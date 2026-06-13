"""PySide2.QtWidgets compatibility shim backed by PySide6.QtWidgets."""

from PySide6.QtWidgets import *  # noqa: F401,F403

from PySide6 import QtGui as _QtGui

_QTGUI_COMPAT_NAMES = [
    "QAction",
    "QActionGroup",
    "QShortcut",
]

for _name in _QTGUI_COMPAT_NAMES:
    if hasattr(_QtGui, _name):
        globals()[_name] = getattr(_QtGui, _name)

del _QtGui, _QTGUI_COMPAT_NAMES, _name
