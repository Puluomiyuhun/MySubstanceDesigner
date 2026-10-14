"""Compact node-authoring widgets with optional local icons and a standalone fallback."""
from pathlib import Path
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QIcon,QAction
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QLabel,QToolButton,QToolBar,
    QComboBox,QTreeWidget,QLineEdit,QListWidget,QScrollArea,QSizePolicy,QMenu)
from model import ROOT,DEFINITIONS

ASSETS=ROOT/'assets/designer'
GUI='pfx/editor/gui/images/'
ALG='alg/gui/icons/'
GRAPH='pfx/editor/components/graph/images/'
COMP='sbsdatacontrol/icons/'
NODE_ICONS={'uniform':'uniform','blend':'blend','blur':'blur','directionalBlur':'dirmotionblur',
 'warp':'warp','directionalWarp':'directionalwarp','transform':'transformation','levels':'levels',
 'normal':'normal','gradient':'gradient','gradientMap':'dyngradient','output':'output',
 'levelsAdvanced':'levels','hsl':'hsl','grayscale':'grayscaleconversion','sharpen':'sharpen','distance':'distance'}
def icon(path):
    candidate=ASSETS/path
    if candidate.is_file():return QIcon(str(candidate))
    from PySide6.QtWidgets import QApplication,QStyle
    app=QApplication.instance()
    if app is None:return QIcon()
    name=Path(path).stem.lower()
    code=QStyle.StandardPixmap.SP_FileIcon
    for key,kind in [('save','SP_DialogSaveButton'),('open','SP_DirOpenIcon'),('close','SP_DialogCloseButton'),('left','SP_ArrowLeft'),('right','SP_ArrowRight'),('down','SP_ArrowDown'),('up','SP_ArrowUp'),('folder','SP_DirIcon')]:
        if key in name:code=getattr(QStyle.StandardPixmap,kind);break
    return app.style().standardIcon(code)
def button(path,label,callback,parent=None):
    b=QToolButton(parent);b.setIcon(icon(path));b.setIconSize(QSize(24,24))
    b.setToolTip(label);b.setAccessibleName(label);b.setAutoRaise(True)
    if callback:b.clicked.connect(callback)
    return b

def bar():
    w=QWidget();w.setObjectName('compactBar');l=QHBoxLayout(w)
    l.setContentsMargins(3,0,3,0);l.setSpacing(2);w.setFixedHeight(28)
    return w,l

class Section(QWidget):
    def __init__(self,title,expanded=True):
        super().__init__();outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        self.toggle=QToolButton();self.toggle.setObjectName('sectionToggle');self.toggle.setText(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True);self.toggle.setChecked(expanded)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.body=QWidget();self.content=QVBoxLayout(self.body);self.content.setContentsMargins(10,7,10,10);self.content.setSpacing(6)
        outer.addWidget(self.toggle);outer.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded);self.set_expanded(expanded)
    def set_expanded(self,expanded):
        self.body.setVisible(expanded)
        self.toggle.setIcon(icon(ALG+('lightarrowdown.svg' if expanded else 'lightarrowright.svg')))
        self.toggle.setIconSize(QSize(10,10))

class DockTitle(QWidget):
    def __init__(self,dock,name):
        super().__init__();self.setObjectName('dockTitle');self.setFixedHeight(26)
        row=QHBoxLayout(self);row.setContentsMargins(4,0,2,0);row.setSpacing(3)
        path={'explorer':'explorer','properties':'properties','library':'shelf','view3d':'view3d','view2d':'view2d'}.get(name)
        ico=QLabel();ico.setPixmap(icon(f'pfx/editor/components/{path}/'+('icons/' if name=='library' else 'images/')+'icon.svg').pixmap(14,14));row.addWidget(ico)
        self.label=QLabel(dock.windowTitle());self.label.setObjectName('dockLabel');row.addWidget(self.label,1)
        dock.windowTitleChanged.connect(self.label.setText)
        float_button=button(ALG+'dockwidgetfloat.svg','浮动 / 停靠',lambda:dock.setFloating(not dock.isFloating()));float_button.setProperty('dockControl',True);row.addWidget(float_button)
        close_button=button(ALG+'dockwidgetclose.svg','关闭面板',dock.close);close_button.setProperty('dockControl',True);row.addWidget(close_button)
        # Unhandled mouse events bubble to QDockWidget, preserving native drag docking.

