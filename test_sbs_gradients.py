import sys,json,copy,tempfile
from pathlib import Path
import numpy as np
from sbs_import import SBSProject,LIBRARY
from sbs_edit import add_node,constant,connect,Edits,save_project,load_project,add_instance
from sbs_compute import Evaluator,sample
from sbs_gradients import set_keys,get_keys,gradient_map,dynamic_gradient
from sbs_functions import dynamic
from test_sbs_pixelprocessor import expression

def run(out):
    rows=[]
    def check(name,fn):
        try:fn();rows.append(dict(name=name,passed=True))
        except Exception as exc:
            import traceback;traceback.print_exc();rows.append(dict(name=name,passed=False,error=repr(exc)))
    def near(a,b):np.testing.assert_allclose(a,b,atol=3e-6,rtol=1e-5)
    p=SBSProject(LIBRARY/'threshold.sbs');pkg=p.package(p.root);g=copy.deepcopy(next(iter(pkg['graphs'].values())));g.update(name='test',nodes=[],inputs=[],outputs=[]);pkg['graphs']['test']=g
    ev=Evaluator(p,64);u=ev.u;v=ev.v;a=np.stack((u,v,1-u,np.ones_like(u)),axis=-1)
    grad=add_node(g,'gradient',[0,0]);keys=[[0,1,0,0,1],[.5,0,1,0,.5],[1,0,0,1,0]]
    check('Color keys roundtrip',lambda:(set_keys(grad,keys),near(get_keys(grad),keys)))
    check('Piecewise interpolation and alpha',lambda:near(gradient_map(grad,np.array([[[.25,0,0,1],[.75,0,0,1]]]))[0],[[.5,.5,0,.75],[0,.5,.5,.25]]))
    check('Gradient clamps endpoints',lambda:near(gradient_map(grad,np.array([[[-1,0,0,1],[2,0,0,1]]]))[0],[[1,0,0,1],[0,0,1,0]]))
    check('Gradient repeat maps 1.25 to .25',lambda:near(gradient_map(grad,np.array([[[1.25,0,0,1]]]),repeat=True)[0,0],[.5,.5,0,.75]))
    check('Horizontal dynamic ramp sampling',lambda:near(dynamic_gradient(a,a,.5,0,False,sample)[...,:3],np.stack((u,np.full_like(u,.5),1-u),axis=-1)))
    check('Vertical dynamic ramp sampling',lambda:near(dynamic_gradient(a,a,.25,1,False,sample)[...,:3],np.stack((np.full_like(u,.25),u,np.full_like(u,.75)),axis=-1)))
    check('Dynamic ramp edge clamp never fades to black',lambda:near(dynamic_gradient(np.ones_like(a),a,1,0,False,sample)[0,0],a[-1,-1]))
    def reject():
        old=grad['xml']
        try:set_keys(grad,[[0,1,0,0,1],[0,0,0,1,1]])
        except ValueError:assert old==grad['xml'];return
        raise AssertionError('duplicate positions accepted')
    check('Invalid keys rejected without mutation',reject)
    def undo():
        edits=Edits(p);edits.change((str(p.root),'test'),lambda g:set_keys(g['nodes'][0],[[0,0,0,0,1],[1,1,1,1,1]]));edits.restore();near(get_keys(pkg['graphs']['test']['nodes'][0]),keys);edits.restore(True)
    check('Key edits undo and redo',undo)
    def persist():
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'gradient.mlsbs';save_project(p,f);q=load_project(f);near(get_keys(q.package(q.root)['graphs']['test']['nodes'][0]),[[0,0,0,0,1],[1,1,1,1,1]])
    check('Key arrays survive native save and reopen',persist)
    for op,inputval,expected in [('pow2',3,8),('log2',8,3),('toint1',-2.8,-2),('not',0,True)]:
        nodes=[('c','const_float1',('constantValueFloat1',str(inputval)),{}),('r',op,None,{'value' if op=='toint1' else 'a':'c'})]
        check('Function '+op,lambda nodes=nodes,expected=expected:near(dynamic(expression(nodes,'r'),{}),expected))
    for op,expected in [('and',False),('or',True),('noteq',True)]:
        nodes=[('a','const_float1',('constantValueFloat1','0'),{}),('b','const_float1',('constantValueFloat1','1'),{}),('r',op,None,{'a':'a','b':'b'})]
        check('Function '+op,lambda nodes=nodes,expected=expected:near(dynamic(expression(nodes,'r'),{}),expected))
    nodes=[('a','const_float2',('constantValueFloat2','3 4'),{}),('r','dot',None,{'a':'a','b':'a'})]
    check('Dot product',lambda:near(dynamic(expression(nodes,'r'),{}),25))
    g=pkg['graphs']['test'];source=add_node(g,'uniform',[0,0]);constant(source,'outputcolor','constantValueFloat4','.25 .25 .25 1');grad=g['nodes'][0];connect(g,source['uid'],source['outputs'][0]['uid'],grad['uid'],'input1')
    def evaluate(n):return Evaluator(p,64).evaluate(str(p.root),'test',n['uid'])
    check('Editable Gradient integrated with evaluator',lambda:near(evaluate(grad)[0,0],[.25,.25,.25,1]))
    dyn=add_node(g,'dyngradient',[0,0]);connect(g,source['uid'],source['outputs'][0]['uid'],dyn['uid'],'input1');connect(g,grad['uid'],grad['outputs'][0]['uid'],dyn['uid'],'input2')
    check('Editable Dynamic Gradient integrated with evaluator',lambda:near(evaluate(dyn)[0,0],[.25,.25,.25,1]))
    trans=add_node(g,'transformation',[0,0]);connect(g,source['uid'],source['outputs'][0]['uid'],trans['uid'],'input1');constant(trans,'mipmapmode','constantValueInt32','1');constant(trans,'manualmiplevel','constantValueInt32','2')
    check('Manual Mipmap preserves constant',lambda:near(evaluate(trans)[0,0],[.25,.25,.25,1]))
    for wrapper in ('normal_normalise','normal_add','normal_blend'):
        def normal_check(wrapper=wrapper):
            source=add_node(g,'uniform',[0,0]);constant(source,'colorswitch','constantValueBool','1');constant(source,'outputcolor','constantValueFloat4','.5 .5 1 1')
            n=add_instance(p,pkg,g,wrapper,[0,0]);r=p.instance(pkg,n)
            for entry in p.package(r['path'])['graphs'][r['graph']]['inputs']:
                if entry['type']=='1':connect(g,source['uid'],source['outputs'][0]['uid'],n['uid'],entry['name'])
            near(evaluate(n)[0,0,:3],[.5,.5,1])
        check('Neutral normal survives '+wrapper,normal_check)
    nodes=[('a','const_float4',('constantValueFloat4','1 2 3 4'),{}),('r','swizzle3',None,{'vector':'a'})]
    check('Implicit Swizzle3 preserves XYZ rather than repeating X',lambda:near(dynamic(expression(nodes,'r'),{}),[1,2,3]))
    Path(out).mkdir(parents=True,exist_ok=True);(Path(out)/'sbs-gradients-verification.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(rows,ensure_ascii=False));return all(r['passed'] for r in rows)
if __name__=='__main__':sys.exit(0 if run(sys.argv[1]) else 1)
