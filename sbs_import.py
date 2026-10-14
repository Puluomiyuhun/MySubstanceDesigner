"""Structural SBS reader preserving original node XML; no SBS/SBSAR execution."""
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
import xml.etree.ElementTree as ET
import collections,hashlib
LIBRARY=Path(r'C:\Program Files\Adobe\Adobe Substance 3D Designer\resources\packages')
def value(e,path,default=''):
    x=e.find(path);return x.get('v',default) if x is not None else default

def parameters(parent):
    result=[]
    if parent is None:return result
    for p in parent.findall('parameter'):
        pv=p.find('paramValue');dynamic=p.find('paramValue/dynamicValue')
        result.append({'name':value(p,'name'),'relative_to':value(p,'relativeTo'),
                       'dynamic':dynamic is not None,'value':[(x.tag,x.get('v')) for x in pv] if pv is not None and dynamic is None else None,
                       'xml':ET.tostring(p,encoding='unicode')})
    return result

class SBSProject:
    def __init__(self,path,library=LIBRARY):
        self.root=Path(path).resolve();self.library=Path(library);self.cache={}
        self.package(self.root)
    def package(self,path):
        path=Path(path).resolve();key=str(path)
        if key in self.cache:return self.cache[key]
        if path.suffix.lower()!='.sbs':raise ValueError('编译 SBSAR 尚不能解析计算图：'+str(path))
        if path.stat().st_size>64*1024*1024:raise ValueError('SBS 文件超过 64 MB')
        raw=path.read_bytes()
        if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise ValueError('不支持带 DTD/实体定义的 SBS')
        root=ET.fromstring(raw)
        if root.tag!='package':raise ValueError('不是 SBS package')
        package={'path':key,'sha256':hashlib.sha256(raw).hexdigest(),'dependencies':{value(d,'uid'):value(d,'filename') for d in root.findall('./dependencies/dependency')},'graphs':{},'resources':[]}
        self.cache[key]=package
        def content(e,prefix=''):
            for item in e:
                name=value(item,'identifier');qualified=prefix+name
                if item.tag=='group':
                    nested=item.find('content')
                    if nested is not None:content(nested,qualified+'/')
                elif item.tag=='resource':
                    pathref=value(item,'source/externalcopy/filename') or value(item,'filepath')
                    package['resources'].append({'name':qualified,'uid':value(item,'uid'),'path':pathref,'resolved':str((path.parent/pathref).resolve()),'exists':(path.parent/pathref).is_file()})
                elif item.tag=='graph':package['graphs'][qualified]=self.parse_graph(item,qualified)
                elif item.tag=='function':package.setdefault('functions',{})[qualified]=ET.tostring(item,encoding='unicode')
        c=root.find('content')
        if c is not None:content(c)
        return package
    def parse_graph(self,g,name):
        graph={'name':name,'uid':value(g,'uid'),'nodes':[],'outputs':[],'inputs':[],'frames':[],'base_parameters':parameters(g.find('baseParameters'))}
        for o in g.findall('./graphOutputs/graphoutput'):
            graph['outputs'].append({'uid':value(o,'uid'),'name':value(o,'identifier'),'usages':[value(u,'name') for u in o.findall('./usages/usage')]})
        for p in g.findall('./paraminputs/paraminput'):
            graph['inputs'].append({'name':value(p,'identifier'),'uid':value(p,'uid'),'type':value(p,'type'),'connectable':value(p,'isConnectable')=='1','xml':ET.tostring(p,encoding='unicode')})
        for n in g.findall('./compNodes/compNode'):
            holder=n.find('compImplementation');impl=list(holder)[0] if holder is not None and len(holder) else ET.Element('unknown')
            node={'uid':value(n,'uid'),'kind':impl.tag,'filter':value(impl,'filter'),'path':value(impl,'path'),'output':value(impl,'output'),'entry':value(impl,'entry'),
                  'position':[float(x) for x in value(n,'GUILayout/gpos','0 0 0').split()],
                  'connections':[{'input':value(c,'identifier'),'source':value(c,'connRef'),'source_output':value(c,'connRefOutput')} for c in n.findall('./connections/connection')],
                  'outputs':[{'uid':value(o,'uid'),'type':value(o,'comptype')} for o in n.findall('./compOutputs/compOutput')],
                  'parameters':parameters(impl.find('parameters')),'output_bridgings':[{'uid':value(o,'uid'),'name':value(o,'identifier')} for o in impl.findall('./outputBridgings/outputBridging')],
                  'xml':ET.tostring(n,encoding='unicode')}
            graph['nodes'].append(node)
        for f in g.findall('./GUIObjects/GUIObject'):
            graph['frames'].append({'type':value(f,'type'),'title':value(f,'title'),'position':[float(x) for x in value(f,'GUILayout/gpos','0 0').split()],
                                    'size':[float(x) for x in value(f,'GUILayout/size','300 200').split()],'color':value(f,'frameColor'),'xml':ET.tostring(f,encoding='unicode')})
        return graph
    def dependency(self,package,uid):
        name=package['dependencies'].get(uid)
        if name is None:return None,'missing dependency UID '+uid
        if name=='?himself':return Path(package['path']),''
        if name.startswith('sbs://'):path=self.library/unquote(name[6:])
        elif '://' in name:return None,'unsupported URI '+name
        else:path=Path(package['path']).parent/name
        path=path.resolve()
        if path.is_file() or str(path) in self.cache:return path,''
        # Recovery only for a unique matching basename inside the supplied project directory.
        candidates=list(self.root.parent.rglob(Path(name).name))
        candidates=[p for p in candidates if p.is_file() and '.autosave' not in p.parts]
        if len(candidates)==1:return candidates[0].resolve(),'relocated by unique basename'
        return None,'missing or ambiguous path '+name
    def instance(self,package,node):
        parsed=urlparse(node['path']);name=unquote(parsed.path).lstrip('/');uid=parse_qs(parsed.query).get('dependency',[''])[0]
        if not uid:path=Path(package['path']);note=''
        else:path,note=self.dependency(package,uid)
        if path is None:return {'status':'missing','graph':name,'reason':note}
        if path.suffix.lower()=='.sbsar':return {'status':'compiled','graph':name,'path':str(path)}
        try:target=self.package(path)
        except Exception as exc:return {'status':'error','graph':name,'path':str(path),'reason':str(exc)}
        if name not in target['graphs']:return {'status':'missing_graph','graph':name,'path':str(path)}
        return {'status':'resolved','graph':name,'path':str(path),'note':note}
    def inspect(self):
        pending=[(str(self.root),name) for name in self.package(self.root)['graphs']];visited=set();graphs=[];issues=[]
        while pending:
            path,name=pending.pop(0)
            if (path,name) in visited:continue
            if len(visited)>=1000:raise ValueError('依赖图超过 1000 个独立图')
            visited.add((path,name));package=self.package(path);g=package['graphs'][name];ids={n['uid'] for n in g['nodes']}
            atomic=collections.Counter(n['filter'] for n in g['nodes'] if n['kind']=='compFilter');wrapped=collections.Counter();resolved=collections.Counter();dynamic=0;edges=0;broken=[]
            for n in g['nodes']:
                edges+=len(n['connections']);dynamic+=sum(p['dynamic'] for p in n['parameters'])
                for c in n['connections']:
                    if c['source'] not in ids:broken.append({'target':n['uid'],**c})
                if n['kind']=='compInstance':
                    r=self.instance(package,n);resolved[r['status']]+=1;wrapped[r['graph']]+=1
                    if r['status']=='resolved':pending.append((r['path'],r['graph']))
                    else:issues.append({'package':path,'graph':name,'node':n['uid'],**r,'owner_graph':name})
            # Reachability is computed independently for each exposed output.
            byid={n['uid']:n for n in g['nodes']};outputs=[]
            for o in g['outputs']:
                stack=[n['uid'] for n in g['nodes'] if n['output']==o['uid']];seen=set()
                while stack:
                    uid=stack.pop()
                    if uid in seen or uid not in byid:continue
                    seen.add(uid);stack.extend(c['source'] for c in byid[uid]['connections'])
                outputs.append({**o,'upstream_nodes':len(seen),'compiled_instances':[uid for uid in seen if byid[uid]['kind']=='compInstance' and self.instance(package,byid[uid])['status']=='compiled']})
            graphs.append({'package':path,'graph':name,'nodes':len(g['nodes']),'edges':edges,'atomic':dict(atomic),'instances':dict(wrapped),'instance_resolution':dict(resolved),'dynamic_parameters':dynamic,'frames':len(g['frames']),'broken_connections':broken,'outputs':outputs})
        return {'root':str(self.root),'root_sha256':self.package(self.root)['sha256'],'graphs':graphs,'packages':len(self.cache),'issues':issues,'resources':[{'package':p['path'],**r} for p in self.cache.values() for r in p['resources']]}
