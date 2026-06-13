# Compatibility shim for the vendored TI GL text helper.
# Original TI source path: tools\visualizers\Applications_Visualizer\common\gl_text.py

from importlib import util
from pathlib import Path


COMMON_GL_TEXT = Path(__file__).resolve().parents[1] / "gl_text.py"
spec = util.spec_from_file_location("_ti_style_common_gl_text", COMMON_GL_TEXT)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load {COMMON_GL_TEXT}")
module = util.module_from_spec(spec)
spec.loader.exec_module(module)

GLTextItem = module.GLTextItem
