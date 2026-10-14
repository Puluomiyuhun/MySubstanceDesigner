"""Read-only SBS graph navigation, separate from the toy GPU evaluator."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QPainter, QAction
from PySide6.QtWidgets import (QMainWindow, QGraphicsScene, QGraphicsRectItem,
    QGraphicsItem, QDockWidget, QPlainTextEdit, QTreeWidget, QTreeWidgetItem,
    QComboBox, QLineEdit, QMessageBox)
from navigation import NavigationView
from sbs_import import SBSProject


class Node(QGraphicsRectItem):
    def __init__(self, browser, data, title):
        self.data=data; self.browser=browser
        self.inputs=browser.input_names(data) if hasattr(browser,'input_names') else list(dict.fromkeys(c['input'] for c in data['connections']))
        self.outputs=[o['uid'] for o in data['outputs']]
        self.height=max(94,32+16*max(len(self.inputs),len(self.outputs)))
        super().__init__(0,0,104,self.height)
        self.setPos(*data['position'][:2]);self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip(title+'\nUID '+data['uid']+'\n双击包装节点查看内部结构')
        self.title=title
    def port(self,key,output=False):
        ports=self.outputs if output else self.inputs
        index=ports.index(key) if key in ports else 0
        return self.pos()+QPointF(104 if output else 0,32+16*index)
    def paint(self,p,option,widget=None):
        p.setPen(QPen(QColor('#eeeeee' if self.isSelected() else '#1d1d1d'),2))
        p.setBrush(QColor('#303030'));p.drawRect(self.rect())
        colors={'compFilter':'#68775d','compInstance':'#686f87','compOutputBridge':'#8b7050'}
        p.fillRect(2,2,100,19,QColor(colors.get(self.data['kind'],'#666666')))
        p.setPen(QColor('#eeeeee'));font=p.font();font.setPixelSize(10);p.setFont(font)
        p.drawText(5,15,p.fontMetrics().elidedText(self.title,Qt.TextElideMode.ElideRight,94))
        for output,ports in [(False,self.inputs),(True,self.outputs)]:
            for i,key in enumerate(ports):
                p.setPen(QPen(QColor('#191919'),2));p.setBrush(QColor('#aaaaaa'))
                p.drawEllipse(QPointF(104 if output else 0,32+16*i),4,4)
        preview=getattr(self,'preview_image',None)
        if preview is not None:p.drawImage(QRectF(12,25,80,44),preview)
        p.setPen(QColor('#999999'))
        label={'compFilter':'底层节点','compInstance':'包装节点','compOutputBridge':'输出','compInputBridge':'输入'}.get(self.data['kind'],'未知节点')
        p.drawText(10,self.height-20,label);p.drawText(10,self.height-6,('已计算 · ' if preview is not None else '未计算 · ')+self.data['uid'])
    def mouseDoubleClickEvent(self,event):
        self.browser.drill(self.data);event.accept()
    def mousePressEvent(self,event):
        if hasattr(self.browser,'port_click'):
            for output,ports in [(False,self.inputs),(True,self.outputs)]:
                for i,key in enumerate(ports):
                    if (event.pos()-QPointF(104 if output else 0,32+16*i)).manhattanLength()<11:
                        self.browser.port_click(self.data['uid'],key,output,event.button());event.accept();return
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if hasattr(self.browser,'positions_changed'):self.browser.positions_changed()
    def itemChange(self,change,value):
        if change==QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and hasattr(self.browser,'node_moved'):self.browser.node_moved(self.data['uid'])
        return super().itemChange(change,value)


class SBSBrowser(QMainWindow):
    def __init__(self,path,parent=None,project=None):
        super().__init__(parent,Qt.WindowType.Window)
        self.project=project or SBSProject(path);self.history=[];self.items={};self.edges=[]
        self.resize(1500,900);self.setWindowTitle('SBS 结构查看器 — '+Path(path).name)
        self.scene=QGraphicsScene(self);self.scene.setBackgroundBrush(QColor('#3a3a3a'))
        self.view=NavigationView(self.scene);self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(self.view.DragMode.RubberBandDrag);self.setCentralWidget(self.view)
        self.inspector=QPlainTextEdit();self.inspector.setReadOnly(True)
        dock=QDockWidget('节点属性 / 原始 SBS 参数',self);dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock);dock.setMinimumWidth(330)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['节点 / 输出','UID'])
        dock=QDockWidget('资源管理器',self);dock.setWidget(self.tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,dock)
        self.tree.itemClicked.connect(lambda item,col:self.focus_node(item.data(0,Qt.ItemDataRole.UserRole)))
        toolbar=self.addToolBar('SBS 导航')
        toolbar.addAction('返回',self.back);toolbar.addAction('全图',self.fit)
        self.combo=QComboBox();self.combo.addItems(self.project.package(self.project.root)['graphs'])
        toolbar.addWidget(self.combo)
        self.combo.activated.connect(lambda i:self.load(str(self.project.root),self.combo.itemText(i)))
        self.search=QLineEdit();self.search.setPlaceholderText('查找节点名称或 UID，回车定位')
        self.search.returnPressed.connect(self.find_node);toolbar.addWidget(self.search)
        fit=QAction(self);fit.setShortcut('F');fit.triggered.connect(self.fit_selection);self.addAction(fit)
        self.scene.selectionChanged.connect(self.selection_changed)
        self.load(str(self.project.root),self.combo.currentText(),False)
    def load(self,path,name,remember=True):
        package=self.project.package(path);graph=package['graphs'][name]
        if remember and hasattr(self,'current'):self.history.append(self.current)
        self.current=(path,name);self.package=package;self.graph=graph
        self.scene.blockSignals(True);self.scene.clear();self.items={};self.edges=[];self.tree.clear()
        names={o['uid']:o['name'] for o in graph['outputs']}
        for frame in graph['frames']:
            x,y=frame['position'][:2];w,h=frame['size'][:2]
            rect=self.scene.addRect(x,y,w,h,QPen(QColor('#78786b')),QBrush(QColor(70,70,62,65)));rect.setZValue(-3)
            label=self.scene.addText(frame['title']);label.setDefaultTextColor(QColor('#d0cfb0'));label.setPos(x,y);label.setZValue(-2)
        for n in graph['nodes']:
            title=n['filter'] or (n['path'].split('?')[0].split('/')[-1] if n['path'] else names.get(n['output'],n['entry'] or n['kind']))
            item=Node(self,n,title);self.scene.addItem(item);self.items[n['uid']]=item
            row=QTreeWidgetItem([title,n['uid']]);row.setData(0,Qt.ItemDataRole.UserRole,n['uid']);self.tree.addTopLevelItem(row)
        missing=0
        for n in graph['nodes']:
            target=self.items[n['uid']]
            for c in n['connections']:
                source=self.items.get(c['source'])
                if source is None:missing+=1;continue
                a=source.port(c['source_output'],True);b=target.port(c['input'])
                curve=QPainterPath(a);d=max(45,abs(b.x()-a.x())*.45)
                curve.cubicTo(a+QPointF(d,0),b-QPointF(d,0),b)
                edge=self.scene.addPath(curve,QPen(QColor('#d4d4d4'),1.5));edge.setZValue(-1)
                edge.setToolTip(f"{c['source']}:{c['source_output']} → {n['uid']}:{c['input']}");edge.setData(0,(n['uid'],c));self.edges.append(edge)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-150,-150,150,150))
        self.scene.blockSignals(False);self.fit()
        self.inspector.setPlainText('结构查看 / 尚未计算材质\n\n'+path+'\n'+name+'\n\n双击包装节点进入内部图；选择节点查看原始参数和端口。\n\n图输出：\n'+json.dumps(graph['outputs'],ensure_ascii=False,indent=2))
        self.statusBar().showMessage(f'{name} | {len(self.items)} 节点 · {len(self.edges)} 连线 · {missing} 缺失来源 | 只读结构，未进行材质求值')
    def fit(self):self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-40,-40,40,40),Qt.AspectRatioMode.KeepAspectRatio)
    def fit_selection(self):
        selected=self.scene.selectedItems()
        if selected:self.focus_node(selected[0].data['uid'])
        else:self.fit()
    def focus_node(self,uid):
        item=self.items.get(uid)
        if item:
            self.scene.clearSelection();item.setSelected(True);self.view.resetTransform();self.view.centerOn(item)
    def find_node(self):
        query=self.search.text().casefold().strip()
        if not query:return
        matches=[i for i in self.items.values() if query in (i.title+' '+i.data['uid']).casefold()]
        if matches:
            selected=next((j for j,i in enumerate(matches) if i.isSelected()),-1)
            self.focus_node(matches[(selected+1)%len(matches)].data['uid'])
    def selection_changed(self):
        selected=self.scene.selectedItems()
        if not selected:return
        n=selected[0].data;info={k:v for k,v in n.items() if k!='xml'}
        if n['kind']=='compInstance':
            r=self.project.instance(self.package,n);info['dependency_resolution']=r
            if r['status']=='resolved':
                g=self.project.package(r['path'])['graphs'][r['graph']]
                info['declared_inputs']=g['inputs'];info['declared_outputs']=g['outputs'];info['base_parameters']=g['base_parameters']
        self.inspector.setPlainText(json.dumps(info,ensure_ascii=False,indent=2)+'\n\n原始节点 XML（未执行）\n'+n['xml'])
    def drill(self,n):
        if n['kind']!='compInstance':return
        r=self.project.instance(self.package,n)
        if r['status']=='resolved':self.load(r['path'],r['graph'])
        else:QMessageBox.information(self,'无法展开此节点',('这是编译后的 SBSAR，目前只保留实例和端口，尚不能展开内部图。' if r['status']=='compiled' else r.get('reason',r['status']))+'\n'+r.get('path',n['path']))
    def back(self):
        if self.history:self.load(*self.history.pop(),remember=False)


if __name__=='__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    from designer_ui import STYLE
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    browser=SBSBrowser(sys.argv[1]);browser.show();sys.exit(app.exec())
