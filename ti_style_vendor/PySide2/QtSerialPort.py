"""PySide2.QtSerialPort compatibility shim backed by PySide6.QtSerialPort."""

try:
    from PySide6.QtSerialPort import *  # noqa: F401,F403
except ImportError:
    pass
