from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QFont, QPixmap, QPainterPathStroker, QCursor
from PySide6.QtWidgets import (QGraphicsObject,QGraphicsEllipseItem,QGraphicsPathItem,
    QGraphicsScene,QGraphicsView,QGraphicsItem,QMenu)
from model import DEFS,DEFINITIONS
from navigation import NavigationView


class Port(QGraphicsEllipseItem):
    def __init__(self,node,index,output=False):
        super().__init__(-5,-5,10,10,node)
        self.node,self.index,self.output=node,index,output
        self.setPos(104 if output else 0,54 if output else 54+(index-(len(node.data["inputs"])-1)/2)*22)
        self.setPen(QPen(QColor('#202020'),2.5))
        self.setBrush(QColor('#aaaaaa'))
        self.setZValue(3)
        self.setToolTip('Output' if output else DEFS[node.data['type']]['inputs'][index])


class NodeItem(QGraphicsObject):
    def __init__(self,data):
        super().__init__()
        self.data=data
        self.preview=QPixmap()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable|QGraphicsItem.GraphicsItemFlag.ItemIsSelectable|QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(data['x'],data['y'])
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.output=Port(self,0,True)
        self.inputs=[Port(self,i) for i in range(len(data['inputs']))]
        for p,value in zip(self.inputs,data['inputs']):
            if value is not None:
                p.setBrush(QColor('#bbbbbb'))

    def boundingRect(self):
        return QRectF(-7,-2,118,126)

    def paint(self,painter,option,widget=None):
        d=DEFS[self.data['type']]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(QRectF(0,0,104,104),QColor('#272727'))
        colors={'生成器':'#858370','处理':'#788f74','输出':'#858585'}
        color='#858585' if self.data['type']=='blend' else colors[d['category']]
        painter.fillRect(QRectF(2,2,100,19),QColor(color))
        if not self.preview.isNull():
            painter.drawPixmap(QRectF(2,21,100,81),self.preview,self.preview.rect())
        painter.setPen(QPen(QColor('#e5e5e5') if self.isSelected() else QColor('#181818'),3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0,0,104,104))
        painter.setPen(QColor('#eeeeee'))
        painter.setFont(QFont('Microsoft YaHei UI',7))
        painter.drawText(QRectF(3,2,98,18),Qt.AlignmentFlag.AlignCenter,d['zh'])
        painter.setPen(QColor('#c8c8c8'))
        painter.setFont(QFont('Segoe UI',8))
        size=getattr(self,'texture_size',512)
        painter.drawText(QRectF(-12,107,128,17),Qt.AlignmentFlag.AlignCenter,f'{size}×{size} · RGBA8')

    def itemChange(self,change,value):
        if change==QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.scene():
            self.scene().redraw_wires()
        return super().itemChange(change,value)


def curve(a,b):
    p=QPainterPath(a)
    distance=max(65,abs(b.x()-a.x())*.5)
    p.cubicTo(a+QPointF(distance,0),b-QPointF(distance,0),b)
    return p


class WireItem(QGraphicsPathItem):
    def __init__(self,path,target,index):
        super().__init__(path);self.target,self.index=target,index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPen(QPen(QColor('#dedede'),3));self.setZValue(-1)
    def shape(self):
        stroker=QPainterPathStroker();stroker.setWidth(12)
        return stroker.createStroke(self.path())
    def itemChange(self,change,value):
        if change==QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.setPen(QPen(QColor('#ffffff') if value else QColor('#dedede'),5 if value else 3))
        return super().itemChange(change,value)


