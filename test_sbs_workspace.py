"""Integration tests: package tree, main-window docking and active-document actions."""
import sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtCore import Qt,QEventLoop,QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtTest import QTest
from main import MainWindow,STYLE
from sbs_edit import load_project
from sbs_compute import read

def run(path,out):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    fmt=QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile);QSurfaceFormat.setDefaultFormat(fmt)
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    w=MainWindow(restore=False);w.show();QTest.qWait(300);results=[];out=Path(out)
    def check(name,fn):
        try:fn();results.append({'name':name,'passed':True})
        except Exception as exc:
            import traceback
            traceback.print_exc();results.append({'name':name,'passed':False,'error':repr(exc)})
    def require(x):assert x
    def open_file():
        with patch.object(QFileDialog,'getOpenFileName',return_value=(path,'')):w.open_project()
        QTest.qWait(80)
        require(w.sbs_workspace.active is not None)
        require([x for x in app.topLevelWidgets() if x.isVisible()]==[w])
        require(w.explorer.topLevelItemCount()==2)
        e=w.sbs_workspace.active
        require(e.view.window() is w and e.table.window() is w and e.preview.window() is w)
        require(e.view.isVisible() and e.table.isVisible() and e.preview.isVisible())
    check('File/Open mounts SBS in the existing main window; only one visible top-level window',open_file)
    e=w.sbs_workspace.active
    def click_graph(name):
        parent=w.explorer.topLevelItem(1);row=next(parent.child(i) for i in range(parent.childCount()) if parent.child(i).text(0)==name)
        w.explorer.scrollToItem(row);QTest.mouseClick(w.explorer.viewport(),Qt.MouseButton.LeftButton,pos=w.explorer.visualItemRect(row).center());QTest.qWait(30)
    def switch():
        click_graph('Hay');require(e.graph['name']=='Hay' and len(e.items)==36)
        click_graph('Substance_graph');require(len(e.items)==328)
        click_graph('MA017_02_BruntGround');require(len(e.items)==329)
    check('Actual package-tree clicks switch all three imported graphs in place',switch)
    def edit_undo():
        uid='1359211407';e.focus_node(uid)
        row=next(r for r in range(e.table.rowCount()) if e.table.item(r,0).text()=='outputcolor')
        e.table.item(row,2).setText('0.42 0.42 0.42 1');e.timer.stop()
        e.view.setFocus();QTest.keyClick(e.view,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);QTest.qWait(30)
        n=e.items[uid].data;require(not any(p['name']=='outputcolor' for p in n['parameters']))
        w.redo();n=e.items[uid].data;require(abs(float(read(n,'outputcolor',None)[0])-.42)<1e-6)
    check('Main-window Ctrl+Z and Redo target SBS edits, with no shortcut ambiguity',edit_undo)
    def save():
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'MA017-edited.mlsbs')
            with patch.object(QFileDialog,'getSaveFileName',return_value=(target,'')):w.save_project()
            require(Path(target).is_file() and not e.edits.dirty)
            require(w.explorer.topLevelItem(1).text(0)=='MA017-edited.mlsbs')
            p=load_project(target);g=p.package(p.root)['graphs']['MA017_02_BruntGround'];n=next(n for n in g['nodes'] if n['uid']=='1359211407')
            require(abs(float(read(n,'outputcolor',None)[0])-.42)<1e-6)
    check('Main File/Save writes the active SBS document and updates its package label',save)
    def toy_and_back():
        row=w.explorer.topLevelItem(0).child(0)
        QTest.mouseClick(w.explorer.viewport(),Qt.MouseButton.LeftButton,pos=w.explorer.visualItemRect(row).center())
        require(w.sbs_workspace.active is None and w.graph_view.isVisible() and w.material.isVisible())
        w.refresh();require(w.explorer.topLevelItemCount()==2)
        click_graph('Hay');require(w.sbs_workspace.active is e and e.view.isVisible() and not w.material.isVisible())
        require(w.sbs_workspace.open(path) is e and len(w.sbs_workspace.documents)==1)
    check('Switching to the JSON graph and back retains SBS documents; reopen avoids duplicates',toy_and_back)
    def preview():
        n=next(n for n in e.graph['nodes'] if n['filter']=='transformation');e.focus_node(n['uid']);e.compute()
        loop=QEventLoop();poll=QTimer();poll.timeout.connect(lambda:loop.quit() if not e.busy else None);poll.start(30)
        timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(15000);loop.exec();poll.stop();timeout.stop()
        require(not e.busy and e.preview.pixmap() is not None and not e.preview.pixmap().isNull())
        require(e.preview.window() is w and e.preview.isVisible())
        w.grab().save(str(out/'sbs-main-window.png'))
    check('Hay computes into the main 2D dock beside editable properties',preview)
    def cancel_close():
        e.edits.dirty=True
        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):w.close()
        require(w.isVisible());e.edits.dirty=False
    check('Closing the main window protects unsaved SBS edits; Cancel keeps the workspace open',cancel_close)
    w.close()
    (out/'sbs-workspace-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    for r in results:print(r)
    return all(r['passed'] for r in results)

if __name__=='__main__':sys.exit(0 if run(sys.argv[1],sys.argv[2]) else 1)