def build_ui(self):
    from main import TextureView
    from renderer import MaterialView
    from graphview import GraphScene,GraphView
    file_menu=self.menuBar().addMenu('文件(&F)')
    for label,fn,key in [('新建工程',self.new_project,'Ctrl+N'),('打开工程…',self.open_project,'Ctrl+O'),('保存工程',self.save_project,'Ctrl+S'),('另存为…',lambda:self.save_project(True),'Ctrl+Shift+S'),('导出当前节点 PNG…',self.export_png,'Ctrl+E')]:self.action(file_menu,label,fn,key)
    edit=self.menuBar().addMenu('编辑(&E)')
    for label,fn,key in [('撤销',self.undo,'Ctrl+Z'),('重做',self.redo,'Ctrl+Shift+Z'),('复制节点',self.duplicate,'Ctrl+D')]:self.action(edit,label,fn,key)
    tools=self.menuBar().addMenu('工具(&T)')
    self.action(tools,'节点库',lambda:self.docks['library'].show(),'Shift+Space')
    self.view_menu=self.menuBar().addMenu('窗口(&W)')
    self.action(self.view_menu,'适应节点画布',self.fit_current_graph)
    self.action(self.view_menu,'恢复默认布局',self.reset_layout)
    help_menu=self.menuBar().addMenu('帮助(&H)');self.action(help_menu,'操作说明',self.help)
    toolbar=QToolBar('文件工具栏',self);toolbar.setObjectName('mainToolbar');toolbar.setMovable(False);toolbar.setIconSize(QSize(16,16));self.addToolBar(toolbar)
    for path,label,fn in [(GUI+'package_new.svg','新建',self.new_project),(ALG+'fileload.svg','打开',self.open_project),(GUI+'save.svg','保存',self.save_project),(GUI+'undo.svg','撤销',self.undo),(GUI+'redo.svg','重做',self.redo)]:toolbar.addWidget(button(path,label,fn))
    graph_widget=QWidget();layout=QVBoxLayout(graph_widget);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    title,row=bar();title.setObjectName('dockTitle');label=QLabel();label.setPixmap(icon(GUI+'graph.svg').pixmap(14,14));row.addWidget(label);row.addWidget(QLabel('Material Graph - 图形'),1)
    row.addWidget(button(ALG+'zoomfit.svg','适应节点画布 F',lambda:self.graph_view.fit_graph()));layout.addWidget(title)
    graphbar,row=bar()
    for path,label,fn in [(ALG+'zoomreset.svg','缩放 1:1',lambda:self.graph_view.resetTransform()),(ALG+'zoomfit.svg','适应画布',lambda:self.graph_view.fit_graph()),(GUI+'export.svg','导出当前纹理',self.export_png),(ALG+'copy.svg','复制节点',self.duplicate),(ALG+'itemdelete.svg','删除节点',self.delete_nodes)]:row.addWidget(button(path,label,fn))
    row.addSpacing(8)
    self.preset_combo=QComboBox()
    for name,value in [('风化砖墙','brick'),('锤纹金属','metal'),('木纹','wood'),('直方图节点示例','histogram')]:self.preset_combo.addItem(name,value)
    row.addWidget(self.preset_combo);row.addWidget(button(GUI+'compute.svg','载入所选示例',self.load_preset));row.addSpacing(10)
    row.addWidget(QLabel('输出尺寸：'));self.resolution=QComboBox();self.resolution.addItems(['256','512','1024']);self.resolution.setCurrentText('512');self.resolution.currentTextChanged.connect(self.schedule);row.addWidget(self.resolution);row.addStretch();layout.addWidget(graphbar)
    nodesbar=QToolBar();nodesbar.setIconSize(QSize(18,18));nodesbar.setFixedHeight(28)
    for d in DEFINITIONS:
        kind=d['id'];path=COMP+'comp_'+NODE_ICONS[kind]+'.svg' if kind in NODE_ICONS else None
        b=button(path,d['zh']+' / '+d['name'],lambda checked=False,k=kind:self.add_node(k)) if path else QToolButton()
        if not path:
            b.setIcon(QIcon(str(node_icon_path(kind))));b.setIconSize(QSize(18,18));b.setAutoRaise(True);b.setToolTip(d['zh']);b.setAccessibleName(d['zh']);b.clicked.connect(lambda checked=False,k=kind:self.add_node(k))
        nodesbar.addWidget(b)
    layout.addWidget(nodesbar)
    self.graph_scene=GraphScene(self.model,self);self.graph_scene.changed_graph.connect(self.refresh);self.graph_scene.layout_changed.connect(self.queue_save);self.graph_scene.message.connect(self.message);self.graph_scene.selectionChanged.connect(self.selection_changed);self.graph_scene.preview_requested.connect(self.view_node)
    self.graph_view=GraphView(self.graph_scene);self.graph_view.setObjectName('graphView');self.graph_view.add_requested.connect(self.add_node);self.graph_view.delete_requested.connect(self.delete_nodes);self.graph_view.search_requested.connect(lambda p:show_node_search(self,p));layout.addWidget(self.graph_view,1);self.setCentralWidget(graph_widget)
    self.explorer=QTreeWidget();self.explorer.setHeaderHidden(True);self.explorer.setMinimumWidth(120);self.explorer.setIndentation(14);self.explorer.setIconSize(QSize(14,14))
    exp=QWidget();exl=QVBoxLayout(exp);exl.setContentsMargins(0,0,0,0);exl.setSpacing(0);eb,er=bar()
    for path,label,fn in [(GUI+'save.svg','保存',self.save_project),(ALG+'fileload.svg','打开',self.open_project),(GUI+'export.svg','导出纹理',self.export_png)]:er.addWidget(button(path,label,fn))
    er.addStretch();exl.addWidget(eb);exl.addWidget(self.explorer,1)
    self.dock('explorer','资源管理器',exp,Qt.DockWidgetArea.LeftDockWidgetArea)
    lib=QWidget();ll=QVBoxLayout(lib);ll.setContentsMargins(6,6,6,6);self.search=QLineEdit();self.search.setPlaceholderText('搜索节点…');self.search.textChanged.connect(self.filter_library);ll.addWidget(self.search)
    self.category=QComboBox();self.category.addItems(['全部','生成器','处理','输出']);self.category.currentTextChanged.connect(self.filter_library);ll.addWidget(self.category)
    self.library=QListWidget();self.library.setIconSize(QSize(40,40));self.library.itemDoubleClicked.connect(lambda item:self.add_node(item.data(Qt.ItemDataRole.UserRole)));ll.addWidget(self.library)
    self.dock('library','库',lib,Qt.DockWidgetArea.LeftDockWidgetArea);self.filter_library();self.docks['library'].hide()
    self.inspector=QScrollArea();self.inspector.setWidgetResizable(True);self.inspector.setMinimumWidth(180);self.dock('properties','属性',self.inspector,Qt.DockWidgetArea.RightDockWidgetArea)
    preview=QWidget();vl=QVBoxLayout(preview);vl.setContentsMargins(0,0,0,0);vl.setSpacing(0);pb,pr=bar()
    pr.addWidget(QLabel('场景'));self.mesh=QComboBox();self.mesh.addItems(['球体','平面']);self.mesh.currentIndexChanged.connect(self.set_mesh);pr.addWidget(self.mesh);pr.addSpacing(8)
    pr.addWidget(button(ALG+'reset_to_default.svg','重置相机',self.reset_camera));pr.addStretch();vl.addWidget(pb)
    self.material=MaterialView();self.material.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding);self.material.setObjectName('materialPreview');self.material.images_ready.connect(self.images_updated);self.material.failed.connect(lambda m:self.message('GPU 错误：'+m));self.material.frame_info.connect(self.frame_info);vl.addWidget(self.material,1)
    footer,fr=bar();fr.addWidget(QLabel('  简化 PBR  ·  RGBA8'));fr.addStretch();vl.addWidget(footer)
    dock3=self.dock('view3d','材质 - 3D视图',preview,Qt.DockWidgetArea.BottomDockWidgetArea)
    preview2=QWidget();vl=QVBoxLayout(preview2);vl.setContentsMargins(0,0,0,0);vl.setSpacing(0);tb,tr=bar()
    for path,label,fn in [(GUI+'save.svg','导出 2D 预览纹理',lambda:self.export_png(node_id=self.viewed)),(ALG+'zoomfit.svg','适应纹理',lambda:self.texture.fit_texture())]:tr.addWidget(button(path,label,fn))
    tile=button('pfx/editor/components/view2d/images/tiling.svg','平铺 ×3',None);self.tile_button=tile;tile.setCheckable(True);tile.toggled.connect(self.set_tiled);tr.addWidget(tile);tr.addStretch();vl.addWidget(tb)
    self.texture=TextureView();self.texture.tile_requested.connect(tile.toggle);self.texture.setFrameShape(TextureView.Shape.NoFrame);vl.addWidget(self.texture,1)
    footer,fr=bar();self.texture_name=QLabel('当前节点');fr.addWidget(self.texture_name);fr.addStretch();fr.addWidget(QLabel('RGBA · 8 bpc  '));vl.addWidget(footer)
    dock2=self.dock('view2d','纹理 - 2D视图',preview2,Qt.DockWidgetArea.BottomDockWidgetArea);self.splitDockWidget(dock3,dock2,Qt.Orientation.Horizontal)
    for name,dock in self.docks.items():dock.setTitleBarWidget(DockTitle(dock,name));self.view_menu.addAction(dock.toggleViewAction())
    self.status_text=QLabel('正在初始化 OpenGL…');self.statusBar().addWidget(self.status_text,1);self.gpu_text=QLabel('');self.statusBar().addPermanentWidget(self.gpu_text)
    self.resizeDocks([self.docks['explorer'],self.docks['properties']],[215,300],Qt.Orientation.Horizontal)
    self.resizeDocks([dock3,dock2],[440,440],Qt.Orientation.Vertical);self.resizeDocks([dock3,dock2],[500,620],Qt.Orientation.Horizontal)
    self.default_layout=self.saveState()

