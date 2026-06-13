# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\SeatBeltReminder.py
# General Library Imports
import time

# PyQt Imports
from PySide2.QtWidgets import QGridLayout, QGroupBox, QVBoxLayout, QLabel, QWidget, QCheckBox,QFormLayout, QHBoxLayout
from PySide2.QtGui import QPixmap, QFont
from PySide2.QtCore import Qt
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from gl_text import GLTextItem
from pyqtgraph.opengl import GLImageItem
from pyqtgraph.opengl import GLGraphicsItem

import numpy as np

# Local Imports
from Common_Tabs.plot_1d import Plot1D
from Common_Tabs.plot_3d import Plot3D
from graph_utilities import eulerRot


# Logger
import logging
log = logging.getLogger(__name__)


class SeatBeltReminder():
    def __init__(self):
        # 1D Plot for the probability of each cuboid
        self.plot_1d = Plot1D("LPD")
        self.probPlot = self.plot_1d.probPlot
        self.probLines = self.plot_1d.probLines
        self.probPlot.setTitle('Probability Plot of Adult in Seat')
        # 3D Plot for the point cloud
        self.plot3D = Plot3D("LPD")
        self.plot_3d  = self.plot3D.plot_3d
        self.evmBox = self.plot3D.evmBox


        # Demo Specific Initializations
        self.seatColors = ['r', 'g', 'b', 'c', 'y']
        self.probSymbols = ['o','s','t','d','+','star']# list of symbols to represent the probability of each cuboid
        self.cuboidZones = {} # zoneID = [cuboidID]
        self.numZones = 0
        self.cumulativeCloud = None

        self.driver = False
        
        
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)

        #classifierTemporalFilter inits
        self.tagTemporalFiltSize = 20
        self.minNumOccupancyHits = 5
        self.tagTemporal = [] # initialized through the parseCuboidDef function
        self.score = []

        #bounds inits
        self.xMax = float('-inf')
        self.xMin = float('inf')
        self.yMax = float('-inf')
        self.yMin = float('inf')
        self.zMax = float('-inf')
        self.zMin = float('inf')

        #probability inits
        self.slidingScores = []

        # To keep track of plotting time
        self.plotStart = 0

        # Variables from .cfg file (not required)
        self.channelCfgRX = 0
        self.channelCfgTX = 0

        

    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        self.snapTo2D = QCheckBox('Snap to 2D')
        plotControlLayout = QFormLayout()
        
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox

    def updateStatusPane(self):
        for i in range(len(self.beltStatusList)):
            if self.beltStatusList[i] == 0:
                self.beltLabels[i].hide()
            else:
                self.beltLabels[i].show()

    def initStatusPane(self):
        self.statusBox = QGroupBox('Car Status')
        self.stausBoxGrid = QGridLayout()

        self.statusImgLabel = QLabel()
        carPixmap = QPixmap('images/car.png')
        carPixmap = carPixmap.scaledToWidth(350)
        self.statusImgLabel.setPixmap(carPixmap)

        self.beltLabels = []
        self.beltStatusList = [0,0,0,0,0] 

        # TODO: Plot the car image in the 3D plot?
        
        for i in range(5):
            beltLabel = QLabel()
            beltPixmap = QPixmap('images/fasten-seat-belt.png')
            beltPixmap = beltPixmap.scaledToWidth(50)
            beltLabel.setPixmap(beltPixmap)
            beltLabel.setParent(self.statusImgLabel)
            self.beltLabels.append(beltLabel)

        self.beltLabels[0].move(75,115) # Driver Front Seat
        self.beltLabels[1].move(230,115) # Passenger Front Seat
        self.beltLabels[2].move(67,265)  # Driver Rear Seat
        self.beltLabels[3].move(153,265) # Back Middle Seat
        self.beltLabels[4].move(240,265) # Passenger Rear Seat

        self.updateStatusPane()
        self.stausBoxGrid.addWidget(self.statusImgLabel, 0, 0, 1, 1)
        self.statusBox.setLayout(self.stausBoxGrid)

        return self.statusBox

    # Required Function
    # Set up the GUI for this demo
    #
    # gridLayout:   QGridLayout() for whole window
    # demoTabs:     QTabWidget() for holding GUI tabs
    # device:       device name being used
    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)
        self.device = device
        
        demoGroupBox = self.initPlotControlPane()
        self.plot3D.snapTo2D = self.snapTo2D
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        statusGroupBox = self.initStatusPane()
        gridLayout.addWidget(statusGroupBox, 4, 0, 1, 1)


        # Create a pane for our demo
        self.myTab = QWidget()
        hbox = QHBoxLayout()
        vbox = QVBoxLayout()

        hbox.addWidget(self.plot_3d, stretch=1)

        vbox.addWidget(self.probPlot, stretch=1)

        hbox.addLayout(vbox, stretch=1)

        self.myTab.setLayout(hbox)

        demoTabs.addTab(self.myTab, 'Seat Belt Reminder')
        demoTabs.setCurrentIndex(0)

        #self.tabs = demoTabs

    # Required Function if some statistics are to be displayed
    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: -')
        self.plotTimeDisplay = QLabel('Plot Time: - ms')
        self.ARMprocTimeData = QLabel('ARM Processing Time: - ms')
        self.DSPprocTimeData = QLabel('DSP Processing Time: - ms')
        self.UARTTransmitTime = QLabel('UART Transmit Time: - ms')
        self.MeanPowerDisplay = QLabel('Average Power: - mW')
        self.statsLayout = QVBoxLayout()
        
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.ARMprocTimeData)
        self.statsLayout.addWidget(self.DSPprocTimeData)
        self.statsLayout.addWidget(self.UARTTransmitTime)
        self.statsLayout.addWidget(self.MeanPowerDisplay)
        statBox.setLayout(self.statsLayout)

        return statBox

    # Required Function
    # Updates the plot, called after parsing each frame
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def updateGraph(self, outputDict):
        # Update start time
        self.plotStart = int(round(time.time()*1000))
        self.plot3D.updatePointCloud(outputDict)

        # Plot the predictions scatter / line plot and highlight boxes
        highlightZones = [] # SBR
        removeHighlightZones = []
        if('OccPredictions' in outputDict):

            # RESHAPE
            scoreOcc = [] #CLEAR
            for i in range(0, len(outputDict['OccPredictions']), 2):
                scoreOcc.append(outputDict['OccPredictions'][i:i+2])
            for x in range(self.numZones):
                if len(self.slidingScores[x]) >= 50:
                    self.slidingScores[x].pop(0)
                    #print("popping oldest element")                    
                self.slidingScores[x].append(scoreOcc[x][1])

                # TAG which boxes to highlight
                zone = "Z"+str(x)
                if scoreOcc[x][1] > 0.5: 
                    #highlight
                    highlightZones.append(zone)
                    self.beltStatusList[x] = 1
                else:
                    #remove highlight
                    removeHighlightZones.append(zone)
                    self.beltStatusList[x] = 0

            outputDict['OccPredPlot'] = self.slidingScores

        
        self.plot_1d.updateOccPred(outputDict, 'SBR')
        
        # HIGHLIGHT LOGIC
        for box in self.plot3D.boundaryBoxViz:
            if box['name'][0:2] in highlightZones:
                # ADULT 
                self.plot3D.changeBoundaryBoxBold(box, True, False)
            elif box['name'][0:2] in removeHighlightZones:
                # REMOVE
                self.plot3D.changeBoundaryBoxBold(box,False, False)
            else:
                # REMOVE
                self.plot3D.changeBoundaryBoxBold(box,False, False)
                

        self.updateStatusPane()


        # CONVERT Point cloud to tuples for set data
        self.cumulativeCloud = None
        if (len(self.plot3D.previousClouds) > 0):
            # For all the previous point clouds, including the current frame's
            for frame in range(len(self.plot3D.previousClouds[:])):
                # if it's not empty
                if(len(self.plot3D.previousClouds[frame]) > 0):
                    
                    # if it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        
                        self.cumulativeCloud = self.plot3D.previousClouds[frame]

                    # if it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.plot3D.previousClouds[frame]),axis=0)
        
        # If we're snapping to 2D, set Z coordinate of each point to 0
        if(self.snapTo2D.isChecked() is True and self.cumulativeCloud is not None):
            self.cumulativeCloud[:,2] = 0
        #if not self.cumulativeCloud.any():
        self.plot3D.scatter.setData(pos=self.cumulativeCloud[:, 0:3])
        self.graphDone(outputDict)

            
    # Required Function
    # Generally called by updateGraph
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def graphDone(self, outputDict):
        plotTime = int(round(time.time()*1000)) - self.plotStart
        self.plotTimeDisplay.setText('Plot Time: ' + str(plotTime) + 'ms')
        self.plotComplete = 1


        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))
        
        if ('ARMprocTimeData' in outputDict):
            self.ARMprocTimeData.setText('ARM Processing Time: ' + str(outputDict['ARMprocTimeData'])+ 'ms')
        
        if ('DSPprocTimeData' in outputDict):
            self.DSPprocTimeData.setText('DSP Processing Time: ' + str(outputDict['DSPprocTimeData'])+ 'ms')

        if ('UARTTransmitTime' in outputDict):
            self.UARTTransmitTime.setText('UART Transmit Time: ' + str(outputDict['UARTTransmitTime'])+ 'ms')

        if ('MeanPowerDisplay' in outputDict):
            self.MeanPowerDisplay.setText('Average Power: ' + str(round(outputDict['MeanPowerDisplay'],2))+ ' mW')
    
    
    # Optional - gui_core.py parseCfg() for more details
    # Parse a specific CLI command to be used in the demo
    #
    # args:         list of each portion of CLI command (command name is args[0])
    def parseChannelCfg(self, args):
        # e.g. parse channelCfg
        self.channelCfgRX = int(args[1])
        self.channelCfgTX = int(args[2])

    def parseCuboidDef(self, args):
        
        # Zone Definitions parsing
        zoneIndex = int(args[1])  # index of zone - 5 in default 
        cuboidIndex = int(args[2]) # index of cuboid - 3 per zones
        xMin = float(args[3])
        xMax = float(args[4])
        yMin = float(args[5])
        yMax = float(args[6])
        zMin = float(args[7])
        zMax = float(args[8])

        self.xMin = min(self.xMin, xMin)
        self.xMax = max(self.xMax, xMax)
        self.yMin = min(self.yMin, yMin)
        self.yMax = max(self.yMax, yMax)
        self.zMin = min(self.zMin, zMin)
        self.zMax = max(self.zMax, zMax)

        # Zone Definitions - creating the objects
        boxID = "Z" + str(zoneIndex) + "C" + str(cuboidIndex)
        self.plot3D.addBoundBox(boxID, xMin, xMax, yMin, yMax, zMin, zMax, self.seatColors[zoneIndex % len(self.seatColors)])
            

        if zoneIndex in self.cuboidZones:
            # adding to old zone
            self.cuboidZones[zoneIndex].append(boxID)
        else: 
            # this is a new zone
            # Probability definitions
            scatterItem = pg.ScatterPlotItem(pen=pg.mkPen(width=3, color=self.seatColors[zoneIndex % len(self.seatColors)], name = "Zone_" + str(zoneIndex)), symbol=self.probSymbols[zoneIndex % len(self.probSymbols)], size=10)
            lineItem = pg.PlotCurveItem(pen=pg.mkPen(width=3, color=self.seatColors[zoneIndex % len(self.seatColors)], name = "Zone " + str(zoneIndex)))
            self.probLines.append([lineItem,scatterItem])
            self.probPlot.addItem(lineItem)
            
        
            # Add track classifier label string
            classifierText = GLTextItem()
            classifierText.setGLViewWidget(self.plot_3d)
            classifierText.setVisible(True)
            classifierText.setText('Seat_' + str(zoneIndex+1))
            classifierText.setX((xMin + xMax) / 2)
            classifierText.setY((yMin + yMax) / 2)
            classifierText.setZ((zMin + zMax) / 2)
            # TODO increase font size to make it more visible
            #classifierText.setFont(QFont("Arial", pointSize=15))
            self.plot_3d.addItem(classifierText)
            
            self.cuboidZones[zoneIndex] = [boxID]
            self.numZones += 1
            self.slidingScores.append([])

        self.tagTemporal.append([0]*self.tagTemporalFiltSize)

    def parseSensorPositionCfg(self, args):
        self.plot3D.parseSensorPosition(args, False) # false is for is_x843


    def removeAllBoundBoxes(self):
        self.plot3D.removeAllBoundBoxes()