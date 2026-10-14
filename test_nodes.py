"""Compare actual GLSL output against the extracted SBS function DAG interpreter."""
import sys,json,itertools
import numpy as np
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QSurfaceFormat,QImage,QPainter,QColor,QFont
from PySide6.QtWidgets import QApplication
from OpenGL import GL as gl
from main import MainWindow,STYLE
from model import ROOT,empty,make_node,preset
from sbs_reference import render_reference,levels

def rgb(image):
    return np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4)[:,:,:3].copy()

def run():
 QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
 fmt=QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile);QSurfaceFormat.setDefaultFormat(fmt)
 app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE);w=MainWindow(restore=False);w.show();rows=[];tiles=[]
 def tests():
  view=w.material;w.compute_timer.stop();view.makeCurrent()
  def evaluate(kind,params,source='gradient',source_params=None):
   graph=empty();graph['nodes']=[make_node(1,source,params=source_params),make_node(2,kind,params=params)];graph['nodes'][1]['inputs']=[1]
   view.set_graph(graph,128);view.evaluate();return rgb(view.images[1])/255.,rgb(view.images[2])
  def compare(kind,name,params,keys,source='gradient',source_params=None):
   inp,actual=evaluate(kind,params,source,source_params)
   gray=inp[:,:,0] # all fixtures for these grayscale SBS graphs are grayscale
   expected=np.broadcast_to(render_reference(name,dict(zip(keys,params)),gray),gray.shape)
   error=float(np.abs(actual.astype(float)-np.rint(expected[:,:,None]*255)).max())
   rows.append(dict(node=kind,parameters=params,fixture=source,passed=error<=1,max_error_8bit=error))
  try:
   if not view.ready:raise RuntimeError(view.error or 'GL not ready')
   for pos,contrast,invert in itertools.product([0,.23,.5,.79,1],[0,.4,1],[0,1]):compare('histogramScan','histogram_scan',[pos,contrast,invert],['Position','Contrast','Invert_Position'])
   for span,pos in itertools.product([0,.25,1],[0,.13,.5,.87,1]):compare('histogramRange','histogram_range',[span,pos],['range','position'])
   for pos,span,contrast in itertools.product([0,.3,1],[0,.25,1],[0,.6,1]):compare('histogramSelect','histogram_select',[pos,span,contrast],['position','range','constrast'])
   for pos in [0,.17,.5,.91,1]:compare('histogramShift','histogram_shift',[pos],['position'])
   # Endpoint fixtures exercise exact black/white rather than only pixel-centered ramps.
   for name,kind,params,keys in [('histogram_scan','histogramScan',[0,1,0],['Position','Contrast','Invert_Position']),('histogram_shift','histogramShift',[0],['position']),('histogram_select','histogramSelect',[0,0,1],['position','range','constrast'])]:
    for color in ['#000000','#ffffff']:compare(kind,name,params,keys,'uniform',[color])
   for params in [[0,1,1,0,1],[.2,.8,2,.15,.9],[1,0,1,0,1],[.5,.5,1,0,1],[0,1,.5,1,0]]:
    inp,actual=evaluate('levelsAdvanced',params);expected=levels(inp,*params);error=float(np.abs(actual.astype(float)-np.rint(expected*255)).max());rows.append(dict(node='levelsAdvanced',parameters=params,passed=error<=1,max_error_8bit=error))
   for kind,params,label in [('histogramScan',[.5,.8,0],'Histogram Scan'),('histogramRange',[.3,.5],'Histogram Range'),('histogramSelect',[.5,.25,.6],'Histogram Select'),('histogramShift',[.5],'Histogram Shift'),('levelsAdvanced',[.1,.9,.7,.1,.9],'Levels Extended')]:
    evaluate(kind,params,'clouds');tiles.append((label,view.images[2].copy()))
   if gl.glGetError()!=gl.GL_NO_ERROR:raise RuntimeError('OpenGL error')
  except Exception as exc:rows.append(dict(node='test runtime',passed=False,error=repr(exc)))
  finally:view.doneCurrent()
  result={'reference':'Extracted SBS parameter DAG interpreter + independent Levels primitive; not Adobe-engine output','tolerance_8bit':1,'checks':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows)}
  (ROOT/'node-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  sheet=QImage(1000,230,QImage.Format.Format_ARGB32);sheet.fill(QColor('#333333'));painter=QPainter(sheet);painter.setFont(QFont('Segoe UI',10));painter.setPen(QColor('#ddd'))
  for i,(label,img) in enumerate(tiles):painter.drawImage(i*200+10,10,img.scaled(180,180));painter.drawText(i*200+10,215,label)
  painter.end();sheet.save(str(ROOT/'nodes-preview.png'))
  print(json.dumps({'passed':result['passed'],'total':result['total'],'failures':[r for r in rows if not r['passed']]}),flush=True);w.close();app.exit(0 if all(r['passed'] for r in rows) else 1)
 QTimer.singleShot(800,tests);return app.exec()
if __name__=='__main__':sys.exit(run())

