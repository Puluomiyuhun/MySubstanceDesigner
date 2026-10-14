"""Independent invariants and real package round trips for the CPU filter subset."""
import sys,json,copy
from pathlib import Path
import numpy as np
from sbs_import import SBSProject,LIBRARY
from sbs_compute import Evaluator,sample
from sbs_filters import apply
from sbs_edit import add_node,add_instance,connect,constant

def run(out):
    e=Evaluator(SBSProject(LIBRARY/'rgba_merge.sbs'),64);u,v=e.u,e.v
    a=np.stack((u,v,1-u,np.full_like(u,.7)),axis=-1);flat=np.full_like(a,.4);flat[...,3]=1
    results=[]
    def near(x,y):np.testing.assert_allclose(x,y,atol=3e-6,rtol=1e-5)
    def check(name,fn):
        try:fn();results.append(dict(name=name,passed=True))
        except Exception as exc:
            import traceback;traceback.print_exc();results.append(dict(name=name,passed=False,error=repr(exc)))
    def render(op,params={},image=a,field=flat):return apply(op,lambda k,d:params.get(k,d),lambda port:image if port=='input1' else field,u,v,sample)
    for op in ('blur','dirmotionblur','warp','directionalwarp'):
        check(op+' zero intensity identity',lambda op=op:near(render(op,{'intensity':0}),a))
    check('HSL neutral preserves RGB and alpha',lambda:near(render('hsl'),a))
    check('HSL desaturation has equal RGB',lambda:near(render('hsl',{'saturation':0})[...,0],render('hsl',{'saturation':0})[...,2]))
    check('HSL lightness endpoints',lambda:(near(render('hsl',{'luminosity':0})[...,:3],0),near(render('hsl',{'luminosity':1})[...,:3],1)))
    red=np.zeros_like(a);red[...,0]=1;red[...,3]=.7
    check('HSL one-third hue rotation red to green',lambda:near(render('hsl',{'hue':.5+1/3},red)[0,0],[0,1,0,.7]))
    for op in ('blur','dirmotionblur'):
        check(op+' constant preservation',lambda op=op:near(render(op,{'intensity':8},flat),flat))
    impulse=np.zeros_like(a);impulse[32,32]=1
    def blur_impulse():
        image=render('blur',{'intensity':4},impulse)
        near(image.sum((0,1)),np.ones(4));near(image[31,32],image[33,32]);assert 0<image[32,32,0]<1
    check('Gaussian impulse conserves mass and symmetry',blur_impulse)
    check('Directional blur horizontal does not spread into other rows',lambda:near(render('dirmotionblur',{'intensity':8},impulse)[31],0))
    check('Flat height normal is neutral with forced alpha',lambda:near(render('normal',{'input2alpha':0},flat),np.broadcast_to([.5,.5,1,1],a.shape)))
    def normal():
        n=render('normal',{'input2alpha':0});flipped=render('normal',{'input2alpha':0,'inversedy':1})
        near(np.linalg.norm(n[...,:3]*2-1,axis=-1),1);near(n[...,1]+flipped[...,1],1)
    check('Normal vectors unit length and Y switch reverses only Y',normal)
    check('Normal alpha can carry input height',lambda:near(render('normal',{'input2alpha':1})[...,3],u))
    check('Flat gradient creates no Warp displacement',lambda:near(render('warp',{'intensity':20}),a))
    white=np.ones_like(a)
    check('Directional Warp 4 units shifts one preview pixel',lambda:near(render('directionalwarp',{'intensity':4},a,white),np.roll(a,-1,axis=1)))
    check('Directional Warp quarter turn shifts vertically',lambda:near(render('directionalwarp',{'intensity':4,'warpangle':.25},a,white),np.roll(a,-1,axis=0)))
    check('Shuffle can mix both inputs and alpha',lambda:near(render('shuffle',{'channelred':6,'channelgreen':0,'channelblue':3,'channelalpha':5})[0,0],[.4,a[0,0,0],.7,.4]))
    p=SBSProject(LIBRARY/'rgba_merge.sbs');pkg=p.package(p.root);g=copy.deepcopy(next(iter(pkg['graphs'].values())));g.update(name='fixture',nodes=[],inputs=[],outputs=[]);pkg['graphs']['fixture']=g
    src=add_node(g,'uniform',[0,0]);constant(src,'colorswitch','constantValueBool','1');constant(src,'outputcolor','constantValueFloat4','.2 .4 .6 .8')
    split=add_instance(p,pkg,g,'rgba_split',[200,0]);connect(g,src['uid'],src['outputs'][0]['uid'],split['uid'],'RGBA')
    merge=add_instance(p,pkg,g,'rgba_merge',[400,0])
    for name,port in zip(('R','G','B','A'),split['outputs']):connect(g,split['uid'],port['uid'],merge['uid'],name)
    def evalnode(n):return Evaluator(p,64).evaluate(str(p.root),'fixture',n['uid'])
    check('Actual RGBA Split four outputs reconnect to actual Merge',lambda:near(evalnode(merge)[0,0],[.2,.4,.6,.8]))
    inv=add_instance(p,pkg,g,'normal_invert',[200,200]);connect(g,src['uid'],src['outputs'][0]['uid'],inv['uid'],'Normal')
    for key in ('invert_red','invert_green','invert_blue','invert_alpha'):constant(inv,key,'constantValueBool','1')
    check('Actual Normal Invert toggles all four channels',lambda:near(evalnode(inv)[0,0],[.8,.6,.4,.2]))
    for op in ('blur','dirmotionblur','warp','directionalwarp','normal','hsl','shuffle'):
        def integration(op=op):
            n=add_node(g,op,[0,0]);connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'input1')
            if op in ('warp','directionalwarp'):connect(g,src['uid'],src['outputs'][0]['uid'],n['uid'],'inputgradient' if op=='warp' else 'inputintensity')
            val=evalnode(n);assert val.shape==(64,64,4) and np.isfinite(val).all()
            if op in ('normal','hsl','shuffle'):assert n['outputs'][0]['type']=='1'
            if op in ('blur','dirmotionblur'):near(val[0,0],[.2,.4,.6,.8])
        check('Editable atom routes through Evaluator: '+op,integration)
    Path(out).mkdir(parents=True,exist_ok=True);(Path(out)/'sbs-filters-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(results,ensure_ascii=False,indent=2));return all(r['passed'] for r in results)
if __name__=='__main__':sys.exit(0 if run(sys.argv[1]) else 1)
