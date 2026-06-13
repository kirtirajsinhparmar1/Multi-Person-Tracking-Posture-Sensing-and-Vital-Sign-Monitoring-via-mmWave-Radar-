"""PySide2.QtOpenGL compatibility shim backed by PySide6 OpenGL modules."""

try:
    from PySide6.QtOpenGL import *  # noqa: F401,F403
except ImportError:
    pass

try:
    from PySide6.QtOpenGLWidgets import *  # noqa: F401,F403
except ImportError:
    pass
