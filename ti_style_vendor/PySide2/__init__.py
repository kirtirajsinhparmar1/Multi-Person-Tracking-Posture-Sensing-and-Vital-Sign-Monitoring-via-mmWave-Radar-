"""PySide2 compatibility package backed by PySide6.

The vendored TI Industrial Visualizer imports PySide2 directly. Python 3.11
does not have usable PySide2 wheels, so this local package keeps those imports
working while loading Qt from PySide6.
"""

from PySide6 import __version__, __version_info__

from . import QtCore, QtGui, QtWidgets

try:
    from . import QtOpenGL
except ImportError:
    QtOpenGL = None

try:
    from . import QtSerialPort
except ImportError:
    QtSerialPort = None

__all__ = [
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtOpenGL",
    "QtSerialPort",
    "__version__",
    "__version_info__",
]
