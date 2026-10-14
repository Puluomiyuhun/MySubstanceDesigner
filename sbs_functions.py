"""Restricted, non-executing interpreter for scalar/vector SBS parameter DAGs."""
import xml.etree.ElementTree as ET
import numpy as np
from sbs_import import value

def literal(element):
    if element is None:raise ValueError('缺少常量值')
    if element.tag=='constantValueString':return element.get('v','')
    if not element.tag.startswith(('constantValueFloat','constantValueInt','constantValueBool')):raise ValueError('不支持常量 '+element.tag)
    v=np.array([float(x) for x in element.get('v','').split()],np.float32)
    if v.size not in (1,2,3,4) or not np.all(np.isfinite(v)):raise ValueError('常量维数或数值错误')
    return float(v[0]) if v.size==1 else v

def input_default(entry):
    e=ET.fromstring(entry['xml']).find('defaultValue')
    if e is None or len(e)!=1:raise ValueError('输入缺少支持的默认值：'+entry['name'])
    return literal(e[0])

def dynamic(xml,environment,sampler=None,call=None):
    root=ET.fromstring(xml).find('paramValue/dynamicValue')
    if root is None:raise ValueError('缺少动态函数图')
    nodes={value(n,'uid'):n for n in root.findall('./paramNodes/paramNode')};cache={};active=set()
    if len(nodes)>2048:raise ValueError('参数函数节点超过 2048')
    stateful=any(value(n,'function') in ('set','sequence') for n in nodes.values());steps=0
    def visit(uid):
        nonlocal steps
        steps+=1
        if steps>20000:raise ValueError('参数函数执行超过 20000 步')
        if not stateful and uid in cache:return cache[uid]
        if uid in active:raise ValueError('参数函数循环')
        if uid not in nodes:raise ValueError('参数函数缺少节点 '+uid)
        active.add(uid);n=nodes[uid];op=value(n,'function')
        refs={value(c,'identifier'):value(c,'connRef') for c in n.findall('./connections/connection')}
        def arg(name):
            if name not in refs:raise ValueError(op+' 缺少输入 '+name)
            return visit(refs[name])
        data=n.find('./funcDatas/funcData/constantValue');data=literal(data[0]) if data is not None and len(data)==1 else None
        try:
            if op in {'const_'+t for t in ('bool','float1','float2','float3','float4','int1','int2','int3','int4')}:
                result=data if data is not None else (0. if op[-1:] not in '234' else np.zeros(int(op[-1]),np.float32))
            elif op.startswith('get_'):
                if data not in environment:raise ValueError('未绑定参数 '+str(data))
                result=environment[data]
            elif op=='ifelse':
                condition=arg('condition')
                result=(arg('ifpath') if condition else arg('elsepath')) if np.ndim(condition)==0 else np.where(condition,arg('ifpath'),arg('elsepath'))
            elif op=='sequence':arg('seqin');result=arg('seqlast')
            elif op=='set':
                if not isinstance(data,str):raise ValueError('Set 缺少变量名')
                result=arg('value');environment[data]=result
            elif op in ('samplelum','samplecol'):
                if sampler is None:raise ValueError('采样函数只能在 Pixel Processor 中执行')
                settings=np.atleast_1d(data if data is not None else [0,0])
                if len(settings)!=2:raise ValueError('未知采样参数结构')
                result=sampler(int(settings[0]),int(settings[1]),arg('pos'),op=='samplelum')
            elif op=='instance':
                if call is None:raise ValueError('尚未绑定函数实例 '+str(data))
                result=call(data,{name:arg(name) for name in refs},environment,sampler)
            elif op.startswith('swizzle'):
                v=np.atleast_1d(arg('vector'));indices=np.atleast_1d(data if data is not None else np.arange(int(op[-1]))).astype(int)
                if np.any(indices<0) or np.any(indices>=v.shape[-1]):raise ValueError('Swizzle 分量越界')
                result=v[...,indices]
                if len(indices)==1 and result.ndim==1:result=float(result[0])
            elif op in ('vector2','vector3','vector4'):
                a=np.atleast_1d(arg('componentsin'));b=np.atleast_1d(arg('componentslast'))
                shape=np.broadcast_shapes(a.shape[:-1],b.shape[:-1]);a=np.broadcast_to(a,shape+(a.shape[-1],));b=np.broadcast_to(b,shape+(b.shape[-1],))
                result=np.concatenate([a,b],axis=-1)
                if result.shape[-1]!=int(op[-1]):raise ValueError('向量拼接维数错误')
            elif op=='abs':result=np.abs(arg('a'))
            elif op=='neg':result=-arg('a')
            elif op=='tofloat':result=np.asarray(arg('value'),np.float32)
            elif op in ('toint1','toint2','toint3','toint4'):
                v=np.asarray(arg('value'))
                if np.any(np.abs(v)>=2147483648):raise ValueError('整数转换超出 int32 范围')
                result=np.trunc(v).astype(np.int32)
            elif op=='pow2':result=np.exp2(arg('a'))
            elif op=='log2':result=np.log2(arg('a'))
            elif op=='not':result=np.logical_not(arg('a'))
            elif op=='atan2':
                v=np.asarray(arg('a'))
                if v.shape[-1:]!=(2,):raise ValueError('Atan2 需要 Float2')
                result=np.arctan2(v[...,1:2],v[...,0:1])
            elif op=='mulscalar':result=arg('a')*arg('scalar')
            elif op in ('floor','ceil','sqrt','sin','cos','tan','log','exp'):
                result=getattr(np,op)(arg('a'))
            else:
                a,b=arg('a'),arg('b')
                if op=='add':result=a+b
                elif op=='sub':result=a-b
                elif op=='mul':result=a*b
                elif op=='div':
                    if np.any(np.asarray(b)==0):raise ValueError('参数函数除零')
                    result=a/b
                elif op=='min':result=np.minimum(a,b)
                elif op=='max':result=np.maximum(a,b)
                elif op=='and':result=np.logical_and(a,b)
                elif op=='or':result=np.logical_or(a,b)
                elif op=='dot':result=np.sum(np.asarray(a)*b,axis=-1,keepdims=np.ndim(a)>1)
                elif op=='mod':
                    if np.any(np.asarray(b)==0):raise ValueError('参数函数模零')
                    result=np.mod(a,b)
                elif op=='lerp':result=a+(b-a)*arg('x')
                elif op=='gt':result=np.asarray(a)>b
                elif op=='gteq':result=np.asarray(a)>=b
                elif op=='lr':result=np.asarray(a)<b
                elif op=='lreq':result=np.asarray(a)<=b
                elif op=='eq':result=np.asarray(a)==b
                elif op=='noteq':result=np.asarray(a)!=b
                else:raise ValueError('未实现参数函数 '+op)
            if result is None or not np.all(np.isfinite(result)):raise ValueError('参数函数返回无效值')
            cache[uid]=result;return result
        finally:active.remove(uid)
    return visit(value(root,'rootnode'))
