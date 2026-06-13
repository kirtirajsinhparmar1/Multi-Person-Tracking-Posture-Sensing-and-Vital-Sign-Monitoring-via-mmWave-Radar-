# Vendored from: tools\visualizers\Applications_Visualizer\Industrial_Visualizer\gui_main.py
import sys
import os

# add common folder to path
#sys.path.insert(1, os.path.abspath(os.getcwd()) + "\\common") # Uncomment for debug in VSCode or running from Applications_Visualizer dir
sys.path.insert(1, '../common')

# PySide2 Imports
from PySide2.QtCore import Qt
from PySide2.QtWidgets import QApplication
from PySide2.QtGui import QPalette, QColor

# Window Class
from gui_core import Window

# Demo List
from demo_defines import *

# Logging (possible levels: DEBUG, INFO, WARNING, ERROR, CRITICAL)
import logging

# Uncomment this line for logging with timestamps
# logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S', level=logging.INFO)

logging.basicConfig(format='%(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

if __name__ == '__main__':
        for key in DEVICE_DEMO_DICT.keys():
                DEVICE_DEMO_DICT[key]["demos"] = [x for x in DEVICE_DEMO_DICT[key]["demos"] if x in BUSINESS_DEMOS["Industrial"]]

        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        app = QApplication(sys.argv)

        if (len(sys.argv) >= 2 and sys.argv[1] == "dark"):
                # Force the style to be the same on all OSs:
                app.setStyle("Fusion")

                # Now use a palette to switch to dark colors:
                palette = QPalette()
                palette.setColor(QPalette.Window, QColor(53, 53, 53))
                palette.setColor(QPalette.WindowText, Qt.white)
                palette.setColor(QPalette.Base, QColor(25, 25, 25))
                palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
                palette.setColor(QPalette.ToolTipBase, Qt.black)
                palette.setColor(QPalette.ToolTipText, Qt.white)
                palette.setColor(QPalette.Text, Qt.white)
                palette.setColor(QPalette.Button, QColor(53, 53, 53))
                palette.setColor(QPalette.ButtonText, Qt.white)
                palette.setColor(QPalette.BrightText, Qt.red)
                palette.setColor(QPalette.Link, QColor(42, 130, 218))
                palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
                palette.setColor(QPalette.HighlightedText, Qt.black)
                app.setPalette(palette)

        screen = app.primaryScreen()
        size = screen.size()
        main = Window(size=size, title="Industrial Visualizer")
        main.show()
        sys.exit(app.exec_())