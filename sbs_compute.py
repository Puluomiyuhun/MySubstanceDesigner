"""Float32 CPU reference evaluator for the first editable SBS branches.

Fixed preview resolution, encoded channel values, not Adobe engine equivalence.
Unknown operations and parameter semantics fail explicitly.
"""
import numpy as np
import xml.etree.ElementTree as ET
from urllib.parse import urlparse,parse_qs,unquote
from PySide6.QtGui import QImage
from sbs_functions import dynamic,input_default
from sbs_import import SBSProject,value
from sbs_filters import PARAMETERS,APPROXIMATE,apply as apply_filter
from sbs_gradients import gradient_map,dynamic_gradient

class Unsupported(ValueError):pass

def read(n,name,default,env=None,call=None):
    p=next((p for p in n['parameters'] if p['name']==name),None)
    if p is None:return default
    if p['relative_to'] not in ('','0'):raise Unsupported(name+'：相对参数尚未求值')
    if p['dynamic']:
        try:return dynamic(p['xml'],dict(env or {}),call=call)
        except ValueError as exc:raise Unsupported(name+'：'+str(exc)) from exc
    if not p['value'] or len(p['value'])!=1:raise Unsupported(name+'：未知参数值')
    tag,text=p['value'][0]
    if tag=='constantValueString':return text
    vals=[float(x) for x in text.split()]
    return vals[0] if len(vals)==1 else np.array(vals,dtype=np.float32)

def sample(image,u,v,tiling=3,nearest=False):
    h,w=image.shape[:2];x=u*w-.5;y=v*h-.5
    def at(ix,iy):
        valid=np.ones(ix.shape,dtype=bool)
        if tiling&1:ix=ix%w
        else:valid&=(ix>=0)&(ix<w);ix=np.clip(ix,0,w-1)
        if tiling&2:iy=iy%h
        else:valid&=(iy>=0)&(iy<h);iy=np.clip(iy,0,h-1)
        return image[iy,ix]*valid[...,None]
    if nearest:return at(np.floor(x+.5).astype(int),np.floor(y+.5).astype(int))
    ix=np.floor(x).astype(int);iy=np.floor(y).astype(int);fx=(x-ix)[...,None];fy=(y-iy)[...,None]
    return ((at(ix,iy)*(1-fx)+at(ix+1,iy)*fx)*(1-fy)+(at(ix,iy+1)*(1-fx)+at(ix+1,iy+1)*fx)*fy).astype(np.float32)

