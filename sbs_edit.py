"""Editable SBS project snapshots; original dependencies are never overwritten."""
import copy,json,math
import xml.etree.ElementTree as ET
from pathlib import Path
from sbs_import import SBSProject,parameters

PORTS={'uniform':[],'bitmap':[],'transformation':['input1'],'levels':['input1'],
       'passthrough':['input'],'blend':['destination','source','opacity'],'grayscaleconversion':['input1']}
DEFAULTS={
 'uniform':{'colorswitch':('constantValueBool','0'),'outputcolor':('constantValueFloat4','0.5 0.5 0.5 1')},
 'transformation':{'matrix22':('constantValueFloat4','1 0 0 1'),'offset':('constantValueFloat2','0 0'),'tiling':('constantValueInt32','3')},
 'levels':{'levelinlow':('constantValueFloat4','0 0 0 0'),'levelinhigh':('constantValueFloat4','1 1 1 1'),'levelinmid':('constantValueFloat4','0.5 0.5 0.5 0.5'),'leveloutlow':('constantValueFloat4','0 0 0 0'),'levelouthigh':('constantValueFloat4','1 1 1 1')},
 'passthrough':{},
 'blend':{'blendingmode':('constantValueInt32','0'),'opacitymult':('constantValueFloat1','1'),'alphablending':('constantValueInt32','1')},
 'grayscaleconversion':{'channelsweights':('constantValueFloat4','0.299 0.587 0.114 0')}}
PORTS.update({'blur':['input1'],'dirmotionblur':['input1'],'normal':['input1'],'hsl':['input1'],
              'warp':['input1','inputgradient'],'directionalwarp':['input1','inputintensity'],'shuffle':['input1','input2']})
for op,values in {
    'blur':{'intensity':1},'dirmotionblur':{'intensity':8,'mblurangle':0},
    'warp':{'intensity':1},'directionalwarp':{'intensity':10,'warpangle':0},
    'normal':{'intensity':10},'hsl':{'hue':.5,'saturation':.5,'luminosity':.5}}.items():
    DEFAULTS[op]={k:('constantValueFloat1',str(v)) for k,v in values.items()}
DEFAULTS['normal'].update({'inversedy':('constantValueBool','0'),'input2alpha':('constantValueBool','0')})
DEFAULTS['shuffle']={k:('constantValueInt32',str(i)) for i,k in enumerate(('channelred','channelgreen','channelblue','channelalpha'))}

WRAPPERS={'invert_grayscale':'invert','invert':'invert','histogram_scan':'histogram_scan',
          'histogram_range':'histogram_range','histogram_shift':'histogram_shift','histogram_select':'histogram_select',
          'clamp_grayscale':'clamp','contrast_luminosity_grayscale':'contrast_luminosity',
          'contrast_luminosity':'contrast_luminosity','switch_grayscale':'blend_switch','switch':'blend_switch'}
WRAPPERS.update({'rgba_split':'rgba_split','rgba_merge':'rgba_merge','normal_invert':'normal_invert','normal_intensity':'normal_intensity'})
WRAPPERS.update({'threshold':'threshold','quantize':'quantize','quantize_grayscale':'quantize',
    'rgb-a_split':'rgb-a_split','rgb-a_merge':'rgb-a_merge','mirror':'mirror','mirror_grayscale':'mirror',
    'normal_normalise':'normal_normalise','normal_add':'normal_add','normal_blend':'normal_blend'})
PORTS.update({'gradient':['input1'],'dyngradient':['input1','input2']})
DEFAULTS['gradient']={'colorswitch':('constantValueBool','1'),'addressing':('constantValueBool','0')}
DEFAULTS['dyngradient']={'coordinate':('constantValueFloat1','0'),'uvselector':('constantValueInt32','0'),'addressing':('constantValueBool','0')}

