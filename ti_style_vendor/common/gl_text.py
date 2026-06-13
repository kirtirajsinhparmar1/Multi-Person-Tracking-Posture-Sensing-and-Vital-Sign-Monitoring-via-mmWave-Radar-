# Vendored from: tools\visualizers\Applications_Visualizer\common\gl_text.py
import logging
import math
import os

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.Qt import QtCore, QtGui


log = logging.getLogger(__name__)
GL_TEXT_DISABLED = os.environ.get("TI_STYLE_DISABLE_GL_TEXT") == "1"


class GLTextItem(gl.GLTextItem):
    def __init__(self, X=None, Y=None, Z=None, text=None, force_enabled=False, color=None):
        self.X = 0.0 if X is None else float(X)
        self.Y = 0.0 if Y is None else float(Y)
        self.Z = 0.0 if Z is None else float(Z)
        self._force_enabled = bool(force_enabled)
        self._paint_failed = False
        self.GLViewWidget = None

        font = QtGui.QFont('Helvetica', 16)
        label_color = color if color is not None else QtCore.Qt.GlobalColor.white
        gl.GLTextItem.__init__(
            self,
            pos=np.array([self.X, self.Y, self.Z], dtype=float),
            text="" if text is None else str(text),
            color=label_color,
            font=font,
        )

    def _set_data_safe(self, **kwargs):
        try:
            self.setData(**kwargs)
        except Exception as exc:
            self._paint_failed = True
            try:
                self.setVisible(False)
            except Exception:
                pass
            log.warning("GLTextItem disabled after data update failure: %s", exc)

    def setFont(self, fontObj):
        self._set_data_safe(font=fontObj)
        
    def setGLViewWidget(self, GLViewWidget):
        self.GLViewWidget = GLViewWidget

    def setText(self, text):
        self._set_data_safe(text="" if text is None else str(text))

    def setX(self, X):
        self.X = float(X)
        self._sync_pos()

    def setY(self, Y):
        self.Y = float(Y)
        self._sync_pos()

    def setZ(self, Z):
        self.Z = float(Z)
        self._sync_pos()

    def setColor(self, color):
        self._set_data_safe(color=color)

    def setPosition(self, X, Y, Z):
        self.X = float(X) + 0.25
        self.Z = float(Z) + 0.6
        self.Y = float(Y)
        self._set_data_safe(
            pos=np.array([self.X, self.Y, self.Z], dtype=float),
            text='('+str(X)[:4]+', ' + str(Y)[:4]+', '+str(Z)[:4]+')',
        )

    def _sync_pos(self):
        if not all(math.isfinite(value) for value in (self.X, self.Y, self.Z)):
            self._paint_failed = True
            self.setVisible(False)
            log.warning("GLTextItem disabled after non-finite position")
            return
        self._set_data_safe(pos=np.array([self.X, self.Y, self.Z], dtype=float))

    def paint(self):
        if (GL_TEXT_DISABLED and not self._force_enabled) or self._paint_failed:
            return
        if self.text is None or len(str(self.text)) < 1:
            return

        try:
            gl.GLTextItem.paint(self)
        except Exception as exc:
            self._paint_failed = True
            try:
                self.setVisible(False)
            except Exception:
                pass
            log.warning("GLTextItem disabled after paint failure: %s", exc)
