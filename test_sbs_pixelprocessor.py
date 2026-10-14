"""Pixel Processor/function fixtures; no Adobe-render equivalence claim."""
import sys,json,copy,tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from sbs_import import SBSProject,LIBRARY,parameters
from sbs_functions import dynamic
from sbs_compute import Evaluator
from sbs_edit import save_project,load_project

def expression(nodes,root):
    element=ET.Element('parameter');ET.SubElement(element,'name',v='perpixel');ET.SubElement(element,'relativeTo',v='0')
    dag=ET.SubElement(ET.SubElement(element,'paramValue'),'dynamicValue');ET.SubElement(dag,'rootnode',v=root);ns=ET.SubElement(dag,'paramNodes')
    for uid,op,data,refs in nodes:
        n=ET.SubElement(ns,'paramNode');ET.SubElement(n,'uid',v=uid);ET.SubElement(n,'function',v=op)
        if data is not None:
            d=ET.SubElement(ET.SubElement(ET.SubElement(n,'funcDatas'),'funcData'),'constantValue');ET.SubElement(d,data[0],v=data[1])
        cs=ET.SubElement(n,'connections')
        for name,ref in refs.items():
            c=ET.SubElement(cs,'connection');ET.SubElement(c,'identifier',v=name);ET.SubElement(c,'connRef',v=ref)
    return ET.tostring(element,encoding='unicode')

def run(out):
    results=[]
    def check(name,fn):
        try:fn();results.append(dict(name=name,passed=True))
        except Exception as exc:
            import traceback;traceback.print_exc();results.append(dict(name=name,passed=False,error=repr(exc)))
    def near(a,b):np.testing.assert_allclose(a,b,atol=2e-6,rtol=1e-5)
    p=SBSProject(LIBRARY/'histogram_select.sbs');pkg=p.package(p.root);g=next(iter(pkg['graphs'].values()))
    pp=next(n for n in g['nodes'] if n['filter']=='pixelprocessor');ev=Evaluator(p,64)
    rgba=np.stack((ev.u,ev.v,1-ev.u,np.full_like(ev.u,.4)),axis=-1)
    pos=('p','get_float2',('constantValueString','$pos'),{})
    def render(nodes,root='s',gray=False,index=0):
        holder=ET.Element('parameters');holder.append(ET.fromstring(expression(nodes,root)))
        c=ET.SubElement(holder,'parameter');ET.SubElement(c,'name',v='colorswitch');ET.SubElement(c,'relativeTo',v='0');ET.SubElement(ET.SubElement(c,'paramValue'),'constantValueBool',v='0' if gray else '1')
        pp['parameters']=parameters(holder);pp['outputs'][0]['type']='2' if gray else '1';pp['connections'][0]['input']='input' if index==0 else 'input:'+str(index)
        return Evaluator(p,64).evaluate(str(p.root),g['name'],pp['uid'],bindings={'input':lambda:rgba})
    for filtering in (0,1):
        check('RGBA identity sampler filter '+str(filtering),lambda filtering=filtering:near(render([pos,('s','samplecol',('constantValueInt2',f'0 {filtering}'),{'pos':'p'})]),rgba))
    check('Second input selected by numbered port',lambda:near(render([pos,('s','samplecol',('constantValueInt2','1 0'),{'pos':'p'})],index=1),rgba))
    check('Gray sample returns first channel and opaque output',lambda:near(render([pos,('s','samplelum',None,{'pos':'p'})],gray=True)[...,0],ev.u))
    offset=('o','const_float2',('constantValueFloat2','0.0078125 0'),{})
    add=('a','add',None,{'a':'p','b':'o'})
    for filtering in (0,1):
        expected=np.roll(rgba,-1,axis=1) if filtering==0 else .5*(rgba+np.roll(rgba,-1,axis=1))
        check('Half-pixel shift including repeat edge '+str(filtering),lambda filtering=filtering,expected=expected:near(render([pos,offset,add,('s','samplecol',('constantValueInt2',f'0 {filtering}'),{'pos':'a'})]),expected))
    nodes=[pos,('x','swizzle1',('constantValueInt32','0'),{'vector':'p'}),('c','const_float1',('constantValueFloat1','.5'),{}),('b','gt',None,{'a':'x','b':'c'}),('s','ifelse',None,{'condition':'b','ifpath':'x','elsepath':'c'})]
    check('Per-pixel conditional field',lambda:near(render(nodes,gray=True)[...,0],np.maximum(ev.u,.5)))
    nodes=[pos,('c','const_float1',('constantValueFloat1','2'),{}),('m','mulscalar',None,{'a':'p','scalar':'c'}),('s','swizzle1',('constantValueInt32','1'),{'vector':'m'})]
    check('Vector field scalar multiplication and swizzle',lambda:near(render(nodes,gray=True)[...,0],np.clip(2*ev.v,0,1)))
    functions=p.package(LIBRARY/'functions.sbs')
    check('Nested real library function: degrees to radians calls Pi',lambda:near(ev.function(functions,'pkg:///Functions/Math/Trigo/deg_to_rad',{'deg':180},{'deg':1}),np.pi))
    check('Real range function accepts a scalar field',lambda:near(ev.function(functions,'pkg:///Functions/Ranges/[-1_1]_to_[0_1]',{'Input':2*ev.u[...,None]-1},{}),ev.u[...,None]))
    nodes=[('a','const_float1',('constantValueFloat1','3'),{}),('set','set',('constantValueString','temp'),{'value':'a'}),('get','get_float1',('constantValueString','temp'),{}),('s','sequence',None,{'seqin':'set','seqlast':'get'})]
    check('Sequence executes Set before Get',lambda:near(dynamic(expression(nodes,'s'),{}),3))
    def invalid():
        try:render([pos,('s','samplecol',('constantValueInt2','0 99'),{'pos':'p'})])
        except ValueError:return
        raise AssertionError('unsupported filter accepted')
    check('Unknown sampler filtering fails explicitly',invalid)
    def persist():
        render([pos,('s','samplecol',None,{'pos':'p'})])
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'pixel.mlsbs';save_project(p,file);q=load_project(file)
            near(Evaluator(q,64).evaluate(str(q.root),g['name'],pp['uid'],bindings={'input':lambda:rgba}),rgba)
            near(Evaluator(q,64).function(q.package(LIBRARY/'functions.sbs'),'pkg:///Functions/Math/Trigo/deg_to_rad',{'deg':90},{}),np.pi/2)
    check('Pixel graph and loaded function definitions survive native save/reload',persist)
    Path(out).mkdir(parents=True,exist_ok=True);(Path(out)/'sbs-pixelprocessor-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(results,ensure_ascii=False,indent=2));return all(r['passed'] for r in results)
if __name__=='__main__':sys.exit(0 if run(sys.argv[1]) else 1)