STYLE='''
QWidget{background:#333333;color:#cccccc;font-family:"Segoe UI","Microsoft YaHei UI";font-size:11px;}
QMenuBar{background:#333333;min-height:18px;}QMenuBar::item{padding:2px 8px;}QMenuBar::item:selected,QMenu::item:selected{background:#505050;}
QMenu{background:#292929;border:1px solid #1b1b1b;}QMenu::item{padding:5px 25px;}
QToolBar{background:#333333;border:0;border-bottom:1px solid #1e1e1e;padding:1px;spacing:1px;}
QToolButton{border:0;padding:2px;background:transparent;}QToolButton:hover{background:#535353;}QToolButton:checked{background:#555555;}
QWidget#dockTitle{background:#2b2b2b;border-bottom:1px solid #202020;}QWidget#dockTitle QLabel{background:transparent;}QLabel#dockLabel{color:#e0e0e0;font-weight:bold;}
QDockWidget{color:#c8c8c8;}QMainWindow::separator{background:#202020;width:3px;height:3px;}QMainWindow::separator:hover{background:#666;}
QWidget#compactBar{background:#333333;border-bottom:1px solid #292929;}
QComboBox,QLineEdit,QDoubleSpinBox{background:#2d2d2d;border:1px solid #484848;border-radius:0;padding:1px 3px;min-height:16px;}
QComboBox::drop-down{border:0;width:15px;}QComboBox QAbstractItemView{background:#292929;selection-background-color:#505050;}
QDoubleSpinBox{background:transparent;border:0;}QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{width:0;}
QPushButton{background:#3b3b3b;border:1px solid #555;padding:3px;}QPushButton:hover{background:#505050;}
QTreeWidget{background:#252525;border:0;}QTreeWidget::item{height:23px;}QTreeWidget::item:selected{background:#394552;color:#cccccc;border:1px solid #698cac;}
QListWidget{background:#252525;border:0;}QListWidget::item{padding:4px;}QListWidget::item:selected{background:#394552;}
QScrollArea{border:0;}QToolButton#sectionToggle{background:#4b4b4b;text-align:left;padding:3px;font-weight:bold;}


QScrollBar:vertical{background:#333333;width:8px;}QScrollBar::handle:vertical{background:#555;min-height:25px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QStatusBar{background:#333333;color:#999;font-size:10px;}QStatusBar::item{border:0;}QLabel#subtle{color:#999;}QLabel#section{background:#4b4b4b;padding:3px;font-weight:bold;}
'''
STYLE += 'QComboBox::down-arrow{image:url("'+(ASSETS/GUI/'droparrow.svg').as_posix()+'");width:10px;height:10px;}'

