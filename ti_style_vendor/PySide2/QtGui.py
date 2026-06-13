"""PySide2.QtGui compatibility shim backed by PySide6.

Qt6 moved widget classes out of QtGui. Some older TI files still reference
QtGui.QMessageBox or similar Qt5-era names, so expose common QtWidgets classes
here as compatibility aliases.
"""

from PySide6.QtGui import *  # noqa: F401,F403

from PySide6 import QtWidgets as _QtWidgets

_WIDGET_COMPAT_NAMES = [
    "QApplication",
    "QCheckBox",
    "QComboBox",
    "QDialog",
    "QFileDialog",
    "QFrame",
    "QFormLayout",
    "QGraphicsWidget",
    "QGridLayout",
    "QGroupBox",
    "QHBoxLayout",
    "QHeaderView",
    "QLabel",
    "QLineEdit",
    "QMainWindow",
    "QMessageBox",
    "QPushButton",
    "QSizePolicy",
    "QSlider",
    "QTabWidget",
    "QTableWidget",
    "QTableWidgetItem",
    "QVBoxLayout",
    "QWidget",
]

for _name in _WIDGET_COMPAT_NAMES:
    if hasattr(_QtWidgets, _name):
        globals()[_name] = getattr(_QtWidgets, _name)

del _QtWidgets, _WIDGET_COMPAT_NAMES, _name
