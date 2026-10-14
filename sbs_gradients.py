"""Gradient map subset with explicit rejection of unsupported key interpolation."""
import xml.etree.ElementTree as ET
import numpy as np
from sbs_import import value,parameters
from sbs_functions import literal

def gradient_map(node,image,gray=False,repeat=False):
    arrays=ET.fromstring(node['xml']).findall('./compImplementation/compFilter/paramsArrays/paramsArray')
    name='gradient' if gray else 'gradientrgba'
    chosen=next((a for a in arrays if value(a,'name')==name),None)
    if arrays and chosen is None:raise ValueError('渐变数组类型尚未支持：'+str([value(a,'name') for a in arrays]))
    keys=[]
    if chosen is not None:
        for cell in chosen.findall('./paramsArrayCells/paramsArrayCell'):
            data={}
            for p in parameters(cell.find('parameters')):
                if p['dynamic'] or p['relative_to'] not in ('','0'):raise ValueError('渐变关键点动态/相对参数尚未支持')
                pv=ET.fromstring(p['xml']).find('paramValue')
                if pv is None or len(pv)!=1:raise ValueError('渐变关键点格式错误')
                data[p['name']]=literal(pv[0])
            if set(data)-{'position','midpoint','value'}:raise ValueError('未知渐变关键点参数')
            if data.get('midpoint',0)!=0:raise ValueError('渐变非默认 midpoint 尚未校准')
            color=np.asarray(data.get('value',0),np.float32)
            if gray and color.ndim==0:color=np.array([float(color)]*3+[1.],np.float32)
            if color.shape!=(4,):raise ValueError('渐变颜色维数错误')
            position=float(data.get('position',0));keys.append((position,color))
    else:keys=[(0,np.array([0,0,0,1])),(1,np.ones(4))]
    if not keys:raise ValueError('渐变关键点列表为空')
    keys.sort(key=lambda k:k[0]);positions=np.array([k[0] for k in keys]);colors=np.array([k[1] for k in keys])
    if np.any(np.diff(positions)<=0):raise ValueError('渐变关键点重叠尚未支持')
    x=image[...,0];x=x%1 if repeat else np.clip(x,0,1)
    return np.stack([np.interp(x,positions,colors[:,i]) for i in range(4)],axis=-1).astype(np.float32)

def dynamic_gradient(image,ramp,coordinate,orientation,repeat,sample):
    if orientation not in (0,1):raise ValueError('动态渐变仅支持水平/垂直方向')
    x=image[...,0];x=x%1 if repeat else np.clip(x,0,1);pos=np.full_like(x,coordinate)
    u,v=(x,pos) if orientation==0 else (pos,x)
    if not repeat:
        h,w=ramp.shape[:2];u=np.clip(u,.5/w,1-.5/w);v=np.clip(v,.5/h,1-.5/h)
    return sample(ramp,u,v,3)


def set_keys(node,keys):
    """Edit RGBA keys while preserving other raw SBS fields."""
    if node['filter']!='gradient':raise ValueError('请选择 Gradient 节点')
    if not isinstance(keys,list) or not 1<=len(keys)<=256:raise ValueError('需要 1–256 个关键点')
    validated=[]
    for key in keys:
        a=np.asarray(key,dtype=np.float64)
        if a.shape!=(5,) or not np.isfinite(a).all() or np.any(a<0) or np.any(a>1):raise ValueError('每行需要 [位置,R,G,B,A]，均为 0–1')
        validated.append(a)
    validated.sort(key=lambda a:a[0])
    if len({a[0] for a in validated})!=len(validated):raise ValueError('关键点位置不能重复')
    root=ET.fromstring(node['xml']);impl=root.find('./compImplementation/compFilter')
    previous=impl.find('paramsArrays')
    if previous is not None:impl.remove(previous)
    arrays=ET.SubElement(impl,'paramsArrays');arr=ET.SubElement(arrays,'paramsArray');ET.SubElement(arr,'name',v='gradientrgba');ET.SubElement(arr,'uid',v='1');cells=ET.SubElement(arr,'paramsArrayCells')
    for i,a in enumerate(validated,2):
        cell=ET.SubElement(cells,'paramsArrayCell');ET.SubElement(cell,'uid',v=str(i));ps=ET.SubElement(cell,'parameters')
        for name,tag,text in [('position','constantValueFloat1',str(a[0])),('midpoint','constantValueFloat1','0'),('value','constantValueFloat4',' '.join(map(str,a[1:])))]:
            p=ET.SubElement(ps,'parameter');ET.SubElement(p,'name',v=name);ET.SubElement(ET.SubElement(p,'paramValue'),tag,v=text)
    node['xml']=ET.tostring(root,encoding='unicode')
    from sbs_edit import constant
    constant(node,'colorswitch','constantValueBool','1')
    for o in node['outputs']:o['type']='1'
    from sbs_edit import sync
    sync(node)

def get_keys(node):
    result=[]
    for cell in ET.fromstring(node['xml']).findall('./compImplementation/compFilter/paramsArrays/paramsArray/paramsArrayCells/paramsArrayCell'):
        data={p['name']:p for p in parameters(cell.find('parameters'))}
        if any(p['dynamic'] for p in data.values()):raise ValueError('动态关键点不能用常量编辑器打开')
        def number(name,default):
            p=data.get(name)
            if p is None:return default
            return literal(ET.fromstring(p['xml']).find('paramValue')[0])
        if number('midpoint',0)!=0:raise ValueError('非默认 midpoint 暂不能编辑')
        color=np.atleast_1d(number('value',[0,0,0,1])).tolist()
        if len(color)==1:color=color*3+[1]
        result.append([float(number('position',0))]+color)
    return result or [[0,0,0,0,1],[1,1,1,1,1]]