PARAM_ZH={'Amount':'数量','Angle':'角度','Blending Mode':'混合模式','Brightness':'亮度','Contrast':'对比度','Distortion':'扭曲','Format':'格式','Gamma':'伽马','High Color':'高值颜色','Input High':'输入高值','Input Low':'输入低值','Intensity':'强度','Low Color':'低值颜色','Luminance Variation':'亮度变化','Mode':'模式','Mortar':'灰缝','Offset X':'X 偏移','Offset Y':'Y 偏移','Opacity':'不透明度','Pattern':'图案','Random Seed':'随机种子','Rotation':'旋转','Roughness':'粗糙度','Scale':'缩放','Size':'大小','Softness':'柔和度','Steps':'步数','Threshold':'阈值','Tiling':'平铺','Width':'宽度','X Amount':'X 数量','Y Amount':'Y 数量'}
OPTION_ZH={'Disc':'圆盘','Square':'方形','Diamond':'菱形','Copy':'复制','Multiply':'相乘','Add':'相加','Subtract':'相减','Screen':'滤色','Overlay':'叠加','Max':'最大值','Min':'最小值','Greater':'大于','Greater or equal':'大于等于','Lower':'小于','Lower or equal':'小于等于'}

# Apply the standalone theme after the custom widget styles.
import re as _re
_source_rules=(ROOT/'designer_metrics.qss').read_text(encoding='utf-8')
_source_rules=_re.sub(r'url\([\"\']?:/?([^\)\"\']+)[\"\']?\)',lambda m:'url("'+(ASSETS/m[1]).as_posix()+'")',_source_rules)
STYLE+='\n'+_source_rules


