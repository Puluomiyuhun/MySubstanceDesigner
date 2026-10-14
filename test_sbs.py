"""Structural import and native Qt navigation checks against a supplied SBS."""
import sys,json,hashlib,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from sbs_import import SBSProject
from sbs_browser import SBSBrowser
from designer_ui import STYLE

def run(path,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    before=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    app=QApplication.instance() or QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    w=SBSBrowser(path);w.show();QTest.qWait(150);results=[]
    def check(name,test):
        try:test();results.append({'name':name,'passed':True})
        except Exception as exc:results.append({'name':name,'passed':False,'error':repr(exc)})
    def require(value):assert value
    check('MA017 main graph: 329 nodes, 442 drawn edges, 8 outputs',lambda:require(len(w.items)==329 and len(w.edges)==442 and len(w.graph['outputs'])==8))
    check('Original positions, node UIDs and raw XML retained',lambda:require(all(w.items[n['uid']].pos().x()==n['position'][0] and '<compNode>' in n['xml'] for n in w.graph['nodes'])))
    check('Every explicit connection output UID exists on its source',lambda:require(all(not c['source_output'] or c['source_output'] in w.items[c['source']].outputs for n in w.graph['nodes'] for c in n['connections'])))
    check('Five dynamic parameters preserved',lambda:require(sum(p['dynamic'] for n in w.graph['nodes'] for p in n['parameters'])==5))
    check('Multi-output wrapper port locations are distinct',lambda:require(all(len({i.port(o,True).y() for o in i.outputs})==len(i.outputs) for i in w.items.values())))
    w.grab().save(str(out/'MA017-overview.png'))
    hay=next(n for n in w.graph['nodes'] if n['path'].split('?')[0].endswith('/Hay'))
    def drill():
        w.focus_node(hay['uid']);QTest.qWait(30)
        item=w.items[hay['uid']]
        point=w.view.mapFromScene(item.sceneBoundingRect().center())
        QTest.mouseDClick(w.view.viewport(),Qt.MouseButton.LeftButton,pos=point);QTest.qWait(50)
        require(w.graph['name']=='Hay' and len(w.items)==36 and len(w.edges)==24)
        w.back();require(len(w.items)==329)
    check('Double-click opens Hay subgraph, Back restores main graph',drill)
    def external():
        node=next(n for n in w.graph['nodes'] if 'Wsc_ColorGententor' in n['path'])
        w.drill(node);require(w.current[0]!=str(w.project.root));w.back()
    check('External SBS wrapper graph can be entered',external)
    def search():
        w.search.setText('blend');w.find_node();require(w.scene.selectedItems()[0].title=='blend')
        first=w.scene.selectedItems()[0].data['uid'];w.find_node();require(w.scene.selectedItems()[0].data['uid']!=first)
        require('原始节点 XML' in w.inspector.toPlainText())
    check('Search cycles matching nodes and exposes parameters',search)
    QTest.qWait(40);w.grab().save(str(out/'MA017-browser.png'))
    report=w.project.inspect()
    check('54 packages / 74 unique graphs / 20 bitmap resources found',lambda:require(report['packages']==54 and len(report['graphs'])==74 and len(report['resources'])==20 and all(r['exists'] for r in report['resources'])))
    check('Only four unresolved instances, all explicitly compiled SBSAR',lambda:require(len(report['issues'])==4 and all(r['status']=='compiled' for r in report['issues'])))
    def variants():
        for name,count in [('Hay',36),('Substance_graph',328)]:
            w.load(str(w.project.root),name);require(len(w.items)==count)
    check('All three source graphs open independently',variants)
    def invalid():
        with tempfile.TemporaryDirectory() as folder:
            for raw in ['<not_sbs/>','<!DOCTYPE package><package/>','<package>']:
                file=Path(folder)/'invalid.sbs';file.write_text(raw)
                try:SBSProject(file)
                except Exception:continue
                raise AssertionError('Invalid XML accepted')
    check('Non-SBS, DTD and malformed XML rejected',invalid)
    check('Original source file hash unchanged',lambda:require(before==hashlib.sha256(Path(path).read_bytes()).hexdigest()))
    (out/'sbs-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    for result in results:print(result)
    w.close();return all(r['passed'] for r in results)

if __name__=='__main__':sys.exit(0 if run(sys.argv[1],sys.argv[2]) else 1)
