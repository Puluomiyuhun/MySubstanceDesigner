"""Mount SBS documents into the existing main-window docks and package tree."""
from pathlib import Path
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QStackedWidget,QTabWidget,
    QToolBar,QTreeWidgetItem,QLabel,QMessageBox,QFileDialog)
from sbs_editor import SBSEditor
from designer_ui import icon,GUI

ROLE=Qt.ItemDataRole.UserRole+7

class WorkspaceEditor(SBSEditor):
    graph_changed=Signal()
    def load(self,*args,**kwargs):
        super().load(*args,**kwargs);self.graph_changed.emit()
    def save(self,*args,**kwargs):
        result=super().save(*args,**kwargs);self.graph_changed.emit();return result

class SBSWorkspace:
    def __init__(self,main):
        self.main=main;self.documents=[];self.active=None
        self.graph_stack=QStackedWidget();self.toy_graph=main.takeCentralWidget()
        self.graph_stack.addWidget(self.toy_graph);main.setCentralWidget(self.graph_stack)
        self.stacks={};self.toy_titles={}
        for name in ('properties','view2d','view3d'):
            dock=main.docks[name];self.toy_titles[name]=dock.windowTitle();widget=dock.widget()
            stack=QStackedWidget();widget.setParent(stack);stack.addWidget(widget);dock.setWidget(stack);self.stacks[name]=stack
        main.explorer.itemClicked.connect(self.tree_clicked)
    def rebuild_tree(self):
        tree=self.main.explorer
        # MainWindow.refresh builds the toy package first. Remove only our old rows.
        for index in range(tree.topLevelItemCount()-1,-1,-1):
            if tree.topLevelItem(index).data(0,ROLE) is not None:tree.takeTopLevelItem(index)
        for index,doc in enumerate(self.documents):
            editor=doc['editor'];package=QTreeWidgetItem([Path(editor.current_save or editor.project.root).name])
            package.setIcon(0,icon(GUI+'package.svg'));package.setData(0,ROLE,(index,'',''))
            tree.addTopLevelItem(package)
            for name in editor.project.package(editor.project.root)['graphs']:
                row=QTreeWidgetItem([name]);row.setIcon(0,icon(GUI+'graph.svg'));row.setData(0,ROLE,(index,str(editor.project.root),name));package.addChild(row)
                if editor is self.active and editor.current==(str(editor.project.root),name):tree.setCurrentItem(row)
            package.setExpanded(True)
    def open(self,path):
        canonical=str(Path(path).resolve())
        for doc in self.documents:
            editor=doc['editor']
            if canonical in (doc['opened'],str(Path(editor.current_save).resolve()) if editor.current_save else ''):
                self.activate(editor);return editor
        editor=WorkspaceEditor(path,self.main)
        editor.setWindowFlags(Qt.WindowType.Widget);editor.hide()
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        for toolbar in editor.findChildren(QToolBar,options=Qt.FindChildOption.FindDirectChildrenOnly):
            editor.removeToolBar(toolbar);layout.addWidget(toolbar);toolbar.show()
            for action in toolbar.actions():
                if action.shortcut().toString() in ('Ctrl+S','Ctrl+Z'):action.setShortcut('')
        layout.addWidget(editor.takeCentralWidget(),1)
        for action in editor.actions():
            editor.removeAction(action);page.addAction(action);action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        editor.table.setColumnHidden(1,True);editor.table.verticalHeader().hide();editor.table.setColumnWidth(0,110)
        properties=QTabWidget();properties.addTab(editor.table,'参数');properties.addTab(editor.inspector,'原始 SBS')
        preview=editor.preview;preview.setParent(self.stacks['view2d'])
        unavailable=QLabel('SBS 当前支持局部节点的 2D 求值。\n完整材质通道尚未绑定到 3D 预览。');unavailable.setAlignment(Qt.AlignmentFlag.AlignCenter);unavailable.setWordWrap(True)
        self.graph_stack.addWidget(page);self.stacks['properties'].addWidget(properties);self.stacks['view2d'].addWidget(preview);self.stacks['view3d'].addWidget(unavailable)
        doc={'opened':canonical,'editor':editor,'page':page,'properties':properties,'view2d':preview,'view3d':unavailable};self.documents.append(doc)
        editor.graph_changed.connect(lambda:self.changed(editor))
        editor.statusBar().messageChanged.connect(lambda message:self.main.message(message) if self.active is editor else None)
        self.rebuild_tree();self.activate(editor);return editor
    def changed(self,editor):
        if self.active is editor:self.titles();self.rebuild_tree()
    def titles(self):
        editor=self.active
        if editor:
            self.main.docks['properties'].setWindowTitle(editor.graph['name']+' - 属性')
            self.main.docks['view2d'].setWindowTitle(editor.graph['name']+' - 2D视图')
            self.main.docks['view3d'].setWindowTitle('SBS - 3D视图')
            self.main.setWindowModified(any(d['editor'].edits.dirty for d in self.documents))
    def activate(self,editor=None,path=None,name=None):
        self.active=editor
        if editor is None:
            self.graph_stack.setCurrentWidget(self.toy_graph)
            for key,stack in self.stacks.items():stack.setCurrentIndex(0);self.main.docks[key].setWindowTitle(self.toy_titles[key])
            return
        doc=next(d for d in self.documents if d['editor'] is editor)
        self.graph_stack.setCurrentWidget(doc['page'])
        for key,stack in self.stacks.items():stack.setCurrentWidget(doc[key])
        if path and editor.current!=(path,name):editor.load(path,name)
        self.titles();editor.instructions();self.rebuild_tree()
    def tree_clicked(self,item,column):
        data=item.data(0,ROLE)
        if data is None:self.activate();return
        index,path,name=data;self.activate(self.documents[index]['editor'],path or None,name or None)
    def save(self,save_as=False):
        result=self.active.save(save_as);self.rebuild_tree();self.titles();return result
    def export(self):
        pixmap=self.active.preview.pixmap()
        if pixmap is None or pixmap.isNull():self.main.message('请先计算一个受支持的图像节点');return
        path,_=QFileDialog.getSaveFileName(self.main,'导出当前 SBS 预览','preview.png','PNG (*.png)')
        if path:
            if not pixmap.save(path):QMessageBox.warning(self.main,'导出失败',path)
    def can_close(self):
        for doc in self.documents:
            editor=doc['editor']
            if not editor.edits.dirty:continue
            self.activate(editor)
            answer=QMessageBox.question(self.main,'未保存的工程',f'保存 {Path(editor.current_save or editor.project.root).name} 的修改？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
            if answer==QMessageBox.StandardButton.Cancel:return False
            if answer==QMessageBox.StandardButton.Save and not self.save():return False
        for doc in self.documents:doc['editor'].timer.stop();doc['editor'].version+=1
        return True
