"""Behavior regression tests through Qt events in our own application."""
import sys,json,copy
from PySide6.QtCore import Qt,QTimer,QPoint,QPointF,QEvent
from PySide6.QtGui import QSurfaceFormat,QMouseEvent,QWheelEvent
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtTest import QTest
from main import MainWindow,STYLE
from graphview import WireItem,NodeItem
from model import ROOT,preset
L,R,M=Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton,Qt.MouseButton.MiddleButton
ALT,CTRL,SHIFT=Qt.KeyboardModifier.AltModifier,Qt.KeyboardModifier.ControlModifier,Qt.KeyboardModifier.ShiftModifier
NONE=Qt.KeyboardModifier.NoModifier

def run():
 QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
 fmt=QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile);QSurfaceFormat.setDefaultFormat(fmt)
 app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE);w=MainWindow(restore=False);w.show();rows=[]
 def require(ok,msg='condition failed'):
  if not ok:raise AssertionError(msg)
 def check(name,fn):
  try:fn();rows.append(dict(name=name,passed=True))
  except Exception as e:rows.append(dict(name=name,passed=False,error=repr(e)))
 def reset():
  w.model.replace(preset());w.selected=3;w.viewed=3;w.refresh();w.graph_view.fit_graph();QTest.qWait(80)
 def drag(widget,a,b,button=L,mods=NONE):
  QTest.mousePress(widget,button,mods,a)
  # Explicit button/modifier state keeps the synthetic drag identical across Qt versions.
  ev=QMouseEvent(QEvent.Type.MouseMove,QPointF(b),QPointF(widget.mapToGlobal(b)),Qt.MouseButton.NoButton,button,mods)
  QApplication.sendEvent(widget,ev);QTest.mouseRelease(widget,button,mods,b)
 def port(node,index=None):
  item=w.graph_scene.nodes[node];return w.graph_view.mapFromScene(item.output.scenePos() if index is None else item.inputs[index].scenePos())
 def nodepos(node):return w.graph_view.mapFromScene(w.graph_scene.nodes[node].scenePos()+QPointF(50,40))
 def tests():
  def click_links():
   reset();vp=w.graph_view.viewport()
   QTest.mouseClick(vp,L,ALT,port(3,1));require(w.model.node(3)['inputs'][1] is None)
   QTest.mouseClick(vp,L,pos=port(3,1));QTest.mouseClick(vp,L,pos=port(2));require(w.model.node(3)['inputs'][1]==2)
   QTest.mouseClick(vp,L,ALT,port(2));require(all(2 not in n['inputs'] for n in w.model.graph['nodes']))
   w.undo();require(w.model.node(3)['inputs'][1]==2 and w.model.node(6)['inputs'][0]==2)
  check('Bidirectional click links; Alt output disconnect is one undo',click_links)
  def reverse_drag():
   reset();drag(w.graph_view.viewport(),port(3,1),port(1));require(w.model.node(3)['inputs'][1]==1)
   before=copy.deepcopy(w.model.graph);drag(w.graph_view.viewport(),port(3,0),port(3));require(w.model.graph==before,'self-cycle should be rejected atomically')
   QTest.mouseClick(w.graph_view.viewport(),L,pos=port(1));QTest.keyClick(w.graph_view,Qt.Key.Key_Escape);require(w.graph_scene.pending is None)
  check('Input-to-output drag; cycle rejection; Escape cancellation',reverse_drag)
  def wire_delete():
   reset();line=next(x for x in w.graph_scene.wires if x.target==4);point=w.graph_view.mapFromScene(line.path().pointAtPercent(.5))
   QTest.mouseClick(w.graph_view.viewport(),L,pos=point);require(any(isinstance(x,WireItem) for x in w.graph_scene.selectedItems()))
   QTest.keyClick(w.graph_view,Qt.Key.Key_Delete);require(w.model.node(4)['inputs'][0] is None);w.undo();require(w.model.node(4)['inputs'][0]==3)
  check('Wire hit testing, Delete and undo',wire_delete)
  def selection():
   reset();vp=w.graph_view.viewport();QTest.mouseClick(vp,L,pos=nodepos(1));require(w.selected==1 and w.viewed==3)
   QTest.mouseDClick(vp,L,pos=nodepos(2));require(w.viewed==2)
   QTest.mouseClick(vp,L,pos=nodepos(1));QTest.mouseClick(vp,L,CTRL,nodepos(3));require(len([i for i in w.graph_scene.selectedItems() if isinstance(i,NodeItem)])==2)
  check('Single-click properties; double-click independent 2D; Ctrl multiselect',selection)
  def movement():
   reset();vp=w.graph_view.viewport();pos=nodepos(1);drag(vp,pos,pos+QPoint(21,17));n=w.model.node(1);require(n['x']%12==0 and n['y']%12==0);w.undo();require(w.model.node(1)['x']==0)
   pos=nodepos(1);drag(vp,pos,pos+QPoint(17,13),mods=CTRL);n=w.model.node(1);require(n['x']%12!=0 or n['y']%12!=0)
  check('Grid snap, Ctrl free move and undo',movement)
  def navigation():
   reset()
   for view in (w.graph_view,w.texture):
    view.resetTransform();vp=view.viewport();c=vp.rect().center();before=view.mapToScene(c)
    drag(vp,c,c+QPoint(40,20),R,CTRL);after=view.mapToScene(c);require((before-after).manhattanLength()>20)
    old=view.transform().m11();drag(vp,c,c+QPoint(0,30),R,ALT);require(view.transform().m11()>old)
    require(view.nav_mode is None)
    QTest.keyClick(view,Qt.Key.Key_Z);require(abs(view.transform().m11()-1)<.0001)
    wheel=QWheelEvent(QPointF(c),QPointF(vp.mapToGlobal(c)),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,NONE,Qt.ScrollPhase.NoScrollPhase,False)
    point=view.mapToScene(c);QApplication.sendEvent(vp,wheel);require((view.mapToScene(c)-point).manhattanLength()<4,'zoom anchor moved')
  check('Graph and 2D Ctrl-RMB pan, Alt-RMB zoom, Z and cursor-anchored wheel',navigation)
  def preserve_2d():
   reset();w.view_node(3);w.texture.scale(1.7,1.7);w.texture.centerOn(230,170);scale=w.texture.transform().m11();center=w.texture.mapToScene(w.texture.viewport().rect().center())
   w.set_parameter(3,0,.61,True);QTest.qWait(180);require(abs(w.texture.transform().m11()-scale)<.001);require((w.texture.mapToScene(w.texture.viewport().rect().center())-center).manhattanLength()<3)
   old=w.texture.tiled;QTest.keyClick(w.texture,Qt.Key.Key_Space);require(w.texture.tiled!=old)
  check('2D parameter updates preserve framing; Space toggles tiling',preserve_2d)
  def camera():
   reset();view=w.material;baseline=(view.evaluations,view.readbacks);c=view.rect().center()
   old=view.yaw;drag(view,c,c+QPoint(20,10));require(view.yaw!=old)
   drag(view,c,c+QPoint(30,20),M);require(view.camera_pan!=[0.,0.]);pan=view.camera_pan[:]
   drag(view,c,c+QPoint(10,10),R,CTRL);require(view.camera_pan!=pan)
   old=view.zoom;drag(view,c,c+QPoint(0,20),R,ALT);require(view.zoom>old)
   QTest.qWait(80);require((view.evaluations,view.readbacks)==baseline,'camera caused texture recomputation')
   QTest.mouseDClick(view,L,pos=c);require(view.camera_pan==[0.,0.] and view.zoom==1.)
  check('3D orbit, both pan gestures, dolly and reset without recomputation',camera)
  def search():
   reset();before=len(w.model.graph['nodes']);QTest.keyClick(w.graph_view,Qt.Key.Key_Space);popup=w.node_search;require(popup.isVisible())
   popup.search.setText('Invert');require(popup.results.count()==1);QTest.keyClick(popup.search,Qt.Key.Key_Return)
   require(len(w.model.graph['nodes'])==before+1);require(w.model.node(w.selected)['inputs']==[3]);w.undo();require(len(w.model.graph['nodes'])==before)
  check('Space search, Enter insertion and auto-connect as one undo',search)
  def metrics():
   for b in w.findChildren(QToolButton):
    if b.property('dockControl'):require(b.width()>=24 and b.height()>=24,'dock control clipped')
   label=w.docks['properties'].titleBarWidget().label;require(label.font().pixelSize()==12)
   require(w.menuBar().font().pixelSize()==11)
   report={'device_pixel_ratio':w.devicePixelRatioF(),'window_logical_px':[w.width(),w.height()],'menu_font_px':w.menuBar().font().pixelSize(),'dock_title_font_px':label.font().pixelSize(),'dock_controls':[{'w':b.width(),'h':b.height()} for b in w.findChildren(QToolButton) if b.property('dockControl')]}
   (ROOT/'ui-metrics-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  check('Actual Qt font and title-control metrics',metrics)
  reset();w.view_node(3);w.mesh.setCurrentIndex(1);w.tile_button.setChecked(False);w.texture.set_image(w.images.get(3),reset=True);w.graph_view.fit_graph();QTest.qWait(80);w.statusBar().clearMessage();w.grab().save(str(ROOT/'preview-qt.png'))
  result={'checks':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows)};(ROOT/'interaction-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True);w.close();app.exit(0 if all(r['passed'] for r in rows) else 1)
 QTimer.singleShot(900,tests);return app.exec()
if __name__=='__main__':sys.exit(run())
