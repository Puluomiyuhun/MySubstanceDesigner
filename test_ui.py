"""In-process Qt UI regression checks; no external application automation."""
import sys,json
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication,QSlider,QComboBox
from PySide6.QtTest import QTest
from main import MainWindow,STYLE
from designer_ui import Section
from model import ROOT,empty,make_node,preset

def run():
 QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
 fmt=QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile);fmt.setDepthBufferSize(24);QSurfaceFormat.setDefaultFormat(fmt)
 app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE);w=MainWindow(restore=False);w.show();rows=[]
 def check(name,fn):
  try:fn();rows.append({'name':name,'passed':True})
  except Exception as e:rows.append({'name':name,'passed':False,'error':repr(e)})
 def require(ok):
  if not ok:raise AssertionError('condition failed')
 def tests():
  def connect():
   g=empty();g['nodes']=[make_node(1,'uniform',0,0),make_node(2,'invert',240,0)];w.model.replace(g);w.refresh();w.graph_view.fit_graph();QTest.qWait(80)
   view=w.graph_view;scene=w.graph_scene;source=view.mapFromScene(scene.nodes[1].output.scenePos());target=view.mapFromScene(scene.nodes[2].inputs[0].scenePos())
   QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=source);QTest.mouseMove(view.viewport(),target,30);QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=target)
   require(w.model.node(2)['inputs']==[1])
   QTest.mouseClick(view.viewport(),Qt.MouseButton.RightButton,pos=target);require(w.model.node(2)['inputs']==[None]);w.undo();require(w.model.node(2)['inputs']==[1])
  check('Resized ports: drag connect, right-click disconnect, undo',connect)
  def params():
   w.model.replace(preset());w.selected=3;w.refresh();QTest.qWait(80)
   slider=w.inspector.findChild(QSlider);require(slider is not None);slider.setValue(73);require(abs(w.model.node(3)['p'][0]-.73)<.001)
   sections=w.inspector.findChildren(Section);section=next(s for s in sections if s.toggle.text()=='特定参数');QTest.mouseClick(section.toggle,Qt.MouseButton.LeftButton);require(section.body.isHidden());QTest.mouseClick(section.toggle,Qt.MouseButton.LeftButton);require(not section.body.isHidden())
   sizes=sections[0].body.findChild(QComboBox);sizes.setCurrentText('256');require(w.resolution.currentText()=='256');w.resolution.setCurrentText('512');require(sizes.currentText()=='512')
  check('Property slider, collapsible group and resolution synchronization',params)
  def layout():
   w.docks['library'].show();w.reset_layout();QTest.qWait(150);require(w.docks['library'].isHidden());require(.25<w.graph_view.height()/w.height()<.55)
   w.material.yaw=2;w.material.zoom=1.5;w.reset_camera();require(w.material.yaw==.4 and w.material.zoom==1.)
  check('Default dock proportions, hidden library and camera reset',layout)
  def library():
   w.search.setText('Blend');require(w.library.count()==1);require(w.library.item(0).data(Qt.ItemDataRole.UserRole)=='blend');w.search.clear()
  check('Node library search remains available',library)
  w.model.replace(preset());w.selected=3;w.viewed=3;w.refresh();w.mesh.setCurrentIndex(1);w.graph_view.fit_graph();QTest.qWait(200)
  w.grab().save(str(ROOT/'preview-qt.png'))
  (ROOT/'ui-verification.json').write_text(json.dumps({'checks':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows)},indent=2),encoding='utf-8')
  print(json.dumps(rows),flush=True);w.close();app.exit(0 if all(r['passed'] for r in rows) else 1)
 QTimer.singleShot(900,tests);return app.exec()
if __name__=='__main__':sys.exit(run())
