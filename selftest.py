"""Native GL integration and rotation regression checks. Run main.py --self-test."""
import json
import statistics
import time
from OpenGL import GL as gl
from model import ROOT,DEFINITIONS,make_node,empty,preset


def run(app,window):
    view=window.material
    rows=[]
    benchmark={}
    def check(name,fn):
        try:
            fn()
            rows.append(dict(name=name,passed=True))
        except Exception as exc:
            rows.append(dict(name=name,passed=False,error=str(exc)))
    def require(condition,message):
        if not condition:
            raise AssertionError(message)
    def set_graph(g,size=64):
        view.set_graph(g,size)
        view.evaluate()
    try:
        require(view.ready and not view.error,view.error or 'OpenGL did not initialize')
        view.makeCurrent()
        for d in DEFINITIONS:
            def test_node(d=d):
                g=empty()
                source=make_node(1,'clouds')
                node=make_node(2,d['id'])
                node['inputs']=[1]*len(node['inputs'])
                g['nodes']=[source,node]
                set_graph(g)
                image=view.images[2]
                thumbnail_dir=ROOT/'assets/thumbnails'
                thumbnail_dir.mkdir(parents=True,exist_ok=True)
                image.save(str(thumbnail_dir/(d['id']+'.png')),'PNG')
                require(image.width()==64 and image.height()==64,'image dimensions')
                require(image.pixelColor(31,31).alpha()==255,'opaque output')
                require(gl.glGetError()==gl.GL_NO_ERROR,'OpenGL error')
            check('GPU '+d['name'],test_node)
        def threshold():
            g=empty()
            g['nodes']=[make_node(1,'uniform',params=['#000000']),make_node(2,'threshold')]
            g['nodes'][1]['inputs']=[1]
            for mode,expected in ((0,0),(1,255),(2,0),(3,255)):
                g['nodes'][1]['p']=[0,mode]
                set_graph(g)
                require(view.images[2].pixelColor(32,32).red()==expected,'comparison mode '+str(mode))
        check('Threshold equality modes',threshold)
        def invalidation():
            g=empty()
            g['nodes']=[make_node(1,'uniform',params=['#000000']),make_node(2,'invert')]
            g['nodes'][1]['inputs']=[1]
            set_graph(g)
            require(view.images[2].pixelColor(0,0).red()==255,'black -> white')
            g['nodes'][0]['p']=['#ffffff']
            set_graph(g)
            require(view.images[2].pixelColor(0,0).red()==0,'white -> black')
            before=view.evaluations
            set_graph(g)
            require(view.evaluations==before,'unchanged graph should use cache')
        check('Cache propagation and reuse',invalidation)
        def export():
            set_graph(preset(),512)
            file=ROOT/'test-output.png'
            require(view.images[7].save(str(file),'PNG'),'PNG write')
            require(file.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n','PNG signature')
        check('Native 512px PNG export',export)
        def rotation():
            baseline=(view.evaluations,view.readbacks)
            samples=[]
            for i in range(180):
                view.yaw=i*.02
                start=time.perf_counter()
                view.draw_material()
                gl.glFinish()
                samples.append((time.perf_counter()-start)*1000)
            require((view.evaluations,view.readbacks)==baseline,'orbit recomputed graph or read pixels')
            require(gl.glGetError()==gl.GL_NO_ERROR,'orbit GL error')
            samples.sort()
            benchmark.update(renderer=view.renderer_name,frames=180,median_ms=statistics.median(samples),p95_ms=samples[int(.95*(len(samples)-1))],max_ms=max(samples),orbit_node_evaluations=0,orbit_readbacks=0,viewport=[view.width(),view.height()],method='Native OpenGL draw + glFinish, excludes event loop/vsync and compositor')
        check('180 orbit frames have zero node recomputes / readbacks',rotation)
        view.yaw,view.pitch=.4,.12
        view.draw_material()
        view.doneCurrent()
        window.graph_view.fit_graph()
        window.filter_library()
        window.grab().save(str(ROOT/'preview-qt.png'))
    except Exception as exc:
        rows.append(dict(name='initialization',passed=False,error=str(exc)))
    result=dict(checks=rows,passed=sum(r['passed'] for r in rows),total=len(rows),benchmark=benchmark)
    (ROOT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    app.exit(0 if all(r['passed'] for r in rows) else 1)
