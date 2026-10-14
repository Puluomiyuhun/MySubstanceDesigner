"""Numerical fixtures and real installed SBS wrapper evaluation (not Adobe render goldens)."""
import sys,copy,json,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from sbs_import import SBSProject
from sbs_edit import add_node,add_instance,connect,constant,WRAPPERS
from sbs_compute import Evaluator,Unsupported
from sbs_reference import render_reference

def run(path,out):
    p=SBSProject(path);pkg=p.package(p.root);g=copy.deepcopy(next(iter(pkg['graphs'].values())))
    g.update(name='numeric_fixture',nodes=[],inputs=[],outputs=[],frames=[]);pkg['graphs'][g['name']]=g
    x=np.tile(np.linspace(0,1,64,dtype=np.float32),(64,1));image=np.repeat(x[...,None],4,axis=2);image[...,3]=1
    reverse=image.copy();reverse[...,:3]=1-reverse[...,:3]
    def input_node(name):
        n=add_node(g,'uniform',[0,0]);entry='entry_'+n['uid'];n.update(kind='compInputBridge',filter='',entry=entry,parameters=[])
        g['inputs'].append({'name':name,'uid':entry,'type':'2','connectable':True,'xml':f'<paraminput><defaultValue><constantValueFloat1 v="0"/></defaultValue></paraminput>'});return n
    src=input_node('fixture');fg=input_node('foreground')
    bindings={'fixture':lambda:image,'foreground':lambda:reverse}
    def render(n,e=None):return (e or Evaluator(p,64)).evaluate(str(p.root),g['name'],n['uid'],bindings=bindings)
    def wrapper(name,params=None):
        n=add_instance(p,pkg,g,name,[250,0]);r=p.instance(pkg,n);target=p.package(r['path'])['graphs'][r['graph']]
        for entry in target['inputs']:
            if entry['type'] in ('1','2'):connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],entry['name'])
        for key,val in (params or {}).items():constant(n,key,'constantValueBool' if key in ('invert','switch','Invert_Position') else 'constantValueFloat1',str(val))
        return n
    results=[]
    def check(name,fn):
        try:fn();results.append({'name':name,'passed':True})
        except Exception as exc:
            import traceback
            traceback.print_exc();results.append({'name':name,'passed':False,'error':repr(exc)})
    def near(actual,expected):np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=1e-5)
    for name in WRAPPERS:check('Real SBS definition executes: '+name,lambda name=name:render(wrapper(name)))
    for name in ('invert','invert_grayscale'):
        for enabled in (0,1):check(f'{name} parameter override {enabled}',lambda name=name,enabled=enabled:near(render(wrapper(name,{'invert':enabled}))[...,0],1-x if enabled else x))
    check('Clamp grayscale min/max applied via two real Blend nodes',lambda:near(render(wrapper('clamp_grayscale',{'min':.2,'max':.7}))[...,0],np.clip(x,.2,.7)))
    for name in ('contrast_luminosity','contrast_luminosity_grayscale'):
        # Source DAG with Contrast=0 and Luminosity=.2 sets output low=.2, high=1.
        check(name+' output-range formula',lambda name=name:near(render(wrapper(name,{'Contrast':0,'Luminosity':.2}))[...,0],.2+.8*x))
    for name,values in [('histogram_scan',[{'Position':.3,'Contrast':.2,'Invert_Position':0},{'Position':.7,'Contrast':1,'Invert_Position':1}]),('histogram_range',[{'range':.4,'position':.4},{'range':0,'position':.8}]),('histogram_shift',[{'position':0},{'position':.3},{'position':1}])]:
        for parameters in values:
            check(name+' vs extracted DAG '+str(parameters),lambda name=name,parameters=parameters:near(render(wrapper(name,parameters))[...,0],render_reference(name,parameters,x)))
    for parameters in ({'position':.3,'range':.4,'constrast':.2},{'position':.8,'range':.2,'constrast':.7},{'position':.5,'range':0,'constrast':0}):
        check('Histogram Select Pixel Processor vs extracted DAG '+str(parameters),lambda parameters=parameters:near(render(wrapper('histogram_select',parameters))[...,0],render_reference('histogram_select',parameters,x)))
    def isolation():
        a=wrapper('histogram_range',{'range':.4,'position':.4});b=wrapper('histogram_range',{'range':.2,'position':.8});e=Evaluator(p,64)
        near(render(a,e)[...,0],.2+.4*x);near(render(b,e)[...,0],.7+.2*x);near(render(a,e)[...,0],.2+.4*x)
    check('Two instances of one wrapper have isolated parameters and cached outputs',isolation)
    def blend(mode):
        n=add_node(g,'blend',[250,0]);constant(n,'blendingmode','constantValueInt32',str(mode));constant(n,'opacitymult','constantValueFloat1','.35')
        connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'destination');connect(g,fg['uid'],fg['outputs'][0]['uid'],n['uid'],'source');return n
    funcs=[lambda:x*0+1-x,lambda:np.ones_like(x),lambda:np.maximum(2*x-1,0),lambda:x*(1-x),lambda:1-x,lambda:np.maximum(x,1-x),lambda:np.minimum(x,1-x),lambda:1-x]
    for mode,formula in enumerate(funcs):check('Blend enum '+str(mode)+' opacity fixture',lambda mode=mode,formula=formula:near(render(blend(mode))[...,0],.65*x+.35*formula()))
    extra=[lambda:np.minimum(np.divide(x,1-x,out=np.ones_like(x),where=x!=1),1),lambda:np.where(x<=.5,2*x*(1-x),1-2*(1-x)*x),lambda:1-x*(1-x),lambda:(2*x-1)*x*x+2*(1-x)*x]
    for mode,formula in enumerate(extra,8):check('Additional Blend mode '+str(mode),lambda mode=mode,formula=formula:near(render(blend(mode))[...,0],.65*x+.35*formula()))
    def mask():
        n=blend(0);connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'opacity');near(render(n)[...,0],x+(1-2*x)*(.35*x))
    check('Blend opacity image multiplies opacity parameter',mask)
    def lazy_switch():
        bad=add_node(g,'uniform',[0,0]);bad['filter']='unimplemented_fixture';n=blend(7);connect(g,bad['uid'],bad['outputs'][0]['uid'],n['uid'],'source')
        constant(n,'opacitymult','constantValueFloat1','0');near(render(n)[...,0],x)
        constant(n,'opacitymult','constantValueFloat1','1')
        try:render(n)
        except Unsupported:return
        raise AssertionError('Switch evaluated the wrong branch')
    check('Switch lazily skips unsupported inactive branch and rejects active one',lazy_switch)
    def color_alpha():
        n=blend(0);n['outputs'][0]['type']='1';constant(n,'opacitymult','constantValueFloat1','1')
        rgba=reverse.copy();rgba[...,3]=.25;old=bindings['foreground'];bindings['foreground']=lambda:rgba
        try:
            near(render(n)[...,0],.75*x+.25*(1-x));near(render(n)[...,3],1)
            constant(n,'alphablending','constantValueInt32','0');near(render(n),rgba)
        finally:bindings['foreground']=old
    check('Color Copy source alpha and explicitly disabled alpha fixture',color_alpha)
    def levels_mid():
        n=add_node(g,'levels',[200,0]);connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'input1');constant(n,'levelinmid','constantValueFloat4','.25 .25 .25 .5')
        near(render(n)[...,0],np.sqrt(x))
    check('Levels normalized midpoint .25 maps through sqrt curve',levels_mid)
    def grayscale():
        n=add_node(g,'grayscaleconversion',[200,0]);connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'input1');constant(n,'channelsweights','constantValueFloat4','0 0 0 1');near(render(n)[...,0],1)
    check('Grayscale conversion can extract alpha using channel weights',grayscale)
    def uniform_color():
        n=add_node(g,'uniform',[0,0]);constant(n,'colorswitch','constantValueBool','1');constant(n,'outputcolor','constantValueFloat4','.1 .2 .3 .4')
        near(render(n)[0,0],[.1,.2,.3,.4]);assert n['outputs'][0]['type']=='1'
        assert ET.fromstring(n['xml']).find('./compOutputs/compOutput/comptype').get('v')=='1'
    check('Uniform color switch updates evaluation type and serialized output metadata',uniform_color)
    for r in results:print(r)
    Path(out).mkdir(parents=True,exist_ok=True);(Path(out)/'sbs-node-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return all(r['passed'] for r in results)

if __name__=='__main__':sys.exit(0 if run(sys.argv[1],sys.argv[2]) else 1)
