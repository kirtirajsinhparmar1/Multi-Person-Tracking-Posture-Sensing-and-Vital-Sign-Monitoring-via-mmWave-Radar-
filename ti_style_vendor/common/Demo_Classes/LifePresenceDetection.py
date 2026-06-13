# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\LifePresenceDetection.py
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


###################################################################################################
# Life presence detection
# Parent class for CPD_V1 and is the main class for the latest LPD_CPD_V2
###################################################################################################

class LifePresenceDetection():
    def __init__(self, CPD_V1 = False):
        # 1D Plot for the probability of each cuboid
        self.plot_1d = Plot1D("LPD")
        self.probPlot = self.plot_1d.probPlot
        self.probLines = self.plot_1d.probLines
        self.probPlot.setTitle('Probability Plot of Adult in Seat')
        # 3D Plot for the point cloud
        self.plot3D = Plot3D("LPD")
        self.plot_3d  = self.plot3D.plot_3d
        self.evmBox = self.plot3D.evmBox

        #CPD Specific Initializations
        self.CPD = CPD_V1
        self.childOrAdult = None

        if self.CPD:
            self.plot_1dHeight = Plot1D("LPD")
            self.heightPlot = self.plot_1dHeight.probPlot
            self.heightProbLines = self.plot_1dHeight.probLines
            self.heightPlot.setTitle('Detected height of adult in seat')
            self.slidingScoreChild = []
            self.slidingHeight = []

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
        if self.CPD:
            self.childOrAdult = QCheckBox('Check to show child probability')
            plotControlLayout.addRow(self.childOrAdult)


        
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox

    def updateStatusPane(self,adult, child):
        if adult == 'g':
            self.childLabel.hide()
            self.beltLabel.show()
        elif child == 'b':
            self.childLabel.show()
            self.beltLabel.hide()
        else:
            self.childLabel.hide()
            self.beltLabel.hide()
        # for i in range(len(self.beltStatusList)):
        #     if self.beltStatusList[i] == 0:
        #         self.beltLabels[i].hide()
        #     else:
        #         self.beltLabels[i].show()
        # if self.CPD:
        #     for i in range(len(self.childStatusList)):
        #         if self.childStatusList[i] == 0:
        #             self.childLabels[i].hide()
        #         elif self.childStatusList[i] == 1:
        #             self.childLabels[i].show()


    def initStatusPane(self):
        self.statusBox = QGroupBox('Car Status')
        self.stausBoxGrid = QGridLayout()

        self.statusImgLabel = QLabel()
        carPixmap = QPixmap('images/car.png')
        carPixmap = carPixmap.scaledToWidth(350)
        self.statusImgLabel.setPixmap(carPixmap)

        # TODO: Plot the car image in the 3D plot?
        
        self.beltLabel = QLabel()
        beltPixmap = QPixmap('images/person.png')
        beltPixmap = beltPixmap.scaledToWidth(250)
        self.beltLabel.setPixmap(beltPixmap)
        self.beltLabel.setParent(self.statusImgLabel)

        self.childLabel = QLabel()
        childPixmap = QPixmap('images/baby-sitting.png')
        childPixmap = childPixmap.scaledToWidth(250)
        self.childLabel.setPixmap(childPixmap)
        self.childLabel.setParent(self.statusImgLabel)

        self.childLabel.move(52,70) # Driver Front Seat
        # self.childLabels[1].move(230,110) # Passenger Front Seat
        # self.childLabels[2].move(67,260)  # Driver Rear Seat
        # self.childLabels[3].move(153,260) # Back Middle Seat
        # self.childLabels[4].move(240,260) # Passenger Rear Seat

        self.beltLabel.move(52,100) # Driver Front Seat
        # self.beltLabels[1].move(230,115) # Passenger Front Seat
        # self.beltLabels[2].move(67,265)  # Driver Rear Seat
        # self.beltLabels[3].move(153,265) # Back Middle Seat
        # self.beltLabels[4].move(240,265) # Passenger Rear Seat

        self.updateStatusPane('n','n')
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
        if self.CPD:
            vbox.addWidget(self.heightPlot, stretch=1)

        hbox.addLayout(vbox, stretch=1)

        self.myTab.setLayout(hbox)

        if self.CPD:
            demoTabs.addTab(self.myTab, 'CPD')
        else:
            demoTabs.addTab(self.myTab, 'Life Presence Detection')
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
        highlightZones = [] # ADULT OR SBR
        ChildHighlightZones     = []
        removeHighlightZones = []
        adult = 0
        child = 0
        if('OccPredictions' in outputDict):
            
            # RESHAPE
            scoreOcc = []
            for i in range(0, len(outputDict['OccPredictions']), 5):
                scoreOcc.append(outputDict['OccPredictions'][i:i+5])
            scoreOcc = np.array(scoreOcc)
            

            
            for x in range(self.numZones):
                score = scoreOcc[:,x]

                if len(self.slidingScores[x]) >= 50:
                    self.slidingScores[x].pop(0)                
                self.slidingScores[x].append(scoreOcc[1][x])

                # if len(self.slidingScoreChild[x]) >= 50:
                #     self.slidingScoreChild[x].pop(0)
                # self.slidingScoreChild[x].append(scoreOcc[2][x])

                # HIGHLIGHT LOGIC
                zone = "Z"+str(x)
                if score[1] > 0.5: # Adult probability
                    adult = 'g'
                    # highlightZones.append(zone)
                    # self.beltStatusList[x] = 1
                    # self.childStatusList[x] = 0
                elif score[2] > 0.5 and self.CPD and adult == 0: # child probability
                    # for car decision this only highlights when its child only and no adult detected in the car
                    child = 'b'
                    # ChildHighlightZones.append(zone)
                    # self.childStatusList[x] = 1
                    # self.beltStatusList[x] = 0
                else:
                    # self.beltStatusList[x] = 0
                    # self.childStatusList[x] = 0
                    removeHighlightZones.append(zone)
                
            # if self.childOrAdult.isChecked(): # if checked then
            #     #outputDict['OccPredPlot'] = self.slidingScoreChild
            #     #self.probPlot.setTitle('Probability Plot of Child in Seat')
            #     pass
            # else:
            outputDict['OccPredPlot'] = self.slidingScores
            self.probPlot.setTitle('Probability Plot of Adult in Seat')

            
            self.plot_1d.updateOccPred(outputDict, 'SBR')
        
        # HIGHLIGHT LOGIC - PER CAR DECISION HERE
        for box in self.plot3D.boundaryBoxViz:
            if adult != None: #adult - override and plot all GREEN
                self.plot3D.changeBoundaryBoxColor(box, adult)
            elif child != None: #only child, so highlight BLUE
                self.plot3D.changeBoundaryBoxColor(box, child)
            else: #remove all colors
                self.plot3D.changeBoundaryBoxColor(box, 'w')

                

        if('occHeightRes' in outputDict and self.CPD): # only when CPD
            for i in range(self.numZones):
                if(len(self.slidingHeight[i]) >= 50):
                    self.slidingHeight[i].pop(0)
                self.slidingHeight[i].append(outputDict['occHeightRes'][i])
            
            outputDict['OccHeightPlot'] = self.slidingHeight
       
            self.plot_1dHeight.updateOccPred(outputDict, 'CPD')

        self.updateStatusPane(adult, child)


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
        self.plot3D.addBoundBox(boxID, xMin, xMax, yMin, yMax, zMin, zMax, self.seatColors[zoneIndex % len(self.seatColors)])  # 
            

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
            
            text = ('Seat_' + str(zoneIndex+1))
            X = ((xMin + xMax) / 2)
            Y = ((yMin + yMax) / 2)
            Z = ((zMin + zMax) / 2)
            classifierText = GLTextItem(X,Y,Z,text)
            classifierText.setVisible(True)
            classifierText.setGLViewWidget(self.plot_3d)
            bigFont = QFont("Helvetica", 25)
            classifierText.setFont(bigFont)
            self.plot_3d.addItem(classifierText)
            

            if self.CPD: #add height lines
                hlineItem = pg.PlotCurveItem(pen=pg.mkPen(width=3, color=self.seatColors[zoneIndex % len(self.seatColors)], name = "Zone " + str(zoneIndex)))
                hscatterItem = pg.ScatterPlotItem(pen=pg.mkPen(width=3, color=self.seatColors[zoneIndex % len(self.seatColors)], name = "Zone " + str(zoneIndex)), symbol=self.probSymbols[zoneIndex % len(self.probSymbols)], size=10)
                self.heightProbLines.append([hlineItem,hscatterItem])
                self.heightPlot.addItem(self.heightProbLines[self.numZones][0])
                self.heightPlot.addItem(self.heightProbLines[self.numZones][1])
                self.slidingHeight.append([])
                self.slidingScoreChild.append([])
            
            self.cuboidZones[zoneIndex] = [boxID]
            self.numZones += 1
            self.slidingScores.append([])

        self.tagTemporal.append([0]*self.tagTemporalFiltSize)

    def parseSensorPositionCfg(self, args):
        self.plot3D.parseSensorPosition(args, False) # false is for is_x843


    def removeAllBoundBoxes(self):
        self.plot3D.removeAllBoundBoxes()