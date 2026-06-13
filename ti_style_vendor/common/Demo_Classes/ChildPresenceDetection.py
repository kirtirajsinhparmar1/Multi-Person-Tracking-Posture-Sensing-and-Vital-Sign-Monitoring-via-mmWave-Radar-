# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\ChildPresenceDetection.py
# General Library Imports
import time

# PyQt Imports
from PySide2.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QWidget

# Local Imports
from Common_Tabs.plot_1d import Plot1D
from Demo_Classes.LifePresenceDetection import LifePresenceDetection

# Logger
import logging
log = logging.getLogger(__name__)


###################################################################################################
# Child Presence Detection
###################################################################################################

class ChildPresenceDetection():
    def __init__(self):
        # This demo utilizes SBR and builds on top of it
        # OLD CPD
        self.SBR = LifePresenceDetection(True)
        self.childOrAdult = self.SBR.childOrAdult

    # Required Function
    # Set up the GUI for this demo
    #
    # gridLayout:   QGridLayout() for whole window
    # demoTabs:     QTabWidget() for holding GUI tabs
    # device:       device name being used
    def setupGUI(self, gridLayout, demoTabs, device):
        # Inherit from SBR
        self.SBR.setupGUI(gridLayout, demoTabs, device)

    # Required Function if some statistics are to be displayed
    def initStatsPane(self):
        # Inherit from SBR
        return self.SBR.initStatsPane()

    # Required Function
    # Updates the plot, called after parsing each frames
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def updateGraph(self, outputDict):
        # Inherit from SBR
        self.SBR.updateGraph(outputDict)

    # Required Function
    # Generally called by updateGraph
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def graphDone(self, outputDict):
        self.SBR.graphDone(outputDict)

    def parseCuboidDef(self, args):
        # e.g. parse channelCfg
        self.SBR.parseCuboidDef(args)

    def parseSensorPositionCfg(self, args):
        # e.g. parse channelCfg
        self.SBR.parseSensorPositionCfg(args)