def add_instance(project,package,graph,name,position):
    file=project.library/(WRAPPERS[name]+'.sbs');target=project.package(file)['graphs'][name]
    dep=next((uid for uid in package['dependencies'] if project.dependency(package,uid)[0]==file.resolve()),None)
    if dep is None:
        dep=str(max([int(i) for i in package['dependencies'] if i.isdigit()]+[100])+1)
        package['dependencies'][dep]=str(file.resolve())
    n=add_node(graph,'passthrough',position);n['kind']='compInstance';n['filter']='';n['path']=f'pkg:///{name}?dependency={dep}'
    numeric=[int(v) for node in graph['nodes'] for v in [node['uid']]+[o['uid'] for o in node['outputs']] if v.isdigit()]
    next_id=max(numeric)+1;n['outputs']=[];n['output_bridgings']=[]
    gray='grayscale' in name or name.startswith('histogram') or name=='threshold'
    for index,o in enumerate(target['outputs']):
        uid=str(next_id+index);n['outputs'].append({'uid':uid,'type':'2' if gray or name=='rgba_split' or (name=='rgb-a_split' and o['name']=='A') else '1'});n['output_bridgings'].append({'uid':uid,'name':o['name']})
    xml=ET.Element('compNode');ET.SubElement(xml,'uid',v=n['uid']);outs=ET.SubElement(xml,'compOutputs')
    for o in n['outputs']:
        e=ET.SubElement(outs,'compOutput');ET.SubElement(e,'uid',v=o['uid']);ET.SubElement(e,'comptype',v=o['type'])
    instance=ET.SubElement(ET.SubElement(xml,'compImplementation'),'compInstance');ET.SubElement(instance,'path',v=n['path']);bridges=ET.SubElement(instance,'outputBridgings')
    for o in n['output_bridgings']:
        e=ET.SubElement(bridges,'outputBridging');ET.SubElement(e,'uid',v=o['uid']);ET.SubElement(e,'identifier',v=o['name'])
    n['xml']=ET.tostring(xml,encoding='unicode');sync(n);return n

def load_project(path):
    if Path(path).suffix.lower()!='.mlsbs':return SBSProject(path)
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if data.get('format')!='MaterialLabSBS-1':raise ValueError('不支持的 SBS 编辑工程格式')
    p=SBSProject.__new__(SBSProject);p.root=Path(data['root']);p.library=Path(data['library']);p.cache=data['packages']
    if str(p.root) not in p.cache:raise ValueError('工程缺少根包')
    return p

def save_project(project,path):
    project.inspect() # Include all resolvable dependencies, including edited child graphs.
    target=Path(path)
    if target.suffix.lower()!='.mlsbs':raise ValueError('请使用 .mlsbs 扩展名')
    data={'format':'MaterialLabSBS-1','root':str(project.root),'library':str(project.library),'packages':project.cache}
    temporary=target.with_suffix('.mlsbs.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');temporary.replace(target)

def constant(node,name,tag,text):
    if tag not in ('constantValueString','constantValueBool','constantValueInt1','constantValueInt32','constantValueInt2','constantValueInt3','constantValueInt4','constantValueFloat1','constantValueFloat2','constantValueFloat3','constantValueFloat4'):
        raise ValueError('暂不支持编辑此常量类型：'+tag)
    if tag!='constantValueString':
        parts=text.split();count=int(tag[-1]) if tag[-1] in '1234' and tag!='constantValueInt32' else 1
        if len(parts)!=count:raise ValueError(f'需要 {count} 个数值')
        values=[float(x) for x in parts]
        if not all(math.isfinite(x) for x in values):raise ValueError('不能使用 NaN 或无穷大')
        if 'Int' in tag and not all(x.is_integer() for x in values):raise ValueError('需要整数')
        if tag=='constantValueBool' and values[0] not in (0,1):raise ValueError('布尔值只能为 0 或 1')
    old=next((p for p in node['parameters'] if p['name']==name),None)
    if old and (old['dynamic'] or old['relative_to'] not in ('','0')):raise ValueError('动态表达式或相对参数暂不支持常量覆盖')
    e=ET.Element('parameter');ET.SubElement(e,'name',v=name);ET.SubElement(e,'relativeTo',v='0')
    ET.SubElement(ET.SubElement(e,'paramValue'),tag,v=text)
    holder=ET.Element('parameters');holder.append(e);p=parameters(holder)[0]
    if old:node['parameters'][node['parameters'].index(old)]=p
    else:node['parameters'].append(p)
    if name=='colorswitch' and node['filter'] in ('uniform','bitmap'):
        for output in node['outputs']:output['type']='1' if float(text) else '2'
    sync(node)

