"""Real MA017 editing/save round trips and independent numeric fixtures."""
import sys,copy,json,tempfile,hashlib
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint,QEventLoop,QTimer
from PySide6.QtTest import QTest
from sbs_editor import SBSEditor
from sbs_edit import constant,connect,add_node,save_project,load_project
from sbs_compute import Evaluator,Unsupported,sample
from designer_ui import STYLE

def run(path,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);results=[]
    original=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    app=QApplication.instance() or QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    w=SBSEditor(path);w.show();QTest.qWait(80);key=w.current
    def check(name,fn):
        try:fn();results.append({'name':name,'passed':True})
        except Exception as exc:
            import traceback
            traceback.print_exc();results.append({'name':name,'passed':False,'error':repr(exc)})
    def require(value):assert value
    def evaluate(uid):return Evaluator(w.project,64).evaluate(*w.current,uid)
    metallic=next(n for n in w.graph['nodes'] if n['output']=='1213284342')['uid']
    source=next(n for n in w.graph['nodes'] if n['uid']=='1359211407')
    def parameter_edit():
        w.focus_node(source['uid'])
        row=next(r for r in range(w.table.rowCount()) if w.table.item(r,0).text()=='outputcolor')
        w.table.item(row,2).setText('0.37 0.37 0.37 1')
        np.testing.assert_allclose(evaluate(metallic)[...,:3],.37,atol=1e-7)
        w.undo(False);np.testing.assert_allclose(evaluate(metallic)[...,:3],0)
        w.undo(True);np.testing.assert_allclose(evaluate(metallic)[...,:3],.37,atol=1e-7)
    check('Native property edit changes metallic output; undo/redo restores computed values',parameter_edit)
    def numeric_input():
        n=next(n for n in w.graph['nodes'] if n['kind']=='compInputBridge');w.focus_node(n['uid'])
        row=next(r for r in range(w.table.rowCount()) if w.table.item(r,0).text()=='__input_default__')
        w.table.item(row,2).setText('2.5');require(float(evaluate(n['uid']))==2.5)
        output=next(n for n in w.graph['nodes'] if n['output']=='1491953274');require(float(evaluate(output['uid']))==2.5)
    check('Float1 graph input default editable; heightScale remains scalar above 1',numeric_input)
    def move():
        w.focus_node(source['uid']);item=w.items[source['uid']];before=list(item.data['position'])
        start=w.view.mapFromScene(item.sceneBoundingRect().center());end=start+QPoint(-40,50)
        QTest.mousePress(w.view.viewport(),Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(w.view.viewport(),end,40);QTest.mouseRelease(w.view.viewport(),Qt.MouseButton.LeftButton,pos=end);QTest.qWait(40)
        require(w.items[source['uid']].data['position'][:2]!=before[:2]);w.undo(False);require(w.items[source['uid']].data['position']==before)
    check('Actual mouse drag updates persistent node position; undo restores it',move)
    added=[]
    def nodes_and_wires():
        w.mutate(lambda g:added.extend([add_node(g,'uniform',[0,0]),add_node(g,'levels',[260,0])]))
        a,b=added;constant(a,'outputcolor','constantValueFloat4','0.2 0.2 0.2 1')
        # Work through the same port event handler used by mouse input.
        w.port_click(a['uid'],a['outputs'][0]['uid'],True,Qt.MouseButton.LeftButton)
        w.port_click(b['uid'],'input1',False,Qt.MouseButton.LeftButton)
        np.testing.assert_allclose(evaluate(b['uid'])[...,:3],.2,atol=1e-7)
        w.port_click(b['uid'],'input1',False,Qt.MouseButton.RightButton)
        try:evaluate(b['uid'])
        except Unsupported:pass
        else:raise AssertionError('Disconnected levels silently evaluated')
        w.undo(False);np.testing.assert_allclose(evaluate(b['uid'])[...,:3],.2,atol=1e-7)
        w.focus_node(a['uid']);w.delete();require(a['uid'] not in w.items);require(not next(n for n in w.graph['nodes'] if n['uid']==b['uid'])['connections'])
        w.undo(False);require(a['uid'] in w.items)
    check('Add, connect, disconnect, delete and undo preserve computation and remove dangling links',nodes_and_wires)
    def cycle():
        g={'nodes':[]};a=add_node(g,'passthrough',[0,0]);b=add_node(g,'passthrough',[100,0])
        connect(g,a['uid'],a['outputs'][0]['uid'],b['uid'],'input')
        try:connect(g,b['uid'],b['outputs'][0]['uid'],a['uid'],'input')
        except ValueError:return
        raise AssertionError('cycle accepted')
    check('Cycles rejected before mutation',cycle)
    def hay():
        w.load(str(w.project.root),'Hay');e=Evaluator(w.project,64)
        outputs=[n for n in w.graph['nodes'] if n['kind']=='compOutputBridge']
        require(len(outputs)==12)
        for node in outputs:
            pixels=e.evaluate(*w.current,node['uid']);require(pixels.shape==(64,64,4));require(np.ptp(pixels[...,:3])>0)
        transform=next(n for n in w.graph['nodes'] if n['filter']=='transformation');link=transform['connections'][0]
        np.testing.assert_allclose(e.evaluate(*w.current,transform['uid']),e.evaluate(*w.current,link['source'],link['source_output']),atol=1e-6)
        w.focus_node(outputs[0]['uid']);w.compute()
        loop=QEventLoop();poll=QTimer();poll.timeout.connect(lambda:loop.quit() if not w.busy and not w.timer.isActive() and not w.recompute else None)
        poll.start(30);timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(15000);loop.exec();poll.stop();timeout.stop()
        require(not w.busy and w.preview.pixmap() is not None and not w.preview.pixmap().isNull())
        w.grab().save(str(out/'sbs-editable-hay.png'))
        t=next(n for n in w.graph['nodes'] if n['filter']=='transformation')
        w.mutate(lambda g:constant(next(n for n in g['nodes'] if n['uid']==t['uid']),'offset','constantValueFloat2','0.25 0'),t['uid'])
    check('All 12 real Hay outputs compute; identity transform matches input; async Qt preview renders',hay)
    def save_roundtrip():
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'edited.mlsbs';save_project(w.project,file);p=load_project(file)
            np.testing.assert_allclose(Evaluator(p,64).evaluate(*key,metallic)[...,:3],.37,atol=1e-7)
            require(json.dumps(p.cache,sort_keys=True)==json.dumps(w.project.cache,sort_keys=True))
            reopened=SBSEditor(file);require(len(reopened.items)==331);reopened.close()
    check('Save/reopen .mlsbs retains root edits, child edits, resources and unknown raw node XML',save_roundtrip)
    def math():
        image=np.arange(16,dtype=np.float32).reshape(4,4,1);image=np.repeat(image,4,axis=2)
        v,u=np.mgrid[:4,:4].astype(np.float32);u=(u+.5)/4;v=(v+.5)/4
        np.testing.assert_array_equal(sample(image,u,v),image)
        np.testing.assert_array_equal(sample(image,u+.25,v),np.roll(image,-1,axis=1))
        np.testing.assert_array_equal(sample(image,u+2,v,0),np.zeros_like(image))
        np.testing.assert_allclose(sample(image,u+.125,v),.5*(image+np.roll(image,-1,axis=1)))
    check('Independent sampling fixtures: identity, wrapped shift, no-tiling black, half-pixel bilinear',math)
    def levels():
        original_graph=w.project.package(key[0])['graphs'][key[1]];test=copy.deepcopy(original_graph);test['nodes']=[]
        a=add_node(test,'uniform',[0,0]);b=add_node(test,'levels',[200,0]);connect(test,a['uid'],a['outputs'][0]['uid'],b['uid'],'input1')
        constant(a,'outputcolor','constantValueFloat4','0.3 0.3 0.3 1')
        constant(b,'levelinlow','constantValueFloat4','0.2 0.2 0.2 0');constant(b,'levelinhigh','constantValueFloat4','0.6 0.6 0.6 1')
        constant(b,'leveloutlow','constantValueFloat4','0.1 0.1 0.1 0');constant(b,'levelouthigh','constantValueFloat4','0.9 0.9 0.9 1')
        w.project.package(key[0])['graphs']['fixture']=test
        def ev():return Evaluator(w.project,64).evaluate(key[0],'fixture',b['uid'])
        np.testing.assert_allclose(ev()[...,:3],.3,atol=1e-6)
        constant(b,'levelinmid','constantValueFloat4','0.25 0.25 0.25 0.5')
        np.testing.assert_allclose(ev()[...,:3],.5,atol=1e-6)
        del w.project.package(key[0])['graphs']['fixture']
    check('Independent Levels input/output range and non-neutral midpoint fixture',levels)
    def unsupported():
        w.load(*key);n=next(n for n in w.graph['nodes'] if n['filter']=='hsl');old=n['filter'];n['filter']='unknown_test_filter'
        try:
            try:evaluate(n['uid'])
            except Unsupported as exc:require('unknown_test_filter' in str(exc));return
            raise AssertionError('unsupported operation silently evaluated')
        finally:n['filter']=old
    check('Unsupported nodes report the blocking operation instead of returning placeholders',unsupported)
    check('Original SBS SHA256 unchanged',lambda:require(original==hashlib.sha256(Path(path).read_bytes()).hexdigest()))
    w.timer.stop();w.edits.dirty=False
    while w.busy:QTest.qWait(30)
    w.close()
    (out/'sbs-edit-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    for r in results:print(r)
    return all(r['passed'] for r in results)

if __name__=='__main__':sys.exit(0 if run(sys.argv[1],sys.argv[2]) else 1)
