"""Material Lab Qt: native dockable material authoring prototype."""
import copy
import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QPointF, QSize, QSettings, QByteArray, Signal
from PySide6.QtGui import QAction, QKeySequence, QColor, QPixmap, QPainter, QSurfaceFormat, QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QDockWidget,QVBoxLayout,QHBoxLayout,
    QLabel,QLineEdit,QListWidget,QListWidgetItem,QComboBox,QPushButton,QScrollArea,QFormLayout,
    QSlider,QDoubleSpinBox,QColorDialog,QFileDialog,QMessageBox,QTreeWidget,QTreeWidgetItem,
    QGraphicsView,QGraphicsScene,QToolBar,QFrame,QSizePolicy)
from model import ROOT,DEFINITIONS,DEFS,CHANNELS,GraphModel,validate,preset,empty
from renderer import MaterialView
from navigation import NavigationView
from graphview import GraphScene,GraphView,NodeItem,WireItem

from designer_ui import STYLE, Section, icon, GUI, build_ui, PARAM_ZH, OPTION_ZH, node_icon_path



class TextureView(NavigationView):
    tile_requested=Signal()
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor('#242424'))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.image=None
        self.tiled=False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_image(self,image,reset=False):
        old_size=self.image.size() if self.image is not None else None
        center=self.mapToScene(self.viewport().rect().center())
        self.image=image;self.scene().clear()
        if image is not None and not image.isNull():
            pix=QPixmap.fromImage(image);count=3 if self.tiled else 1
            for x in range(count):
                for y in range(count):
                    item=self.scene().addPixmap(pix);item.setPos(x*pix.width(),y*pix.height())
            self.scene().setSceneRect(-20000,-20000,40000,40000)
            if reset or old_size!=image.size():self.fit_texture()
            else:self.centerOn(center)

    def fit_texture(self):
        if self.scene().items():self.fitInView(self.scene().itemsBoundingRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_F:self.fit_texture()
        elif event.key()==Qt.Key.Key_Z:self.resetTransform()
        elif event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():self.tile_requested.emit()
        else:super().keyPressEvent(event)

    def contextMenuEvent(self,event):
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self,restore=True):
        super().__init__()
        self.setWindowTitle('Material Lab Qt 0.12 — 节点材质实验室[*]')
        self.setObjectName('MaterialLabMainWindow')
        self.resize(1800,1000)
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.Corner.BottomLeftCorner,Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner,Qt.DockWidgetArea.RightDockWidgetArea)
        self.model=GraphModel()
        self.selected=self.model.graph['nodes'][-1]['id']
        self.current_file=None
        self.images={}
        self.settings=QSettings(str(ROOT/'user-data/layout-v03.ini'),QSettings.Format.IniFormat)
        self.autosave=ROOT/'user-data/autosave.json'
        self.save_enabled=restore
        self.slider_active=False
        self.docks={}
        if restore and self.autosave.exists():
            try:
                self.model.replace(validate(json.loads(self.autosave.read_text(encoding='utf-8-sig'))),False)
                self.selected=self.model.graph['nodes'][-1]['id'] if self.model.graph['nodes'] else None
            except Exception:
                pass
        self.compute_timer=QTimer(self)
        self.compute_timer.setSingleShot(True)
        self.compute_timer.setInterval(35)
        self.compute_timer.timeout.connect(self.compute)
        self.save_timer=QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(600)
        self.save_timer.timeout.connect(self.save_autosave)
        self.viewed=self.selected
        self.build_ui()
        from sbs_workspace import SBSWorkspace
        self.sbs_workspace=SBSWorkspace(self)
        self.refresh()
        QTimer.singleShot(250,self.graph_view.fit_graph)
        if restore:
            geometry=self.settings.value('geometry')
            state=self.settings.value('dockState')
            if geometry:
                self.restoreGeometry(geometry)
            if state:
                self.restoreState(state)
            else:
                QTimer.singleShot(100,self.apply_default_layout)
        else:
            QTimer.singleShot(100,self.apply_default_layout)

    def dock(self,name,title,widget,area):
        dock=QDockWidget(title,self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area,dock)
        self.docks[name]=dock
        return dock

    def action(self,menu,label,callback,shortcut=None):
        action=QAction(label,self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        menu.addAction(action)
        return action

    build_ui=build_ui

    def reset_camera(self):
        self.material.reset_camera()

    def message(self,text):
        self.statusBar().showMessage(str(text),6500)

    def frame_info(self,text):
        self.gpu_text.setText(text)

    def set_mesh(self,index):
        self.material.shape=index
        self.material.update()

    def set_tiled(self,value):
        self.texture.tiled=value
        self.texture.set_image(self.images.get(self.viewed),reset=True)

    def filter_library(self,*args):
        self.library.clear()
        term=self.search.text().lower()
        cat=self.category.currentText()
        for d in DEFINITIONS:
            if (cat=='全部' or cat==d['category']) and term in (d['name']+' '+d['zh']).lower():
                item=QListWidgetItem(d['name']+'\n'+d['zh'])
                icon=node_icon_path(d['id'])
                if icon.exists():
                    item.setIcon(QIcon(str(icon)))
                item.setData(Qt.ItemDataRole.UserRole,d['id'])
                item.setToolTip('双击添加 '+d['name'])
                self.library.addItem(item)

    def refresh(self):
        if self.model.node(self.selected) is None:
            self.selected=self.model.graph['nodes'][-1]['id'] if self.model.graph['nodes'] else None
        if self.model.node(self.viewed) is None:self.viewed=self.selected
        self.graph_scene.rebuild(self.selected,self.images)
        self.explorer.clear()
        package=QTreeWidgetItem(['Untitled Package' if self.current_file is None else Path(self.current_file).name])
        package.setIcon(0,icon(GUI+'package.svg'))
        graph=QTreeWidgetItem(['Material Graph'])
        graph.setIcon(0,icon(GUI+'graph.svg'))
        package.addChild(graph)
        for k,value in self.model.graph['bindings'].items():
            if value is not None:
                graph.addChild(QTreeWidgetItem([k+' → #'+str(value)]))
        self.explorer.addTopLevelItem(package)
        self.explorer.expandAll()
        graph.setSelected(True)
        self.sbs_workspace.rebuild_tree()
        self.build_properties()
        self.schedule()

    def selection_changed(self):
        if self.graph_scene.rebuilding:
            return
        nodes=[i for i in self.graph_scene.selectedItems() if isinstance(i,NodeItem)]
        self.selected=nodes[0].data['id'] if nodes else None
        self.build_properties()


    def build_properties(self):
        container=QWidget()
        layout=QVBoxLayout(container)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        outer=layout
        node=self.model.node(self.selected)

        if node:
            d=DEFS[node['type']]
            self.docks['properties'].setWindowTitle(d['zh']+' - 属性')

            base=Section('基本参数');outer.addWidget(base)
            base.content.addWidget(QLabel('输出大小'))
            sizes=QComboBox();sizes.addItems(['256','512','1024']);sizes.setCurrentText(self.resolution.currentText())
            sizes.currentTextChanged.connect(self.resolution.setCurrentText)
            self.resolution.currentTextChanged.connect(sizes.setCurrentText)
            base.content.addWidget(sizes)
            base.content.addWidget(QLabel('输出格式'))
            fmt=QComboBox();fmt.addItem('每个通道 8 位 · RGBA');fmt.setEnabled(False);base.content.addWidget(fmt)
            section=Section('特定参数');outer.addWidget(section);layout=section.content
            for index,p in enumerate(d['params']):
                label=QLabel(PARAM_ZH.get(p['name'],p['name']))
                layout.addWidget(label)
                if 'options' in p:
                    combo=QComboBox()
                    combo.addItems([OPTION_ZH.get(o,o) for o in p['options']])
                    combo.setCurrentIndex(int(node['p'][index]))
                    combo.currentIndexChanged.connect(lambda value,ni=node['id'],i=index:self.set_parameter(ni,i,value,True))
                    layout.addWidget(combo)
                elif p.get('color'):
                    button=QPushButton(node['p'][index])
                    button.setStyleSheet('background:'+node['p'][index]+';color:white;')
                    button.clicked.connect(lambda checked=False,ni=node['id'],i=index:self.choose_color(ni,i))
                    layout.addWidget(button)
                else:
                    row=QHBoxLayout()
                    step=p['step']
                    steps=int(round((p['max']-p['min'])/step))
                    slider=QSlider(Qt.Orientation.Horizontal)
                    slider.setRange(0,steps)
                    slider.setValue(int(round((node['p'][index]-p['min'])/step)))
                    slider.setAccessibleName(p['name'])
                    spin=QDoubleSpinBox()
                    spin.setRange(p['min'],p['max'])
                    spin.setDecimals(0 if step>=1 else 3 if step<.01 else 2)
                    spin.setSingleStep(step)
                    spin.setValue(node['p'][index])
                    spin.setFixedWidth(78)
                    slider.sliderPressed.connect(self.begin_slider)
                    slider.sliderReleased.connect(self.end_slider)
                    slider.valueChanged.connect(lambda v,ni=node['id'],i=index,lo=p['min'],step=step,sp=spin:self.slider_value(ni,i,lo+v*step,sp))
                    spin.editingFinished.connect(lambda ni=node['id'],i=index,sp=spin,sl=slider,lo=p['min'],step=step:self.spin_value(ni,i,sp,sl,lo,step))
                    row.addWidget(slider,1)
                    row.addWidget(spin)
                    layout.addLayout(row)
            if not d['params']:
                tip=QLabel('此节点没有可调参数。')
                tip.setObjectName('subtle')
                layout.addWidget(tip)
        else:
            layout.addWidget(QLabel('选择节点查看属性'))
        outputs=Section('材质输出',False);outer.addWidget(outputs);layout=outputs.content
        for k,title in zip(CHANNELS,('基础颜色','高度','粗糙度','法线')):
            layout.addWidget(QLabel(title))
            combo=QComboBox()
            combo.addItem('未绑定',None)
            for n in self.model.graph['nodes']:
                combo.addItem('#'+str(n['id'])+' '+DEFS[n['type']]['name'],n['id'])
            combo.setCurrentIndex(max(0,combo.findData(self.model.graph['bindings'][k])))
            combo.currentIndexChanged.connect(lambda i,key=k,c=combo:self.set_binding(key,c.currentData()))
            layout.addWidget(combo)
        outer.addStretch()
        old=self.inspector.takeWidget()
        self.inspector.setWidget(container)
        if old:
            old.deleteLater()

    def begin_slider(self):
        self.model.checkpoint()
        self.slider_active=True

    def end_slider(self):
        self.slider_active=False

    def slider_value(self,node_id,index,value,spin):
        value=round(value,5)
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
        self.set_parameter(node_id,index,value,not self.slider_active)

    def spin_value(self,node_id,index,spin,slider,low,step):
        value=spin.value()
        self.set_parameter(node_id,index,value,True)
        slider.blockSignals(True)
        slider.setValue(int(round((value-low)/step)))
        slider.blockSignals(False)

    def set_parameter(self,node_id,index,value,remember):
        node=self.model.node(node_id)
        if node is None or node['p'][index]==value:
            return
        if remember:
            self.model.checkpoint()
        node['p'][index]=value
        self.schedule()

    def choose_color(self,node_id,index):
        node=self.model.node(node_id)
        color=QColorDialog.getColor(QColor(node['p'][index]),self,'选择颜色')
        if color.isValid():
            self.set_parameter(node_id,index,color.name(),True)
            self.build_properties()

    def set_binding(self,key,node_id):
        self.model.checkpoint()
        self.model.graph['bindings'][key]=node_id
        self.schedule()

    def schedule(self,*args):
        self.compute_timer.start()
        self.queue_save()

    def queue_save(self):
        self.save_timer.start()

    def compute(self):
        self.material.set_graph(copy.deepcopy(self.model.graph),int(self.resolution.currentText()))

    def images_updated(self,images):
        self.images=images
        for node_id,item in self.graph_scene.nodes.items():
            if node_id in images:
                item.preview=QPixmap.fromImage(images[node_id]).scaled(100,100,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
                item.texture_size=images[node_id].width()
                item.update()
        self.update_texture(images)
        graph=self.model.graph
        connections=sum(i is not None for n in graph['nodes'] for i in n['inputs'])
        self.status_text.setText(f'{len(graph["nodes"])} 节点 · {connections} 连接 · {self.resolution.currentText()}² · '+self.material.renderer_name)

    def view_node(self,node_id):
        if self.model.node(node_id):
            self.viewed=node_id
            self.update_texture(self.images,reset=True)

    def update_texture(self,images,reset=False):
        node=self.model.node(self.viewed)
        title=DEFS[node['type']]['zh'] if node else '未选择输出'
        self.texture_name.setText('  '+title)
        if not self.sbs_workspace.active:self.docks['view2d'].setWindowTitle(title+' - 2D视图')
        self.texture.set_image(images.get(self.viewed),reset=reset)

    def add_node(self,kind,point=None):
        if self.sbs_workspace.active:return self.sbs_workspace.active.add()
        if point is None:
            point=self.graph_view.mapToScene(self.graph_view.viewport().rect().center())
        try:
            source=self.selected if len([i for i in self.graph_scene.selectedItems() if isinstance(i,NodeItem)])==1 else None
            self.selected=self.model.add(kind,point.x()-52,point.y()-52)
            node=self.model.node(self.selected)
            if node['inputs'] and self.model.node(source):node['inputs'][0]=source
            self.refresh()
        except ValueError as exc:
            self.message(str(exc))

    def delete_nodes(self):
        if self.sbs_workspace.active:return self.sbs_workspace.active.delete()
        items=self.graph_scene.selectedItems()
        ids={i.data['id'] for i in items if isinstance(i,NodeItem)}
        edges={(i.target,i.index) for i in items if isinstance(i,WireItem)}
        if not ids and not edges:return
        if ids:self.model.remove(ids)
        else:self.model.checkpoint()
        for target,index in edges:
            node=self.model.node(target)
            if node:node['inputs'][index]=None
        self.selected=None;self.refresh()

    def duplicate(self):
        if self.sbs_workspace.active:
            self.message('SBS 节点复制尚未实现；可使用图形工具栏添加节点');return
        originals=[copy.deepcopy(item.data) for item in self.graph_scene.selectedItems() if isinstance(item,NodeItem)]
        if not originals:
            return
        if len(self.model.graph['nodes'])+len(originals)>100:
            self.message('最多支持 100 个节点')
            return
        self.model.checkpoint()
        next_id=max(n['id'] for n in self.model.graph['nodes'])+1
        mapping={n['id']:next_id+i for i,n in enumerate(originals)}
        for node in originals:
            node['id']=mapping[node['id']]
            node['x']+=45
            node['y']+=60
            node['inputs']=[mapping.get(i,i) for i in node['inputs']]
            self.model.graph['nodes'].append(node)
        self.selected=originals[-1]['id']
        self.refresh()

    def undo(self):
        if self.sbs_workspace.active:return self.sbs_workspace.active.undo(False)
        if self.model.undo():
            self.refresh()

    def redo(self):
        if self.sbs_workspace.active:return self.sbs_workspace.active.undo(True)
        if self.model.redo():
            self.refresh()

    def load_preset(self):
        self.sbs_workspace.activate()
        self.model.replace(preset(self.preset_combo.currentData()))
        self.current_file=None
        self.selected=self.model.graph['nodes'][-1]['id']
        self.refresh()
        self.graph_view.fit_graph()

    def new_project(self):
        self.sbs_workspace.activate()
        self.model.replace(empty())
        self.current_file=None
        self.selected=None
        self.refresh()

    def open_project(self):
        filename,_=QFileDialog.getOpenFileName(self,'打开工程',str(ROOT),'支持的工程 (*.json *.sbs *.mlsbs);;SBS 可编辑工程 (*.sbs *.mlsbs);;Material Lab (*.json)')
        if not filename:
            return
        try:
            if Path(filename).suffix.lower() in ('.sbs','.mlsbs'):
                self.sbs_workspace.open(filename)
                return
            if Path(filename).stat().st_size>2_000_000:
                raise ValueError('文件超过 2 MB')
            graph=validate(json.loads(Path(filename).read_text(encoding='utf-8-sig')))
            self.sbs_workspace.activate()
            self.model.replace(graph)
            self.current_file=filename
            self.selected=graph['nodes'][-1]['id'] if graph['nodes'] else None
            self.refresh()
            self.graph_view.fit_graph()
        except Exception as exc:
            QMessageBox.warning(self,'无法打开',str(exc))

    def save_project(self,save_as=False):
        if self.sbs_workspace.active:return self.sbs_workspace.save(save_as)
        filename=self.current_file
        if not filename or save_as:
            filename,_=QFileDialog.getSaveFileName(self,'保存工程',str(ROOT/'material.json'),'Material Lab (*.json)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(self.model.graph,ensure_ascii=False,indent=2),encoding='utf-8')
                self.current_file=filename
                self.message('已保存：'+filename)
            except OSError as exc:
                QMessageBox.warning(self,'保存失败',str(exc))

    def export_png(self,checked=False,node_id=None):
        if self.sbs_workspace.active:return self.sbs_workspace.export()
        target_id=self.selected if node_id is None else node_id
        if target_id is None:
            self.message('先选择要导出的节点')
            return
        if self.compute_timer.isActive() or self.material.dirty:
            self.compute_timer.stop()
            self.compute()
            self.material.makeCurrent()
            try:
                self.material.evaluate()
            except Exception as exc:
                self.message('无法导出：'+str(exc))
                return
            finally:
                self.material.doneCurrent()
                self.material.update()
        image=self.images.get(target_id)
        if image is None:
            self.message('等待 GPU 完成纹理计算')
            return
        filename,_=QFileDialog.getSaveFileName(self,'导出 PNG',str(ROOT/(self.model.node(target_id)['type']+'.png')),'PNG (*.png)')
        if filename:
            if image.save(filename,'PNG'):
                self.message('已导出：'+filename)
            else:
                QMessageBox.warning(self,'导出失败','无法写入文件')

    def save_autosave(self):
        if not self.save_enabled:
            return
        try:
            self.autosave.parent.mkdir(exist_ok=True)
            temporary=self.autosave.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.model.graph,ensure_ascii=False),encoding='utf-8')
            temporary.replace(self.autosave)
        except OSError as exc:
            self.message('自动保存失败：'+str(exc))

    def apply_default_layout(self):
        self.resizeDocks([self.docks['explorer'],self.docks['properties']],
                         [int(self.width()*.12),int(self.width()*.17)],Qt.Orientation.Horizontal)
        self.resizeDocks([self.docks['view3d'],self.docks['view2d']],
                         [int(self.height()*.46)]*2,Qt.Orientation.Vertical)
        self.resizeDocks([self.docks['view3d'],self.docks['view2d']],[45,55],Qt.Orientation.Horizontal)
        QTimer.singleShot(50,self.graph_view.fit_graph)

    def reset_layout(self):
        self.restoreState(self.default_layout)
        for name,dock in self.docks.items():
            dock.setVisible(name!='library')
        self.apply_default_layout()

    def fit_current_graph(self):
        if self.sbs_workspace.active:self.sbs_workspace.active.fit_selection()
        else:self.graph_view.fit_graph(True)

    def help(self):
        QMessageBox.information(self,'操作说明','节点图：空格搜索节点；单击查看属性，双击在 2D 查看。\n左键拖线或依次点击两个端口（顺序不限）；Esc 取消；Alt+单击端口断线。\n单击连线后 Delete 删除；Ctrl+单击多选；拖动默认吸附网格，Ctrl 拖动自由移动。\n图形/2D：中键或 Ctrl+右键平移，滚轮或 Alt+右键上下拖动缩放，Shift 加速。\nF 聚焦选择/适应；Z 复位缩放。2D 空格切换平铺。\n3D：左键旋转，中键/Ctrl+右键平移，滚轮/Alt+右键缩放，双击复位。\nShift+Space 打开节点库。Ctrl+D 复制；Ctrl+Z 撤销。\n拖动面板标题停靠/浮动；窗口菜单恢复默认布局。\nJSON 工程与网页版互通；Ctrl+E 导出当前所选节点。')


    def closeEvent(self,event):
        if not self.sbs_workspace.can_close():event.ignore();return
        self.compute_timer.stop()
        self.save_autosave()
        if self.save_enabled:
            self.settings.setValue('geometry',self.saveGeometry())
            self.settings.setValue('dockState',self.saveState())
        self.material.cleanup()
        super().closeEvent(event)


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    fmt=QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app=QApplication(sys.argv)
    app.setApplicationName('Material Lab Qt')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    test='--self-test' in sys.argv
    window=MainWindow(restore=not test)
    window.show()
    if test:
        from selftest import run
        QTimer.singleShot(1800,lambda:run(app,window))
    sys.exit(app.exec())


if __name__=='__main__':
    main()
