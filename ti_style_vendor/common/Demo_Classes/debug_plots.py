# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\debug_plots.py
# General Library Imports
import time

# PyQt Imports
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import copy

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QGraphicsWidget, QPushButton, QLineEdit

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from Common_Tabs.plot_2d import Plot2D


# Local Imports
from Common_Tabs.plot_1d import Plot1D
from Common_Tabs.adc_plot import ADCPlotObject
from Common_Tabs.fft_plot import FFTPlotObject
from Common_Tabs.range_snr_plot import RangeSNRPlotObject

# Logger
import logging
log = logging.getLogger(__name__)

class DebugPlots():
    def __init__(self):
        # Basic setup for three debug plot panes
        self.ADCPlotObject = ADCPlotObject()
        self.FFTPlotObject = FFTPlotObject()
        self.rangeSNRPlotObject = RangeSNRPlotObject()
        self.tabs = None
        self.cumulativeCloud = None
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)

        # To keep track of plotting time
        self.plotStart = 0

        # Variables from .cfg file
        self.channelCfgRX = 0
        self.channelCfgTX = 0
        self.numADCSamples = 0


    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        demoGroupBox = self.initPlotControlPane()
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        # Add ADC Plot Pane
        self.ADCPlotPane = QGroupBox("ADC")
        self.ADCPlotPaneLayout = QVBoxLayout()
        self.ADCPlotPane.setLayout(self.ADCPlotPaneLayout)
        self.ADCPlotPaneLayout.addWidget(self.ADCPlotObject.adclayout)
        
        # Add FFT Plot Pane
        self.FFTPlotPane = QGroupBox("FFT")
        self.FFTPlotPaneLayout = QVBoxLayout()
        self.FFTPlotPane.setLayout(self.FFTPlotPaneLayout)
        self.FFTPlotPaneLayout.addWidget(self.FFTPlotObject.fftlayout)
        # Add Range SNR Plot Pane
        self.rangeSNRPlotPane = QGroupBox("rangeSNR")
        self.rangeSNRPlotPaneLayout = QVBoxLayout()
        self.rangeSNRPlotPane.setLayout(self.rangeSNRPlotPaneLayout)
        self.rangeSNRPlotPaneLayout.addWidget(self.rangeSNRPlotObject.rangeSNRlayout)
        
        # Add ADC Plot Tab
        self.adcdebugTab = QWidget()
        self.adcdebugTabLayout = QVBoxLayout()
        self.adcdebugTabLayout.addWidget(self.ADCPlotPane)
        self.adcdebugTab.setLayout(self.adcdebugTabLayout)

        # Add FFT Plot Tab
        self.fftdebugTab = QWidget()
        self.fftdebugTabLayout = QVBoxLayout()
        self.fftdebugTabLayout.addWidget(self.FFTPlotPane)
        self.fftdebugTab.setLayout(self.fftdebugTabLayout)
        
        # Add Range SNR Plot Tab
        self.rangeSNRdebugTab = QWidget()
        self.rangeSNRTabLayout = QVBoxLayout()
        self.rangeSNRTabLayout.addWidget(self.rangeSNRPlotPane)
        self.rangeSNRdebugTab.setLayout(self.rangeSNRTabLayout)
                
        # Add Tabs to screen
        demoTabs.addTab(self.adcdebugTab, 'ADC Debug')
        demoTabs.addTab(self.fftdebugTab, 'Range FFT Debug')
        demoTabs.addTab(self.rangeSNRdebugTab, 'Range SNR Debug')

        self.device = device
        self.tabs = demoTabs

        # Add pane to actual window
        demoTabs.setCurrentIndex(0)


    # Button to clear the point cloud in the range snr debug tab
    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        plotControlLayout = QFormLayout()

        self.clearDebugPlotsButton = QPushButton("Clear debug plots")
        self.clearDebugPlotsButton.clicked.connect(self.clearDebugPlots)
        self.velThreInput = QLineEdit("0")

        plotControlLayout.addRow(self.clearDebugPlotsButton)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox


    def updateGraph(self, outputDict):

        self.plotStart = int(round(time.time()*1000))

        self.cumulativeCloud = None

        # Figure out information needed for plots (number of samples, number of channels)
        outputDict["numADCSamples"] = self.numADCSamples
        RXBinString = "{0:b}".format(self.channelCfgRX)
        TXBinString = "{0:b}".format(self.channelCfgTX)
        numRX = RXBinString.count('1')
        numTX = TXBinString.count('1')
        outputDict['numVirtualChannels'] =  numRX * numTX

        # UpdateGraph function depending on which tab is open right now
        if (self.tabs.currentWidget() == self.adcdebugTab):
            self.ADCPlotObject.updateGraph(outputDict)
        elif (self.tabs.currentWidget() == self.fftdebugTab):
            self.FFTPlotObject.updateGraph(outputDict)
        elif (self.tabs.currentWidget() == self.rangeSNRdebugTab):
            self.rangeSNRPlotObject.updateGraph(outputDict)
        self.graphDone(outputDict)
        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

    # Required Function
    # Generally called by updateGraph
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def graphDone(self, outputDict):
        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

        if ('powerData' in outputDict):
            powerData = outputDict['powerData']
            self.updatePowerNumbers(powerData)

        plotTime = int(round(time.time()*1000)) - self.plotStart
        self.plotTimeDisplay.setText('Plot Time: ' + str(plotTime) + 'ms')
        self.plotComplete = 1


    def updatePowerNumbers(self, powerData):
        if powerData['power1v2'] == 65535:
            self.avgPower.setText('Average Power: N/A')
        else:
            powerStr = str((powerData['power1v2'] \
                + powerData['power1v2RF'] + powerData['power1v8'] + powerData['power3v3']) * 0.1)
            self.avgPower.setText('Average Power: ' + powerStr[:5] + ' mW')



    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.numPointsDisplay = QLabel('Points: 0')
        self.numTargetsDisplay = QLabel('Targets: 0')
        self.avgPower = QLabel('Average Power: 0 mw')
        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.numPointsDisplay)
        self.statsLayout.addWidget(self.numTargetsDisplay)
        self.statsLayout.addWidget(self.avgPower)
        statBox.setLayout(self.statsLayout)
        return statBox

    def clearDebugPlots(self):
        self.rangeSNRPlotObject.clearPlot()
    def parseChannelCfg(self, args):
        # e.g. parse channelCfg
        self.channelCfgRX = int(args[1])
        self.channelCfgTX = int(args[2])

    def parseChirpComnCfg(self,args):
        self.numADCSamples = int(args[4])