class GraphScene(QGraphicsScene):
    changed_graph=Signal()
    layout_changed=Signal()
    message=Signal(str)
    preview_requested=Signal(int)

    def __init__(self,model,parent=None):
        super().__init__(parent)
        self.model=model
        self.nodes={}
        self.wires=[]
        self.pending=None
        self.pending_wire=None
        self.rebuilding=False
        self.setSceneRect(-5000,-5000,10000,10000)

    def rebuild(self,selected=None,images=None):
        self.rebuilding=True
        self.nodes={}
        self.wires=[]
        self.pending=self.pending_wire=None
        self.clear()
        for n in self.model.graph['nodes']:
            item=NodeItem(n)
            self.nodes[n['id']]=item
            self.addItem(item)
            item.setSelected(n['id']==selected)
            if images and n['id'] in images:
                item.preview=QPixmap.fromImage(images[n['id']]).scaled(100,100,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        self.redraw_wires()
        self.rebuilding=False

    def redraw_wires(self):
        for line in self.wires:
            self.removeItem(line)
        self.wires=[]
        for n in self.model.graph['nodes']:
            target=self.nodes.get(n['id'])
            if not target:
                continue
            for i,source_id in enumerate(n['inputs']):
                source=self.nodes.get(source_id)
                if source:
                    path=WireItem(curve(source.output.scenePos(),target.inputs[i].scenePos()),n['id'],i)
                    path.setPen(QPen(QColor('#dedede'),3))
                    path.setZValue(-1)
                    self.addItem(path)
                    self.wires.append(path)

    def cancel_link(self):
        if self.pending_wire is not None:self.removeItem(self.pending_wire)
        self.pending=self.pending_wire=None

    def port_at(self,point):
        return next((i for i in self.items(point) if isinstance(i,Port)),None)

    def disconnect_port(self,port):
        edges=[(n,i) for n in self.model.graph['nodes'] for i,v in enumerate(n['inputs'])
               if (port.output and v==port.node.data['id']) or (not port.output and n['id']==port.node.data['id'] and i==port.index and v is not None)]
        if edges:
            self.model.checkpoint()
            for n,i in edges:n['inputs'][i]=None
            self.changed_graph.emit()

    def finish_link(self,target):
        anchor=self.pending
        if target is None or target.output==anchor.output:return False
        source,dest=(anchor,target) if anchor.output else (target,anchor)
        source_id,target_id,index=source.node.data['id'],dest.node.data['id'],dest.index
        self.cancel_link()
        try:
            if self.model.node(target_id)['inputs'][index]!=source_id:
                self.model.connect(source_id,target_id,index);self.changed_graph.emit()
        except ValueError as exc:self.message.emit(str(exc))
        return True

    def mousePressEvent(self,event):
        port=self.port_at(event.scenePos())
        if self.pending and event.button()==Qt.MouseButton.RightButton:
            self.cancel_link();event.accept();return
        if port and event.button()==Qt.MouseButton.LeftButton:
            if event.modifiers()&Qt.KeyboardModifier.AltModifier:
                self.cancel_link();self.disconnect_port(port)
            elif self.pending:
                if not self.finish_link(port):self.cancel_link()
            else:
                self.pending=port;self.link_start=event.scenePos();self.link_dragged=False
                self.pending_wire=QGraphicsPathItem();self.pending_wire.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.pending_wire.setPen(QPen(QColor('#ffffff'),3));self.pending_wire.setZValue(-.5)
                self.addItem(self.pending_wire)
            event.accept();return
        # Preserve the prototype's right-click input disconnect as an extra shortcut.
        if port and not port.output and event.button()==Qt.MouseButton.RightButton:
            self.disconnect_port(port);event.accept();return
        if self.pending:self.cancel_link()
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.pending:
            a,b=self.pending.scenePos(),event.scenePos()
            self.link_dragged=self.link_dragged or (b-self.link_start).manhattanLength()>3
            self.pending_wire.setPath(curve(a,b) if self.pending.output else curve(b,a))
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.pending:
            target=self.port_at(event.scenePos())
            if target and target is not self.pending:self.finish_link(target)
            elif self.link_dragged:self.cancel_link()
            event.accept();return
        super().mouseReleaseEvent(event)
        moved=[i for i in self.nodes.values() if abs(i.x()-i.data['x'])>.01 or abs(i.y()-i.data['y'])>.01]
        if moved:
            self.model.checkpoint()
            for item in moved:
                if not event.modifiers()&Qt.KeyboardModifier.ControlModifier:
                    item.setPos(round(item.x()/12)*12,round(item.y()/12)*12)
                item.data['x'],item.data['y']=item.x(),item.y()
            self.layout_changed.emit()

    def mouseDoubleClickEvent(self,event):
        item=self.itemAt(event.scenePos(),self.views()[0].transform())
        if isinstance(item,Port):item=item.node
        if isinstance(item,NodeItem) and event.button()==Qt.MouseButton.LeftButton:
            self.cancel_link();self.preview_requested.emit(item.data['id']);event.accept();return
        super().mouseDoubleClickEvent(event)


class GraphView(NavigationView):
    add_requested=Signal(str,object)
    delete_requested=Signal()
    search_requested=Signal(object)

    def __init__(self,scene,parent=None):
        super().__init__(scene,parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.zoom_limits=(.15,2.5)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QColor('#3d3d3d'))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.setToolTip('中键 / Ctrl+右键平移 · Alt+右键缩放 · 空格搜索 · 双击节点预览 · Alt+单击端口断线')

    def drawBackground(self,painter,rect):
        painter.fillRect(rect,QColor('#3d3d3d'))
        for step,color in ((12,'#414141'),(120,'#353535')):
            painter.setPen(QPen(QColor(color),0))
            left=int(rect.left())//step*step
            top=int(rect.top())//step*step
            for x in range(left,int(rect.right())+step,step):
                painter.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
            for y in range(top,int(rect.bottom())+step,step):
                painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))

    def fit_graph(self,selection=False):
        items=[i for i in self.scene().selectedItems() if isinstance(i,NodeItem)] if selection else []
        items=items or list(self.scene().nodes.values())
        if not items:
            return
        rect=items[0].sceneBoundingRect()
        for i in items[1:]:
            rect=rect.united(i.sceneBoundingRect())
        self.fitInView(rect.adjusted(-50,-45,50,45),Qt.AspectRatioMode.KeepAspectRatio)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                point=self.viewport().mapFromGlobal(QCursor.pos())
                if not self.viewport().rect().contains(point):point=self.viewport().rect().center()
                self.search_requested.emit(self.mapToScene(point))
        elif event.key()==Qt.Key.Key_Escape:self.scene().cancel_link()
        elif event.key()==Qt.Key.Key_Z and not event.modifiers():self.resetTransform()
        elif event.key()==Qt.Key.Key_F:self.fit_graph(True)
        elif event.key()==Qt.Key.Key_Delete:self.delete_requested.emit()
        else:super().keyPressEvent(event)

    def contextMenuEvent(self,event):
        if self.suppress_context:
            event.accept();return
        item=self.itemAt(event.pos())
        if isinstance(item,Port):
            return
        menu=QMenu(self)
        if isinstance(item,NodeItem):
            menu.addAction('在 2D 视图中查看',lambda:self.scene().preview_requested.emit(item.data['id']))
            menu.addSeparator()
        point=self.mapToScene(event.pos())
        for cat in ('生成器','处理','输出'):
            group=menu.addMenu(cat)
            for d in DEFINITIONS:
                if d['category']==cat:
                    action=group.addAction(d['name']+'  '+d['zh'])
                    action.triggered.connect(lambda checked=False,kind=d['id'],p=point:self.add_requested.emit(kind,p))
        menu.exec(event.globalPos())
