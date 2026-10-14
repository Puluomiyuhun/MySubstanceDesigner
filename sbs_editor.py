"""Editable SBS workspace with native snapshot save and selective evaluation."""
import copy,json
import xml.etree.ElementTree as ET
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QObject,Signal,QRunnable,QThreadPool,QPointF
from PySide6.QtGui import QAction,QPixmap,QPainterPath
from PySide6.QtWidgets import (QDockWidget,QTableWidget,QTableWidgetItem,QLabel,
    QInputDialog,QFileDialog,QMessageBox,QComboBox,QGraphicsItem)
from sbs_browser import SBSBrowser
from sbs_edit import load_project,save_project,Edits,PORTS,DEFAULTS,WRAPPERS,constant,connect,add_node,add_instance,sync
from sbs_compute import Evaluator,display_image

class Result(QObject):done=Signal(int,object,str)
class Job(QRunnable):
    def __init__(self,version,project,key,uid,output,size):
        super().__init__();self.result=Result();self.version=version;self.project=project;self.key=key;self.uid=uid;self.output=output;self.size=size
    def run(self):
        try:
            evaluator=Evaluator(self.project,self.size);pixels=evaluator.evaluate(*self.key,self.uid,self.output)
            preview=(f'Float1 数值输出：{float(pixels):.8g}' if pixels.ndim==0 else '向量数值输出：'+str(pixels.tolist())) if pixels.ndim<=1 else display_image(pixels)
            thumbnails={key[2]:display_image(value).scaled(88,88,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
                        for key,value in evaluator.cache.items() if key[:2]==self.key and not key[4] and value.ndim==3}
            approximation=' · 近似运算：'+', '.join(sorted(evaluator.approximations)) if evaluator.approximations else ''
            self.result.done.emit(self.version,{'preview':preview,'thumbnails':thumbnails},f'已计算 {evaluator.count} 个节点 · float32 中间值 · {self.size}² 固定尺寸预览 · 尚未与原版逐像素校准'+approximation)
        except Exception as exc:self.result.done.emit(self.version,None,str(exc))

class SBSEditor(SBSBrowser):
    def __init__(self,path,parent=None):
        self.edits=None;self.pending_port=None;self.version=0;self.current_save=path if Path(path).suffix.lower()=='.mlsbs' else None
        super().__init__(path,parent,load_project(path));self.edits=Edits(self.project)
        self.setWindowTitle('SBS 可编辑工程 — '+Path(path).name+'[*]')
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['参数','类型','常量值（双击修改）'])
        self.table.horizontalHeader().setStretchLastSection(True);self.table.itemChanged.connect(self.parameter_changed)
        dock=QDockWidget('编辑参数',self);dock.setWidget(self.table);self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock)
        self.preview=QLabel('选择节点后点击“计算选中”\n支持 Pixel Processor、Histogram Select、Blend、Levels 等节点\n包装子图支持输入绑定、参数覆盖及部分动态表达式；遇到未实现运算会说明原因')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumSize(256,200);self.preview.setWordWrap(True)
        dock=QDockWidget('2D 计算预览',self);dock.setWidget(self.preview);self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock)
        bar=self.addToolBar('工程编辑')
        for title,callback,shortcut in [('保存工程',self.save,'Ctrl+S'),('撤销',lambda:self.undo(False),'Ctrl+Z'),('重做',lambda:self.undo(True),'Ctrl+Y'),('添加节点',self.add,'Insert'),('删除节点',self.delete,'Delete')]:
            action=bar.addAction(title,callback);action.setShortcut(shortcut)
        bar.addAction('另存为',lambda:self.save(True));bar.addAction('计算选中',self.compute)
        bar.addAction('渐变关键点',self.edit_gradient)
        self.output_combo=QComboBox();bar.addWidget(self.output_combo)
        self.resolution=QComboBox();self.resolution.addItems(['64','128','256','512']);self.resolution.setCurrentText('256');bar.addWidget(self.resolution)
        escape=QAction(self);escape.setShortcut('Escape');escape.triggered.connect(self.cancel_link);self.addAction(escape)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.compute)
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.jobs={};self.busy=False;self.recompute=False
        self.scene.selectionChanged.connect(self.edit_selection)
        self.instructions()
    def edit_gradient(self):
        from sbs_gradients import get_keys,set_keys
        n=self.selected()
        if not n or n['filter']!='gradient':
            QMessageBox.information(self,'渐变关键点','请先选择 Gradient 节点');return
        try:
            content=json.dumps(get_keys(n),ensure_ascii=False,indent=2)
            text,ok=QInputDialog.getMultiLineText(self,'渐变关键点','每项：[位置, R, G, B, A]；数值范围 0–1',content)
            if ok:
                keys=json.loads(text);uid=n['uid']
                self.mutate(lambda g:set_keys(next(i for i in g['nodes'] if i['uid']==uid),keys),uid)
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'渐变关键点',str(exc))
    def instructions(self):
        self.statusBar().showMessage(f'{self.graph["name"]} | {len(self.items)} 节点 · {len(self.edges)} 连线 | 拖动节点；点击输出再点击输入连线；右击输入断开；Ctrl+S 保存 .mlsbs')
    def input_names(self,n):
        names=list(PORTS.get(n['filter'],[]))
        if n['kind']=='compOutputBridge':names=['inputNodeOutput']
        if n['kind']=='compInstance':
            r=self.project.instance(self.package,n)
            if r['status']=='resolved':names=[p['name'] for p in self.project.package(r['path'])['graphs'][r['graph']]['inputs'] if p['connectable']]
        return list(dict.fromkeys(names+[c['input'] for c in n['connections']]))
    def load(self,path,name,remember=True):
        self.pending_port=None;self.version+=1
        if hasattr(self,'timer'):self.timer.stop();self.recompute=False
        super().load(path,name,remember)
        self.inspector.setPlainText('可编辑 SBS 工程\n'+path+'\n'+name+'\n\n选择节点后在“编辑参数”中修改常量。\n点击输出端口，再点击目标输入端口完成连线；右击输入断开。\n\n包装图修改作用于本工程内所有引用此定义的实例；不会写入源 SBS 或安装目录。\n\n计算为固定预览分辨率，尚未实现完整 SBS 分辨率/像素格式继承。')
        for item in self.items.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable);item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.combo.setPlaceholderText(name);self.combo.setCurrentIndex(self.combo.findText(name) if path==str(self.project.root) else -1)
        if hasattr(self,'table'):
            self.table.setRowCount(0);self.output_combo.clear();self.preview.setText('当前图尚未计算；选择节点后计算预览')
        self.instructions()
    def selected(self):
        return next((i.data for i in self.scene.selectedItems() if hasattr(i,'data') and isinstance(i.data,dict)),None)
    def refresh_edit(self,uid=None):
        transform=self.view.transform();center=self.view.mapToScene(self.view.viewport().rect().center())
        self.load(*self.current,remember=False);self.view.setTransform(transform);self.view.centerOn(center)
        if uid in self.items:self.items[uid].setSelected(True)
        self.setWindowModified(self.edits.dirty)
    def mutate(self,action,uid=None):
        try:self.edits.change(self.current,action);self.refresh_edit(uid);self.timer.start(180)
        except Exception as exc:QMessageBox.warning(self,'编辑未应用',str(exc))
    def edit_selection(self):
        self.version+=1
        if not hasattr(self,'table'):return
        self.table.blockSignals(True);self.table.setRowCount(0);self.output_combo.clear();n=self.selected()
        if n:
            defaults=dict(DEFAULTS.get(n['filter'],{}))
            if n['kind']=='compInstance':
                resolved=self.project.instance(self.package,n)
                if resolved['status']=='resolved':
                    for entry in self.project.package(resolved['path'])['graphs'][resolved['graph']]['inputs']:
                        if entry['type'] in ('1','2'):continue
                        value=ET.fromstring(entry['xml']).find('defaultValue')
                        if value is not None and len(value)==1 and value[0].tag.startswith('constantValue'):
                            defaults[entry['name']]=(value[0].tag,value[0].get('v',''))
            params={p['name']:p for p in n['parameters']}
            if n['kind']=='compInputBridge':
                entry=next((p for p in self.graph['inputs'] if p['uid']==n['entry']),None)
                default=ET.fromstring(entry['xml']).find('defaultValue') if entry else None
                if default is not None and len(default)==1 and default[0].tag=='constantValueFloat1':
                    params['__input_default__']={'name':'__input_default__','dynamic':False,'relative_to':'0','value':[(default[0].tag,default[0].get('v'))]}
            names=list(dict.fromkeys(list(params)+list(defaults)))
            self.table.setRowCount(len(names))
            for row,name in enumerate(names):
                p=params.get(name);editable=True
                if p:
                    editable=not p['dynamic'] and p['relative_to'] in ('','0') and bool(p['value']) and len(p['value'])==1
                    tag,text=p['value'][0] if editable else ('表达式/相对值','请在原始参数中查看；暂不支持编辑')
                else:tag,text=defaults[name]
                for col,text_value in enumerate([name,tag,text]):
                    cell=QTableWidgetItem(str(text_value));cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable if col!=2 or not editable else cell.flags());self.table.setItem(row,col,cell)
            bridgings={b['uid']:b['name'] for b in n['output_bridgings']}
            for o in n['outputs']:self.output_combo.addItem(bridgings.get(o['uid'],o['uid']),o['uid'])
            if not n['outputs']:self.output_combo.addItem('图输出','')
        self.table.blockSignals(False)
        self.preview.setText('选择已变化；点击“计算选中”查看当前节点')
    def parameter_changed(self,item):
        if item.column()!=2:return
        n=self.selected()
        if not n:return
        name=self.table.item(item.row(),0).text();tag=self.table.item(item.row(),1).text();text=item.text();uid=n['uid']
        def action(g):
            node=next(n for n in g['nodes'] if n['uid']==uid)
            if name=='__input_default__':
                constant(copy.deepcopy(node),name,tag,text) # validate without adding a fake SBS node parameter
                entry=next(p for p in g['inputs'] if p['uid']==node['entry']);xml=ET.fromstring(entry['xml']);xml.find('defaultValue')[0].set('v',text);entry['xml']=ET.tostring(xml,encoding='unicode')
            else:constant(node,name,tag,text)
        self.mutate(action,uid)
    def positions_changed(self):
        positions={uid:[item.pos().x(),item.pos().y(),*item.data['position'][2:]] for uid,item in self.items.items() if [item.pos().x(),item.pos().y()]!=item.data['position'][:2]}
        if not positions:return
        def action(g):
            for n in g['nodes']:
                if n['uid'] in positions:n['position']=positions[n['uid']];sync(n)
        n=self.selected();self.mutate(action,n['uid'] if n else None)
    def node_moved(self,uid):
        for edge in self.edges:
            target,c=edge.data(0)
            if uid not in (target,c['source']):continue
            a=self.items[c['source']].port(c['source_output'],True);b=self.items[target].port(c['input']);d=max(45,abs(b.x()-a.x())*.45)
            curve=QPainterPath(a);curve.cubicTo(a+QPointF(d,0),b-QPointF(d,0),b);edge.setPath(curve)
    def cancel_link(self):self.pending_port=None;self.instructions()
    def port_click(self,uid,port,output,button):
        if button==Qt.MouseButton.RightButton and not output:
            def action(g):
                n=next(n for n in g['nodes'] if n['uid']==uid);n['connections']=[c for c in n['connections'] if c['input']!=port];sync(n)
            self.mutate(action,uid);self.pending_port=None;return
        if button!=Qt.MouseButton.LeftButton:return
        if self.pending_port is None or self.pending_port[2]==output:
            self.pending_port=(uid,port,output);self.statusBar().showMessage('点击另一端端口完成连线，Esc 取消');return
        other=self.pending_port;self.pending_port=None
        source,out=(uid,port) if output else other[:2];target,inp=other[:2] if output else (uid,port)
        self.mutate(lambda g:connect(g,source,out,target,inp),target)
    def add(self):
        kind,ok=QInputDialog.getItem(self,'添加节点','底层运算 / 包装子图',list(DEFAULTS)+['包装 / '+name for name in WRAPPERS],0,False)
        if not ok:return
        center=self.view.mapToScene(self.view.viewport().rect().center());added=[]
        self.mutate(lambda g:added.append(add_instance(self.project,self.package,g,kind.split(' / ')[1],[center.x(),center.y()]) if kind.startswith('包装 / ') else add_node(g,kind,[center.x(),center.y()])))
        if added:self.items[added[0]['uid']].setSelected(True)
    def delete(self):
        ids={i.data['uid'] for i in self.scene.selectedItems() if hasattr(i,'data') and isinstance(i.data,dict)}
        if not ids:return
        def action(g):
            g['nodes']=[n for n in g['nodes'] if n['uid'] not in ids]
            for n in g['nodes']:
                n['connections']=[c for c in n['connections'] if c['source'] not in ids];sync(n)
        self.mutate(action)
    def undo(self,redo):
        key=self.edits.restore(redo)
        if key:
            if key==self.current:self.refresh_edit()
            else:self.load(*key)
    def save(self,save_as=False):
        path=self.current_save
        if not path or save_as:
            path,_=QFileDialog.getSaveFileName(self,'保存可编辑 SBS 工程',str(self.project.root.with_suffix('.mlsbs')),'Material Lab SBS (*.mlsbs)')
        if not path:return False
        if not path.lower().endswith('.mlsbs'):path+='.mlsbs'
        try:save_project(self.project,path);self.current_save=path;self.edits.dirty=False;self.setWindowModified(False);self.statusBar().showMessage('工程已保存：'+path);return True
        except Exception as exc:QMessageBox.warning(self,'保存失败',str(exc));return False
    def compute(self):
        self.timer.stop()
        n=self.selected()
        if n is None:return
        if self.busy:self.recompute=True;return
        self.version+=1;version=self.version;self.busy=True;self.recompute=False
        self.preview.setText('正在计算当前分支…')
        job=Job(version,copy.deepcopy(self.project),self.current,n['uid'],self.output_combo.currentData() or '',int(self.resolution.currentText()))
        self.jobs[version]=job;job.result.done.connect(self.computed);self.pool.start(job)
    def computed(self,version,image,message):
        self.jobs.pop(version,None);self.busy=False
        if version==self.version:
            if isinstance(image,dict):
                for uid,thumbnail in image['thumbnails'].items():
                    if uid in self.items:self.items[uid].preview_image=thumbnail;self.items[uid].update()
                image=image['preview']
            if image is None:self.preview.setText('当前分支无法求值：\n'+message)
            elif isinstance(image,str):self.preview.setText(image)
            else:
                self.preview.setPixmap(QPixmap.fromImage(image))
                node=self.selected()
                if node and node['uid'] in self.items:self.items[node['uid']].preview_image=image;self.items[node['uid']].update()
            self.preview.setToolTip(message);self.statusBar().showMessage(message)
        if self.recompute:self.timer.start(20)
    def closeEvent(self,event):
        if self.edits.dirty:
            answer=QMessageBox.question(self,'未保存的 SBS 工程','保存编辑后的工程？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
            if answer==QMessageBox.StandardButton.Cancel or answer==QMessageBox.StandardButton.Save and not self.save():event.ignore();return
        self.timer.stop();self.version+=1;event.accept()
