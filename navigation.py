"""Shared graph/2D navigation, matching Designer's documented Windows gestures."""
import math
from PySide6.QtCore import Qt,QPointF
from PySide6.QtWidgets import QGraphicsView

class NavigationView(QGraphicsView):
    def __init__(self,*args):
        super().__init__(*args)
        self.nav_mode=None;self.nav_pos=None;self.nav_button=None
        self.zoom_limits=(.02,20.)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.suppress_context=False

    def zoom_at(self,factor,point):
        old=self.transform().m11();target=max(self.zoom_limits[0],min(self.zoom_limits[1],old*factor))
        before=self.mapToScene(point.toPoint() if isinstance(point,QPointF) else point)
        self.scale(target/old,target/old)
        after=self.mapToScene(point.toPoint() if isinstance(point,QPointF) else point)
        center=self.mapToScene(self.viewport().rect().center())
        self.centerOn(center+before-after)

    def wheelEvent(self,event):
        delta=event.angleDelta().y()/120
        if not delta and not event.pixelDelta().isNull():delta=event.pixelDelta().y()/40
        speed=3 if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else 1
        self.zoom_at(math.exp(max(-3,min(3,delta*.14*speed))),event.position());event.accept()

    def mousePressEvent(self,event):
        self.suppress_context=False
        mods=event.modifiers();right=event.button()==Qt.MouseButton.RightButton
        mode='zoom' if right and mods&Qt.KeyboardModifier.AltModifier else 'pan' if event.button()==Qt.MouseButton.MiddleButton or right and mods&Qt.KeyboardModifier.ControlModifier else None
        if mode:
            self.nav_mode=mode;self.nav_pos=event.position();self.nav_button=event.button();self.suppress_context=True
            self.setCursor(Qt.CursorShape.SizeVerCursor if mode=='zoom' else Qt.CursorShape.ClosedHandCursor);event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.nav_mode:
            delta=event.position()-self.nav_pos
            if self.nav_mode=='pan':
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-round(delta.x()))
                self.verticalScrollBar().setValue(self.verticalScrollBar().value()-round(delta.y()))
                self.nav_pos=event.position()
            else:
                speed=3 if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else 1
                # Down moves closer; up moves away, as documented for Alt+RMB.
                self.zoom_at(math.exp(max(-3,min(3,delta.y()*.01*speed))),self.nav_pos)
                self.nav_pos=event.position()
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.nav_mode and event.button()==self.nav_button:
            self.nav_mode=None;self.nav_pos=None;self.nav_button=None;self.unsetCursor();event.accept();return
        super().mouseReleaseEvent(event)

    def focusOutEvent(self,event):
        self.nav_mode=None;self.nav_pos=None;self.nav_button=None;self.unsetCursor()
        super().focusOutEvent(event)
