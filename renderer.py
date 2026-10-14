"""OpenGL node graph and GPU material preview, sharing one native context.

Orbit-only frames do not evaluate nodes, read pixels, or upload textures.
"""
import ctypes
import math
import time
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from model import ROOT, DEFS, CHANNELS, validate

VERTEX = '''#version 330 core
layout(location=0) in vec2 position;out vec2 uv;
void main(){uv=position*.5+.5;gl_Position=vec4(position,0,1);}'''


class MaterialView(QOpenGLWidget):
    images_ready = Signal(object)
    frame_info = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('左键旋转 · 中键 / Ctrl+右键平移 · Alt+右键 / 滚轮缩放 · 双击重置')
        self.yaw, self.pitch, self.zoom, self.shape = .4, .12, 1., 0
        self.graph, self.size, self.dirty = None, 512, False
        self.cache, self.images = {}, {}
        self.revision = self.evaluations = self.readbacks = self.frames = 0
        self.last_frame_ms = 0.
        self.error = None
        self.ready = False
        self.drag_pos = None
        self.drag_mode = None
        self.camera_pan = [0.,0.]
        self.renderer_name = ''
        self.last_info = 0

    def set_graph(self, graph, size=512):
        validate(graph)
        self.graph = graph
        self.size = size
        self.dirty = True
        self.update()

    def initializeGL(self):
        try:
            self.renderer_name = gl.glGetString(gl.GL_RENDERER).decode()
            self.node_program = compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER), compileShader((ROOT/'shaders/nodes.frag').read_text(), gl.GL_FRAGMENT_SHADER))
            self.preview_program = compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER), compileShader((ROOT/'shaders/preview.frag').read_text(), gl.GL_FRAGMENT_SHADER))
            self.vao = gl.glGenVertexArrays(1)
            gl.glBindVertexArray(self.vao)
            self.vbo = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
            verts = np.array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1], dtype=np.float32)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, False, 0, ctypes.c_void_p(0))
            self.fbo = gl.glGenFramebuffers(1)
            self.blank = self.texture(1, bytes([128,128,255,255]))
            self.black = self.texture(1, bytes([0,0,0,255]))
            self.node_uniforms = {k:gl.glGetUniformLocation(self.node_program,k) for k in ('op','p','q','a','b','c','lowColor','highColor','size','maskOn')}
            self.preview_uniforms = {k:gl.glGetUniformLocation(self.preview_program,k) for k in ('baseTex','heightTex','roughTex','normalTex','viewportSize','angles','cameraPan','zoom','textureSize','shape','bound')}
            self.ready = True
            self.dirty = self.graph is not None
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)

    def texture(self, size, data=None):
        tex = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA8,size,size,0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,data)
        for field, value in ((gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR),(gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR),(gl.GL_TEXTURE_WRAP_S,gl.GL_REPEAT),(gl.GL_TEXTURE_WRAP_T,gl.GL_REPEAT)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D,field,value)
        return tex

    def evaluate(self):
        gl.glUseProgram(self.node_program)
        gl.glBindVertexArray(self.vao)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glViewport(0,0,self.size,self.size)
        nodes = {n['id']:n for n in self.graph['nodes']}
        for node_id in list(self.cache):
            if node_id not in nodes:
                gl.glDeleteTextures([self.cache.pop(node_id)['tex']])
                self.images.pop(node_id,None)
        visited = set()
        def visit(node_id):
            if node_id in visited:
                return self.cache[node_id]
            n = nodes[node_id]
            inputs = [visit(i) if i is not None else None for i in n['inputs']]
            key = (self.size,n['type'],tuple(n['p']),tuple(i['revision'] if i else None for i in inputs))
            old = self.cache.get(node_id)
            visited.add(node_id)
            if old and old['key'] == key:
                return old
            if old:
                gl.glDeleteTextures([old['tex']])
            tex = self.texture(self.size)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,gl.GL_COLOR_ATTACHMENT0,gl.GL_TEXTURE_2D,tex,0)
            if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('GPU 帧缓冲不可用')
            u = self.node_uniforms
            for i in range(3):
                gl.glActiveTexture(gl.GL_TEXTURE0+i)
                gl.glBindTexture(gl.GL_TEXTURE_2D,inputs[i]['tex'] if i<len(inputs) and inputs[i] else self.black)
                gl.glUniform1i(u[('a','b','c')[i]],i)
            gl.glUniform1i(u['op'],DEFS[n['type']]['op'])
            values = [float(n['p'][i]) if i<len(n['p']) and isinstance(n['p'][i],(int,float)) else v for i,v in enumerate((0,1,0,0))]
            gl.glUniform4f(u['p'],*values)
            extra=[float(n['p'][i]) if i<len(n['p']) and isinstance(n['p'][i],(int,float)) else 0. for i in range(4,8)]
            gl.glUniform4f(u['q'],*extra)
            colors = [p for p in n['p'] if isinstance(p,str)]
            for k, col in zip(('lowColor','highColor'),colors+['#000000','#ffffff'] if len(colors)==0 else colors+['#ffffff']):
                gl.glUniform3f(u[k],*[int(col[i:i+2],16)/255 for i in (1,3,5)])
            gl.glUniform1f(u['size'],self.size)
            gl.glUniform1i(u['maskOn'],len(inputs)>2 and inputs[2] is not None)
            gl.glDrawArrays(gl.GL_TRIANGLES,0,6)
            data = gl.glReadPixels(0,0,self.size,self.size,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE)
            self.images[node_id] = QImage(data,self.size,self.size,self.size*4,QImage.Format.Format_RGBA8888).copy()
            self.evaluations += 1
            self.readbacks += 1
            self.revision += 1
            entry = dict(key=key,tex=tex,revision=self.revision)
            self.cache[node_id] = entry
            return entry
        for node_id in nodes:
            visit(node_id)
        self.dirty = False
        self.images_ready.emit(dict(self.images))

    def draw_material(self):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.defaultFramebufferObject())
        dpr = self.devicePixelRatioF()
        w,h = max(1,int(self.width()*dpr)),max(1,int(self.height()*dpr))
        gl.glViewport(0,0,w,h)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(self.preview_program)
        gl.glBindVertexArray(self.vao)
        u = self.preview_uniforms
        flags = []
        for i,k in enumerate(CHANNELS):
            entry = self.cache.get(self.graph['bindings'][k]) if self.graph else None
            flags.append(1 if entry else 0)
            gl.glActiveTexture(gl.GL_TEXTURE0+i)
            gl.glBindTexture(gl.GL_TEXTURE_2D,entry['tex'] if entry else self.blank)
            gl.glUniform1i(u[('baseTex','heightTex','roughTex','normalTex')[i]],i)
        gl.glUniform4i(u['bound'],*flags)
        gl.glUniform2f(u['viewportSize'],w,h)
        gl.glUniform2f(u['angles'],self.yaw,self.pitch)
        gl.glUniform2f(u['cameraPan'],*self.camera_pan)
        gl.glUniform1f(u['zoom'],self.zoom)
        gl.glUniform1f(u['textureSize'],self.size)
        gl.glUniform1i(u['shape'],self.shape)
        gl.glDrawArrays(gl.GL_TRIANGLES,0,6)

    def paintGL(self):
        if not self.ready:
            return
        start = time.perf_counter()
        try:
            if self.dirty and self.graph is not None:
                self.evaluate()
            self.draw_material()
            self.frames += 1
            self.last_frame_ms = (time.perf_counter()-start)*1000
            now = time.perf_counter()
            if now-self.last_info>.3:
                self.last_info=now
                self.frame_info.emit(f'GPU · 帧提交 {self.last_frame_ms:.2f} ms · 累计节点计算 {self.evaluations}')
        except Exception as exc:
            self.error=str(exc)
            self.dirty=False
            self.failed.emit(str(exc))

    def mousePressEvent(self,event):
        mods=event.modifiers();right=event.button()==Qt.MouseButton.RightButton
        mode='zoom' if right and mods&Qt.KeyboardModifier.AltModifier else 'pan' if event.button()==Qt.MouseButton.MiddleButton or right and mods&Qt.KeyboardModifier.ControlModifier else 'orbit' if event.button()==Qt.MouseButton.LeftButton else None
        if mode:
            self.drag_mode=mode;self.drag_pos=event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor);event.accept()

    def mouseMoveEvent(self,event):
        if self.drag_pos is not None:
            delta=event.position()-self.drag_pos;self.drag_pos=event.position()
            if self.drag_mode=='orbit':
                self.yaw+=delta.x()*.008;self.pitch=max(-1.45,min(1.45,self.pitch+delta.y()*.008))
            elif self.drag_mode=='pan':
                factor=3./(max(1,self.height())*self.zoom)
                self.camera_pan[0]-=delta.x()*factor;self.camera_pan[1]+=delta.y()*factor
            elif self.drag_mode=='zoom':self.zoom=max(.55,min(1.6,self.zoom*math.exp(max(-3,min(3,delta.y()*.01)))))
            self.update();event.accept()

    def mouseReleaseEvent(self,event):
        self.drag_pos=None;self.drag_mode=None;self.unsetCursor()

    def focusOutEvent(self,event):
        self.drag_pos=None;self.drag_mode=None;self.unsetCursor();super().focusOutEvent(event)

    def wheelEvent(self,event):
        self.zoom=max(.55,min(1.6,self.zoom*math.exp(event.angleDelta().y()*.0008)))
        self.update();event.accept()

    def reset_camera(self):
        self.yaw,self.pitch,self.zoom=.4,.12,1.;self.camera_pan=[0.,0.];self.update()

    def mouseDoubleClickEvent(self,event):
        self.reset_camera()

    def cleanup(self):
        if not self.ready:
            return
        self.makeCurrent()
        gl.glDeleteTextures([e['tex'] for e in self.cache.values()]+[self.blank,self.black])
        gl.glDeleteFramebuffers(1,[self.fbo])
        gl.glDeleteBuffers(1,[self.vbo])
        gl.glDeleteVertexArrays(1,[self.vao])
        gl.glDeleteProgram(self.node_program)
        gl.glDeleteProgram(self.preview_program)
        self.cache.clear()
        self.ready=False
        self.doneCurrent()