class Evaluator:
    def __init__(self,project,size=256):
        if size not in (64,128,256,512):raise ValueError('预览尺寸限制为 64/128/256/512')
        self.project=project;self.size=size;self.cache={};self.active=set();self.count=0;self.approximations=set()
        self.v,self.u=np.mgrid[:size,:size].astype(np.float32);self.u=(self.u+.5)/size;self.v=(self.v+.5)/size
    def function(self,package,uri,args,env,sampler=None,stack=()):
        if not isinstance(uri,str):raise Unsupported('函数实例缺少路径')
        ref=urlparse(uri);name=unquote(ref.path).lstrip('/');dep=parse_qs(ref.query).get('dependency',[''])[0]
        path,reason=self.project.dependency(package,dep) if dep else (package['path'],'')
        if path is None:raise Unsupported(reason)
        target=self.project.package(path);key=(target['path'],name)
        if key in stack or len(stack)>=32:raise Unsupported('函数实例递归或超过 32 层')
        if 'functions' not in target:
            fresh=SBSProject(path,self.project.library).package(path)
            target['functions']=fresh.get('functions',{})
        xml=target['functions'].get(name)
        if xml is None:raise Unsupported('未找到函数 '+name)
        root=ET.fromstring(xml);local={k:v for k,v in env.items() if k.startswith('$')};declared=set()
        for entry in root.findall('./paraminputs/paraminput'):
            identifier=value(entry,'identifier');declared.add(identifier)
            local[identifier]=input_default({'name':identifier,'xml':ET.tostring(entry,encoding='unicode')})
        if set(args)-declared:raise Unsupported('函数实例输入未定义 '+str(set(args)-declared))
        local.update(args)
        return dynamic(xml,local,sampler,lambda uri,args,env,sampler:self.function(target,uri,args,env,sampler,stack+(key,)))
    def evaluate(self,path,graph,uid,output='',scope=(),env=None,bindings=None):
        if len(scope)>48:raise Unsupported('包装图嵌套超过 48 层，可能存在递归')
        key=(path,graph,uid,output,scope)
        if key in self.cache:return self.cache[key]
        if key in self.active:raise Unsupported('图中存在计算循环')
        self.active.add(key)
        try:
            package=self.project.package(path);g=package['graphs'][graph];nodes={n['uid']:n for n in g['nodes']}
            if uid not in nodes:raise Unsupported('找不到来源节点 '+uid)
            n=nodes[uid]
            if env is None:
                env={}
                for entry in g['inputs']:
                    try:env[entry['name']]=input_default(entry)
                    except ValueError:pass
            bindings=bindings or {}
            env=dict(env)
            env['$size']=np.array([self.size,self.size],np.float32)
            env['$sizelog2']=np.array([np.log2(self.size)]*2,np.float32)
            def call(uri,args,environment,sampler):return self.function(package,uri,args,environment,sampler)
            def param(name,default):return read(n,name,default,env,call)
            if output and output not in [o['uid'] for o in n['outputs']]:raise Unsupported('不存在的输出 UID '+output)
            def source(port):
                c=next((c for c in n['connections'] if c['input']==port),None)
                if c is None:raise Unsupported(n['filter']+' 缺少输入 '+port)
                return self.evaluate(path,graph,c['source'],c['source_output'],scope,env,bindings)
            if n['kind']=='compOutputBridge':result=source('inputNodeOutput')
            elif n['kind']=='compInputBridge':
                entry=next((p for p in g['inputs'] if p['uid']==n['entry']),None)
                if entry is None:raise Unsupported('找不到图输入定义 '+n['entry'])
                if entry['name'] in bindings:result=bindings[entry['name']]()
                else:
                    if entry['name'] not in env:raise Unsupported('图输入未绑定 '+entry['name'])
                    result=env[entry['name']]
                    if entry['type'] in ('1','2'):
                        color=np.asarray(result,np.float32)
                        if color.ndim==0:color=np.array([float(color)]*3+[1.],np.float32)
                        if color.shape!=(4,):raise Unsupported('图像默认值维数错误')
                        result=np.broadcast_to(color,(self.size,self.size,4)).copy()
            elif n['kind']=='compInstance':
                r=self.project.instance(package,n)
                if r['status']!='resolved':raise Unsupported('包装节点 '+r['graph']+'：'+r['status'])
                target=self.project.package(r['path'])['graphs'][r['graph']]
                child_env={}
                for entry in target['inputs']:
                    try:child_env[entry['name']]=input_default(entry)
                    except ValueError:pass
                declared={i['name']:i for i in target['inputs']}
                for p in n['parameters']:
                    if p['name'] in ('outputsize','format','randomseed','pixelsize','pixelratio','tiling'):continue
                    if p['name'] not in declared:raise Unsupported('未知实例参数 '+p['name'])
                    child_env[p['name']]=param(p['name'],None)
                child_bindings={}
                for c in n['connections']:
                    name=c['input']
                    if name not in declared:raise Unsupported('未知实例输入 '+name)
                    child_bindings[name]=lambda c=c:self.evaluate(path,graph,c['source'],c['source_output'],scope,env,bindings)
                    if declared[name]['type'] not in ('1','2'):child_env[name]=child_bindings[name]()
                selected=output or (n['outputs'][0]['uid'] if n['outputs'] else '')
                bridge=next((b for b in n['output_bridgings'] if b['uid']==selected),None)
                out=next((o for o in target['outputs'] if bridge and o['name']==bridge['name']),None)
                node=next((i for i in target['nodes'] if out and i['output']==out['uid']),None)
                if node is None:raise Unsupported('无法确定包装节点的输出桥')
                result=self.evaluate(r['path'],r['graph'],node['uid'],'',scope+((path,graph,uid),),child_env,child_bindings)
            elif n['kind']=='compFilter':
                op=n['filter'];allowed={
                  'uniform':{'colorswitch','outputcolor','tiling'},'bitmap':{'bitmapresourcepath','colorswitch'},
                  'transformation':{'matrix22','offset','tiling','filtering','mipmapmode','manualmiplevel'},
                  'levels':{'levelinlow','levelinhigh','levelinmid','leveloutlow','levelouthigh'},'passthrough':set(),
                  'blend':{'blendingmode','opacitymult','alphablending','colorblending','pixelsize'},
                  'grayscaleconversion':{'channelsweights'},'pixelprocessor':{'colorswitch','perpixel','tiling'},
                  'gradient':{'colorswitch','addressing'},'dyngradient':{'coordinate','uvselector','addressing'}}
                allowed.update(PARAMETERS)
                if op not in allowed:raise Unsupported('底层运算尚未实现：'+op+' [UID '+uid+']')
                for p in n['parameters']:
                    if p['name'] in ('outputsize','format','randomseed'):continue # explicit fixed-resolution preview policy
                    if p['name'] not in allowed[op]:raise Unsupported(op+' 未实现参数 '+p['name'])
                if op in ('gradient','dyngradient'):
                    address=int(param('addressing',0))
                    if address not in (0,1):raise Unsupported('未知渐变寻址方式')
                    if op=='gradient':result=gradient_map(n,source('input1'),param('colorswitch',1)==0,address==1)
                    else:result=dynamic_gradient(source('input1'),source('input2'),float(param('coordinate',0)),int(param('uvselector',0)),address==1,sample)
                    self.approximations.add(op)
                elif op in PARAMETERS:
                    result=apply_filter(op,param,source,self.u,self.v,sample)
                    if op in APPROXIMATE:self.approximations.add(op)
                elif op=='pixelprocessor':
                    local=dict(env);local['$pos']=np.stack((self.u,self.v),axis=-1)
                    pre=next((p for p in n['parameters'] if p['name']=='outputsize' and p['dynamic']),None)
                    if pre:dynamic(pre['xml'],local,call=call) # preserve Set/Sequence side effects at fixed preview size
                    tiling=int(param('tiling',3))
                    if tiling not in range(4):raise Unsupported('Pixel Processor 未实现平铺模式')
                    def sampler(index,filtering,pos,gray):
                        if index<0 or filtering not in (0,1):raise Unsupported('未实现采样输入或过滤模式')
                        pos=np.asarray(pos,np.float32)
                        if pos.shape[-1:]!=(2,):raise Unsupported('采样坐标需要 Float2')
                        pixels=sample(source('input' if index==0 else 'input:'+str(index)),pos[...,0],pos[...,1],tiling,nearest=filtering==0)
                        return pixels[...,:1] if gray else pixels
                    expression=next((p for p in n['parameters'] if p['name']=='perpixel'),None)
                    if expression is None:raise Unsupported('Pixel Processor 缺少逐像素函数')
                    result=np.asarray(dynamic(expression['xml'],local,sampler,call),np.float32)
                    if param('colorswitch',1)==0:
                        if result.ndim==0:result=result.reshape(1)
                        if result.shape[-1:]!=(1,):raise Unsupported('灰度 Pixel Processor 需要 Float 输出')
                        result=np.broadcast_to(result,(self.size,self.size,1))
                        result=np.concatenate((np.repeat(result,3,axis=-1),np.ones_like(result)),axis=-1)
                    else:
                        if result.shape[-1:]!=(4,):raise Unsupported('彩色 Pixel Processor 需要 Float4 输出')
                        result=np.broadcast_to(result,(self.size,self.size,4)).copy()
                    result=np.clip(result,0,1)
                elif op=='uniform':
                    color=np.asarray(param('outputcolor',[0,0,0,1]),np.float32)
                    if color.ndim==0:color=np.array([float(color)]*3+[1.],np.float32)
                    if color.shape!=(4,):raise Unsupported('Uniform outputcolor 需要四通道')
                    if param('colorswitch',1)==0:color=np.array([color[0],color[0],color[0],1],np.float32)
                    result=np.broadcast_to(color,(self.size,self.size,4)).copy()
                elif op=='bitmap':
                    uri=urlparse(param('bitmapresourcepath',''));dep=parse_qs(uri.query).get('dependency',[''])[0]
                    resource_package=package
                    if dep:
                        target,reason=self.project.dependency(package,dep)
                        if target is None:raise Unsupported(reason)
                        resource_package=self.project.package(target)
                    resource=next((r for r in resource_package['resources'] if r['name']==unquote(uri.path).lstrip('/')),None)
                    if resource is None:raise Unsupported('找不到位图资源 '+uri.path)
                    image=QImage(resource['resolved'])
                    if image.isNull():raise Unsupported('无法解码位图 '+resource['resolved'])
                    image=image.convertToFormat(QImage.Format.Format_RGBA64)
                    pixels=np.frombuffer(image.constBits(),np.uint16).reshape(image.height(),image.bytesPerLine()//2)[:,:image.width()*4].reshape(image.height(),image.width(),4).astype(np.float32)/65535
                    result=sample(pixels,self.u,self.v,3)
                    if param('colorswitch',1)==0:
                        # Explicit luminance policy; requires reference exports for Adobe parity.
                        gray=result[...,:3]@np.array([.299,.587,.114],np.float32)
                        result[...,:3]=gray[...,None];result[...,3]=1
                elif op=='transformation':
                    a=source('input1');m=np.asarray(param('matrix22',[1,0,0,1]));offset=np.asarray(param('offset',[0,0]))
                    if m.shape!=(4,) or offset.shape!=(2,):raise Unsupported('变换矩阵/偏移维数错误')
                    mode=int(param('tiling',3));filtering=int(param('filtering',1))
                    mipmode=int(param('mipmapmode',1));miplevel=int(param('manualmiplevel',0))
                    if mipmode!=1 or not 0<=miplevel<=int(np.log2(self.size)):raise Unsupported('当前支持手动 Mipmap 模式及预览尺寸范围内的层级')
                    for _ in range(miplevel):a=(a[0::2,0::2]+a[1::2,0::2]+a[0::2,1::2]+a[1::2,1::2])*.25
                    if miplevel:self.approximations.add('transformation:mipmap')
                    if mode not in range(4) or filtering!=1:raise Unsupported('目前仅支持双线性过滤及 0–3 平铺模式')
                    u=self.u-.5;v=self.v-.5
                    result=sample(a,m[0]*u+m[1]*v+.5+offset[0],m[2]*u+m[3]*v+.5+offset[1],mode)
                elif op=='levels':
                    a=source('input1');lo=np.asarray(param('levelinlow',[0]*4),np.float32);hi=np.asarray(param('levelinhigh',[1]*4),np.float32)
                    mid=np.asarray(param('levelinmid',[.5]*4),np.float32)
                    if np.any(mid<=0) or np.any(mid>=1):raise Unsupported('Levels 中值需要在 0 与 1 之间')
                    d=hi-lo;t=np.where(abs(d)<1e-7,(a>=lo).astype(np.float32),np.clip((a-lo)/np.where(abs(d)<1e-7,1,d),0,1))
                    outlo=np.asarray(param('leveloutlow',[0]*4),np.float32);outhi=np.asarray(param('levelouthigh',[1]*4),np.float32)
                    exponent=np.log(.5)/np.log(mid)
                    result=np.clip(outlo+np.power(t,exponent)*(outhi-outlo),0,1)
                elif op=='grayscaleconversion':
                    a=source('input1');weights=np.asarray(param('channelsweights',[.299,.587,.114,0]),np.float32)
                    if weights.shape!=(4,):raise Unsupported('灰度权重需要四个分量')
                    gray=np.clip(a@weights,0,1);result=np.repeat(gray[...,None],4,axis=2);result[...,3]=1
                elif op=='blend':
                    pixel=np.asarray(param('pixelsize',[1,1]))
                    if pixel.shape!=(2,) or not np.all(pixel==1):raise Unsupported('Blend 目前仅支持 pixelsize=1 1')
                    mode=int(param('blendingmode',0));opacity=float(param('opacitymult',1))
                    if mode not in range(12):raise Unsupported('Blend 模式尚未校准：'+str(mode))
                    if mode>=8:self.approximations.add('blend:'+str(mode))
                    if not 0<=opacity<=1:raise Unsupported('Blend opacity 需要 0–1')
                    if param('colorblending',0)!=0:raise Unsupported('Blend colorblending 非默认模式尚未校准')
                    alpha=int(param('alphablending',1))
                    if alpha not in (0,1):raise Unsupported('Blend Alpha 模式尚未实现')
                    def image_input(port):
                        if any(c['input']==port for c in n['connections']):return source(port)
                        return np.zeros((self.size,self.size,4),np.float32)
                    # Switch's endpoint semantics do not evaluate the discarded branch.
                    if mode==7 and opacity in (0,1) and not any(c['input']=='opacity' for c in n['connections']):
                        result=image_input('source' if opacity==1 else 'destination')
                    else:
                        bg=image_input('destination');fg=image_input('source')
                        mask=source('opacity')[...,:1] if any(c['input']=='opacity' for c in n['connections']) else 1.
                        factor=np.clip(opacity*mask,0,1)
                        operations={0:lambda:fg,1:lambda:bg+fg,2:lambda:bg-fg,3:lambda:bg*fg,
                            4:lambda:bg+2*fg-1,5:lambda:np.maximum(bg,fg),6:lambda:np.minimum(bg,fg),7:lambda:fg,
                            8:lambda:np.divide(bg,fg,out=np.where(bg>0,1.,0.).astype(np.float32),where=fg!=0),
                            9:lambda:np.where(bg<=.5,2*bg*fg,1-2*(1-bg)*(1-fg)),
                            10:lambda:1-(1-bg)*(1-fg),11:lambda:(1-2*fg)*bg*bg+2*fg*bg}
                        mixed=np.clip(operations[mode](),0,1)
                        grayscale=bool(n['outputs'] and n['outputs'][0]['type']=='2')
                        if alpha and not grayscale:
                            effective=factor*fg[...,3:4];result=bg+(mixed-bg)*effective
                            result[...,3:4]=effective+bg[...,3:4]*(1-effective)
                        else:result=bg+(mixed-bg)*factor
                else:result=source('input')
                if n['outputs'] and n['outputs'][0]['type']=='2' and np.ndim(result)==3:
                    result=result.copy();result[...,:3]=result[...,:1];result[...,3]=1

            else:raise Unsupported('尚未实现 '+n['kind'])
            result=np.asarray(result,np.float32)
            if not np.all(np.isfinite(result)):raise Unsupported('节点生成非有限数值 '+uid)
            self.cache[key]=result;self.count+=1;return result
        finally:self.active.discard(key)

def display_image(pixels):
    rgba=(np.clip(pixels,0,1)*255+.5).astype(np.uint8);h,w=rgba.shape[:2]
    return QImage(rgba.data,w,h,w*4,QImage.Format.Format_RGBA8888).copy()