def show_node_search(window,point):
    from PySide6.QtWidgets import QDialog,QListWidgetItem
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QCursor
    class NodeSearch(QDialog):
        def __init__(self):
            super().__init__(window,Qt.WindowType.Popup)
            self.setObjectName('nodeSearch');self.resize(300,340)
            layout=QVBoxLayout(self);layout.setContentsMargins(6,6,6,6)
            self.search=QLineEdit();self.search.setPlaceholderText('搜索节点…');layout.addWidget(self.search)
            self.results=QListWidget();layout.addWidget(self.results)
            self.search.textChanged.connect(self.filter);self.search.returnPressed.connect(self.choose)
            self.results.itemActivated.connect(self.choose);self.results.itemClicked.connect(self.choose)
            self.search.installEventFilter(self);self.filter('')
        def filter(self,text):
            self.results.clear()
            for d in DEFINITIONS:
                if text.casefold() in (d['name']+' '+d['zh']).casefold():
                    item=QListWidgetItem(d['zh']+'  '+d['name']);item.setData(Qt.ItemDataRole.UserRole,d['id']);self.results.addItem(item)
            self.results.setCurrentRow(0)
        def choose(self,*args):
            item=self.results.currentItem()
            if item:
                kind=item.data(Qt.ItemDataRole.UserRole);self.close();window.add_node(kind,point)
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Down,Qt.Key.Key_Up):
                count=self.results.count()
                if count:self.results.setCurrentRow((self.results.currentRow()+(1 if event.key()==Qt.Key.Key_Down else -1))%count)
                return True
            return super().eventFilter(obj,event)
    popup=NodeSearch();window.node_search=popup;popup.move(QCursor.pos());popup.show();popup.search.setFocus()


PACKAGE_ICONS={'histogramScan':'histogram_scan','histogramRange':'histogram_range','histogramSelect':'histogram_select','histogramShift':'histogram_shift'}
def node_icon_path(kind):
    if kind in PACKAGE_ICONS and (ROOT/'assets/package-icons'/(PACKAGE_ICONS[kind]+'.png')).is_file():return ROOT/'assets/package-icons'/(PACKAGE_ICONS[kind]+'.png')
    return ROOT/'assets/thumbnails'/(kind+'.png')
PARAM_ZH.update({'Position':'位置','Range':'范围','Invert Position':'反转位置','Output Low':'输出黑场','Output High':'输出白场'})
OPTION_ZH.update({'Off':'关闭','On':'开启'})