def sync(n):
    e=ET.fromstring(n['xml']);layout=e.find('GUILayout')
    for output in e.findall('./compOutputs/compOutput'):
        uid=output.find('uid');kind=output.find('comptype')
        current=next((o for o in n['outputs'] if uid is not None and o['uid']==uid.get('v')),None)
        if current and kind is not None:kind.set('v',current['type'])
    if layout is None:layout=ET.SubElement(e,'GUILayout')
    pos=layout.find('gpos')
    if pos is None:pos=ET.SubElement(layout,'gpos')
    pos.set('v',' '.join(map(str,n['position'])))
    links=e.find('connections')
    if links is not None:e.remove(links)
    if n['connections']:
        links=ET.SubElement(e,'connections')
        for c in n['connections']:
            ce=ET.SubElement(links,'connection')
            for tag,key in [('identifier','input'),('connRef','source'),('connRefOutput','source_output')]:
                if c[key]:ET.SubElement(ce,tag,v=c[key])
    impl=e.find('compImplementation/'+n['kind'])
    if impl is not None:
        old=impl.find('parameters')
        if old is not None:impl.remove(old)
        if n['parameters']:
            ps=ET.SubElement(impl,'parameters')
            for p in n['parameters']:ps.append(ET.fromstring(p['xml']))
    n['xml']=ET.tostring(e,encoding='unicode')

def connect(graph,source,output,target,port):
    nodes={n['uid']:n for n in graph['nodes']}
    if source not in nodes or target not in nodes:raise ValueError('找不到节点')
    if output not in [o['uid'] for o in nodes[source]['outputs']]:raise ValueError('找不到源输出端口')
    if nodes[target]['filter'] in ('levels','transformation','blend') and next(o['type'] for o in nodes[source]['outputs'] if o['uid']==output) not in ('1','2'):
        raise ValueError('此输入需要图像，不能连接数值输出')
    stack=[source];seen=set()
    while stack:
        uid=stack.pop()
        if uid==target:raise ValueError('连线会产生循环')
        if uid in seen:continue
        seen.add(uid);stack.extend(c['source'] for c in nodes[uid]['connections'] if c['source'] in nodes)
    n=nodes[target];n['connections']=[c for c in n['connections'] if c['input']!=port]
    n['connections'].append({'input':port,'source':source,'source_output':output})
    if port=='input1' and n['filter'] in ('blur','dirmotionblur','warp','directionalwarp'):
        kind=next(o['type'] for o in nodes[source]['outputs'] if o['uid']==output)
        for o in n['outputs']:o['type']=kind
    sync(n)

def add_node(graph,kind,position):
    if kind not in DEFAULTS:raise ValueError('此类型尚未支持新建')
    used=[int(v) for n in graph['nodes'] for v in [n['uid']]+[o['uid'] for o in n['outputs']] if v.isdigit()]
    uid=str(max(used+[100])+1);out=str(int(uid)+1)
    e=ET.fromstring(f'<compNode><uid v="{uid}"/><compOutputs><compOutput><uid v="{out}"/><comptype v="2"/></compOutput></compOutputs><compImplementation><compFilter><filter v="{kind}"/></compFilter></compImplementation></compNode>')
    n={'uid':uid,'kind':'compFilter','filter':kind,'path':'','output':'','entry':'','position':list(position)+[0.],
       'connections':[],'outputs':[{'uid':out,'type':'2'}],'parameters':[],'output_bridgings':[],'xml':ET.tostring(e,encoding='unicode')}
    for name,(tag,value) in DEFAULTS[kind].items():constant(n,name,tag,value)
    if kind in ('normal','hsl','shuffle','gradient','dyngradient'):n['outputs'][0]['type']='1'
    sync(n);graph['nodes'].append(n);return n

class Edits:
    def __init__(self,project):self.project=project;self.undo=[];self.redo=[];self.dirty=False
    def change(self,key,action):
        g=self.project.package(key[0])['graphs'][key[1]];before=copy.deepcopy(g)
        try:action(g)
        except Exception:
            g.clear();g.update(before);raise
        if before!=g:self.undo.append((key,before));self.undo=self.undo[-40:];self.redo.clear();self.dirty=True
    def restore(self,redo=False):
        source=self.redo if redo else self.undo;dest=self.undo if redo else self.redo
        if not source:return None
        key,snapshot=source.pop();graphs=self.project.package(key[0])['graphs'];dest.append((key,copy.deepcopy(graphs[key[1]])))
        graphs[key[1]]=snapshot;self.dirty=True;return key
