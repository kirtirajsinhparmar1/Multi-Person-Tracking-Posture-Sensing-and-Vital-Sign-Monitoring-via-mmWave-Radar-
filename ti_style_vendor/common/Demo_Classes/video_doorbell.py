# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\video_doorbell.py
# General Library Imports
# PyQt Imports
# Local Imports
# Logger
# # Different methods to color the points 
COLOR_MODE_SNR = 'SNR'
COLOR_MODE_HEIGHT = 'Height'
COLOR_MODE_DOPPLER = 'Doppler'
COLOR_MODE_TRACK = 'Associated Track'

MAX_PERSISTENT_FRAMES = 30

from collections import deque
import numpy as np
import time
import string

from PySide2.QtCore import Qt, QThread
from PySide2.QtGui import QPixmap, QFont
import pyqtgraph.opengl as gl
import pyqtgraph as pg
from PySide2.QtWidgets import QSizePolicy, QHeaderView, QTableWidget,QTableWidgetItem, QPushButton, QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout

from Common_Tabs.plot_3d import Plot3D
from Common_Tabs.plot_1d import Plot1D
from Common_Tabs.power_consumption_report import PowerReport
from Common_Tabs.false_alarm_test import FalseAlarm
from Demo_Classes.Helper_Classes.fall_detection import *
from demo_defines import *
from graph_utilities import get_trackColors, eulerRot
from gl_text import GLTextItem

from gui_threads import updateQTTargetThread3D
import logging

log = logging.getLogger(__name__)


class VideoDoorbell():
    def __init__(self):
        self.plot_3d = Plot3D()
        self.power_report = PowerReport()
        self.false_alarm = FalseAlarm()
        self.tabs = None
        self.cumulativeCloud = None
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)
        self.maxTracks = int(5) # default to 5 tracks
        self.trackColorMap = get_trackColors(self.maxTracks)
        self.coordStr = []
        self.prevModeState = None
        self.prevCamState = 0
        self.numPoints = 0
        self.frameTime = 0
        self.clusterLocs = None
        self.x_str = ""
        self.y_str = ""
        self.r_str = ""
        self.t_str = ""
        self.lockMode1DetRange = 0
        self.lockMode2DetRange = 0
        self.lockMode3DetRange = 0

    # Not yet implemented, exports power consumption over a file
    def onExportPowerData(self):
        self.exportPowerData()

    # Create the detection distances table
    def initDetDistancesTable(self):
        # Set parameter names

        self.detRangeTable = QTableWidget(3, 5)
        self.firstPassDetStats = QTableWidgetItem('Mode 1 Detection Range :')
        self.secondPassDetStats = QTableWidgetItem('Mode 2 Detection Range :')
        self.thirdPassDetStats = QTableWidgetItem('Mode 3 Detection Range :')

        self.detRangeTableItem = QTableWidgetItem('Range (m)')
        self.detAngleTableItem = QTableWidgetItem('Angle (degrees)')
        self.detXTableItem = QTableWidgetItem('X Position (m)')
        self.detYTableItem = QTableWidgetItem('Y Position (m)')
        self.frameNumTableItem = QTableWidgetItem('Frame Num')


        self.detRangeTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detRangeTable.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detRangeTable.setVerticalHeaderItem(0, self.firstPassDetStats)
        self.detRangeTable.setVerticalHeaderItem(1, self.secondPassDetStats)
        self.detRangeTable.setVerticalHeaderItem(2, self.thirdPassDetStats)
        
        self.detRangeTable.setHorizontalHeaderItem(0, self.detRangeTableItem)
        self.detRangeTable.setHorizontalHeaderItem(1, self.detAngleTableItem)
        self.detRangeTable.setHorizontalHeaderItem(2, self.detXTableItem)
        self.detRangeTable.setHorizontalHeaderItem(3, self.detYTableItem)
        self.detRangeTable.setHorizontalHeaderItem(4, self.frameNumTableItem)

        self.detStatsPaneLayout.addWidget(self.detRangeTable)

    # Removes boundary boxes from the display
    def removeAllBoundBoxes(self):
        self.plot_3d.removeAllBoundBoxes()

    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        demoGroupBox = self.initPlotControlPane()
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        # Need this to link the snapTo2D to render the boxes right
        self.plot_3d.snapTo2D = self.snapTo2D

        self.device = device
        self.tabs = demoTabs

        modeSwitchBox = self.initModeSwitchPane()
        gridLayout.addWidget(modeSwitchBox,4,0,1,1)

        # Add all panes to the overall display
        self.detStatsPane = QGroupBox("Detection Stats")
        self.detStatsPaneLayout = QVBoxLayout()
        self.detStatsPane.setLayout(self.detStatsPaneLayout)
        self.initDetDistancesTable()

        self.pointCloudPlotPane = QGroupBox("Data Plot")
        self.pointCloudPlotPaneLayout = QVBoxLayout()
        self.pointCloudPlotPane.setLayout(self.pointCloudPlotPaneLayout)

        pointCloudPlotSizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        pointCloudPlotSizePolicy.setVerticalStretch(4)
        self.pointCloudPlotPane.setSizePolicy(pointCloudPlotSizePolicy)

        self.plot_3d.plot_3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.pointCloudPlotPaneLayout.addWidget(self.plot_3d.plot_3d)

        self.detDistanceTab = QWidget()
        self.detRangePaneLayout = QVBoxLayout()

        self.detRangePaneLayout.addWidget(self.pointCloudPlotPane)
        self.detRangePaneLayout.addWidget(self.detStatsPane)
        
        self.detDistanceTab.setLayout(self.detRangePaneLayout)

        demoTabs.addTab(self.detDistanceTab, 'Detection Range')
        demoTabs.addTab(self.power_report.powerReportTab, 'Power Consumption Report')
        demoTabs.addTab(self.false_alarm.falseAlarmTab, 'False Alarm Report')

    # Updates 3d Point cloud
    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))
        self.plot_3d.updatePointCloud(outputDict)

        self.cumulativeCloud = None

        if ('numDetectedPoints' in outputDict):
            numPoints = outputDict['numDetectedPoints']
        else:
            numPoints = 0

        if('clusterLocs' in outputDict):
            self.clusterLocs = outputDict['clusterLocs']

        if('frameNum' in outputDict):
            self.frameNum = outputDict['frameNum']

        # Track indexes on 6843 are delayed a frame. So, delay showing the current points by 1 frame for 6843
        if ('frameNum' in outputDict and outputDict['frameNum'] > 1 and len(self.plot_3d.previousClouds[:-1]) > 0 and DEVICE_DEMO_DICT[self.device]["isxWRx843"]):
            # For all the previous point clouds (except the most recent, whose tracks are being computed mid-frame)
            for frame in range(len(self.plot_3d.previousClouds[:-1])):
                # if it's not empty
                if(len(self.plot_3d.previousClouds[frame]) > 0):
                    # if it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.plot_3d.previousClouds[frame]
                    # if it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.plot_3d.previousClouds[frame]),axis=0)
        elif (len(self.plot_3d.previousClouds) > 0):
            # For all the previous point clouds, including the current frame's
            for frame in range(len(self.plot_3d.previousClouds[:])):
                # if it's not empty
                if(len(self.plot_3d.previousClouds[frame]) > 0):
                    # if it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.plot_3d.previousClouds[frame]
                    # if it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.plot_3d.previousClouds[frame]),axis=0)
        # If we're snapping to 2D, set Z coordinate of each point to 0
        if(self.snapTo2D.isChecked() is True and self.cumulativeCloud is not None):
            self.cumulativeCloud[:,2] = 0
        # Tracks
        for cstr in self.coordStr:
            cstr.setVisible(False)

        # Make a fake 3rd mode for the camera on for the logic to be easier later
        if('cameraOn' in outputDict and outputDict['cameraOn'] == 1 and self.prevModeState == 2):
            outputDict['modeState'] = 3

        self.false_alarm.run_false_alarm_state_machine(self.frameNum, self.prevModeState, outputDict, self.prevCamState)

        # Update boundary box colors based on results of Occupancy State Machine
        if ('enhancedPresenceDet' in outputDict):
            enhancedPresenceDet = outputDict['enhancedPresenceDet']
            for box in self.plot_3d.boundaryBoxViz:
                if ('mpdBoundary' in box['name']):
                    # Get index of the occupancy zone from the box name
                    boxIdx = int(box['name'].lstrip(string.ascii_letters))
                    # out of bounds
                    if (boxIdx >= len(enhancedPresenceDet)):
                        log.warning("Warning : Occupancy results for box that does not exist")
                    elif (enhancedPresenceDet[boxIdx] == 0):
                        self.plot_3d.changeBoundaryBoxColor(box, 'b') # Zone unoccupied
                    elif (enhancedPresenceDet[boxIdx] == 1):
                        self.plot_3d.changeBoundaryBoxColor(box, 'y') # Minor Motion Zone Occupancy 
                    elif (enhancedPresenceDet[boxIdx] == 2):
                        self.plot_3d.changeBoundaryBoxColor(box, 'r') # Major Motion Zone Occupancy
                    else:
                        log.error("Invalid result for Enhanced Presence Detection TLV")

 
        # If we're in second pass mode and any of the boxes show a detection. 
        # Needs to be before we change modes in the viz, else a detection in 1st pass mode will automatically go to camera ON
        if ('enhancedPresenceDet' in outputDict):
            if(self.modeSwitchLabel.text() == 'Second Pass Mode' and 2 in outputDict['enhancedPresenceDet']):
                self.modeSwitchLabel.setText('Camera On')
                self.modeSwitchLabel.setFont(QFont('Arial', 16))
                self.modeSwitchLabel.setStyleSheet("background-color: red; border: 1px solid black;")

        if("modeState" in outputDict):
            if(outputDict['modeState'] == 0): # First pass mode
                self.modeSwitchLabel.setText('First Pass Mode')
                self.modeSwitchLabel.setFont(QFont('Arial', 16))
                self.modeSwitchLabel.setStyleSheet("background-color: green; border: 1px solid black;") 
            elif(outputDict['modeState'] == 1): # Second Pass mode
                self.modeSwitchLabel.setText('Second Pass Mode')
                self.modeSwitchLabel.setFont(QFont('Arial', 16))
                self.modeSwitchLabel.setStyleSheet("background-color: lightgreen; border: 1px solid black;") 
            elif(outputDict['modeState'] == 2): # Third Pass mode
                self.modeSwitchLabel.setText('Third Pass Mode')
                self.modeSwitchLabel.setFont(QFont('Arial', 16))
                self.modeSwitchLabel.setStyleSheet("background-color: yellow; border: 1px solid black;")                 
            elif(outputDict['modeState'] == 3):
                self.modeSwitchLabel.setText('Camera ON')
                self.modeSwitchLabel.setFont(QFont('Arial', 16))
                self.modeSwitchLabel.setStyleSheet("background-color: #FF474C; border: 1px solid black;") 

        # Distance Detection Logic
        if("modeState" in outputDict and self.prevModeState is not None):
            # If you're transitioning from 1st pass to 2nd pass mode, note the distance
            if(outputDict['modeState'] == 1 and self.prevModeState == 0 and self.lockMode1DetRange == 0):

                self.createClusterStrings()

                self.detRangeTable.setItem(0, 0, QTableWidgetItem(self.r_str))
                self.detRangeTable.setItem(0, 1, QTableWidgetItem(self.t_str))
                self.detRangeTable.setItem(0, 2, QTableWidgetItem(self.x_str))
                self.detRangeTable.setItem(0, 3, QTableWidgetItem(self.y_str))
                self.detRangeTable.setItem(0, 4, QTableWidgetItem(str(self.frameNum)))

                # Lock the results until you click reset
                self.lockMode1DetRange = 1

            # If you're transitioning from 2nd pass to 3rd pass mode, note the distance
            elif(outputDict['modeState'] == 2 and self.prevModeState == 1 and self.lockMode2DetRange == 0):
                self.createClusterStrings()

                self.detRangeTable.setItem(1, 0, QTableWidgetItem(self.r_str))
                self.detRangeTable.setItem(1, 1, QTableWidgetItem(self.t_str))
                self.detRangeTable.setItem(1, 2, QTableWidgetItem(self.x_str))
                self.detRangeTable.setItem(1, 3, QTableWidgetItem(self.y_str))
                self.detRangeTable.setItem(1, 4, QTableWidgetItem(str(self.frameNum)))

                # Lock the results until you click reset
                self.lockMode2DetRange = 1
            # If you're transitioning from 3rd pass mode to camera on mode, note the distance
            elif(outputDict['modeState'] == 3 and self.prevModeState == 2 and self.lockMode3DetRange == 0):
                self.createClusterStrings()

                self.detRangeTable.setItem(2, 0, QTableWidgetItem(self.r_str))
                self.detRangeTable.setItem(2, 1, QTableWidgetItem(self.t_str))
                self.detRangeTable.setItem(2, 2, QTableWidgetItem(self.x_str))
                self.detRangeTable.setItem(2, 3, QTableWidgetItem(self.y_str))
                self.detRangeTable.setItem(2, 4, QTableWidgetItem(str(self.frameNum)))
                # Lock the results until you click reset
                self.lockMode3DetRange = 1

        # Transition state machine ahead to next state
        if('cameraOn' in outputDict):
            self.prevCamState = 1
        else:
            self.prevCamState = 0

        if("modeState" in outputDict):
            self.prevModeState = outputDict['modeState']


        # Plot
        if (self.tabs.currentWidget() == self.detDistanceTab):
            if ('trackData' in outputDict):
                tracks = outputDict['trackData']
                for i in range(outputDict['numDetectedTracks']):
                    rotX, rotY, rotZ = eulerRot(tracks[i,1], tracks[i,2], tracks[i,3], self.elev_tilt, self.az_tilt)
                    tracks[i,1] = rotX
                    tracks[i,2] = rotY
                    tracks[i,3] = rotZ
                    tracks[i,3] = tracks[i,3] + self.sensorHeight

            else:
                tracks = None
            if (self.plot_3d.plotComplete):
                self.plotStart = int(round(time.time()*1000))
                self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.plot_3d.scatter, self.plot_3d, 0, self.plot_3d.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=self.pointColorMode.currentText(), trackColorMap=self.trackColorMap, clusterLocs=self.clusterLocs)
                self.plot_3d.plotComplete = 0
                self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
                self.plot_3d_thread.start(priority=QThread.HighPriority)
            else:
                log.error("Previous frame did not complete, omitting frame " + str(outputDict["frameNum"]))
        else:
            # Still need the graphDone functions here
            self.graphDone(outputDict)

        updatedPowerNumbers = self.power_report.computeUpdatedPowerNumbers(outputDict)
        if self.power_report.timeStamp > 30:
            self.power_report.updatePowerStatsTable(numPoints)

    # Creates the strings for the cluster locations in the table at the bottom
    def createClusterStrings(self):
        # Make blank string for each list to be populated
        x_str = ""
        y_str = ""
        r_str = ""
        t_str = ""
        # For each cluster
        if self.clusterLocs is not None:
            for idx, cluster in enumerate(self.clusterLocs):
                x_str = x_str + ", " + str(cluster[0])
                y_str = y_str + ", " + str(cluster[1])
                r_str = r_str + ", " + str(round(np.sqrt(np.power(cluster[0],2) + np.power(cluster[1],2)),2))
                t_str = t_str + ", " + str(round(180 / 3.14159 * np.arctan(cluster[0] / cluster[1]), 2))

                # Don't display more than 5 clusters just for readability, shouldn't need this many for det distances
                if(idx > 5):
                    break
        else:
            print("Error : Transitioned modes without a cluster")
        
        # Remove first 2 characters ", " from each string
        self.x_str = x_str[2:]
        self.y_str = y_str[2:]
        self.r_str = r_str[2:]
        self.t_str = t_str[2:]

    def graphDone(self, outputDict):
        # Update all the side panels
        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

        if ('powerData' in outputDict):
            powerData = outputDict['powerData']
            self.updatePowerNumbers(powerData)

        if ('numDetectedPoints' in outputDict):
            self.numPointsDisplay.setText('Points: '+ str(outputDict['numDetectedPoints']))

        if ('numDetectedTracks' in outputDict):
            self.numTargetsDisplay.setText('Targets: '+ str(outputDict['numDetectedTracks']))

        plotTime = int(round(time.time()*1000)) - self.plotStart
        self.plotTimeDisplay.setText('Plot Time: ' + str(plotTime) + 'ms')
        self.plot_3d.plotComplete = 1

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
        self.avgPower = QLabel('Measured Power: Calculating...')
        self.uartPwrLabel = QFormLayout()
        # Feature not implemented yet
        # self.exportPowerCSV = QPushButton('Export Power Data as CSV')
        # self.exportPowerCSV.clicked.connect(self.onExportPowerData)
        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.numPointsDisplay)
        self.statsLayout.addWidget(self.numTargetsDisplay)
        self.statsLayout.addWidget(self.avgPower)
        self.statsLayout.addLayout(self.uartPwrLabel)
        # self.statsLayout.addWidget(self.exportPowerCSV)
        statBox.setLayout(self.statsLayout)
        return statBox
    
    def initModeSwitchPane(self):
        modeSwitchBox = QGroupBox('Mode Switch Status')
        self.modeSwitchLabel = QLabel('Two Pass Mode Disabled')
        self.modeSwitchLabel.setFont(QFont('Arial', 16))
        self.modeSwitchLabel.setStyleSheet("background-color: lightgrey; border: 1px solid black;") 
        self.clearDetectionStatsTable = QPushButton("Clear Detection Table")
        self.clearDetectionStatsTable.clicked.connect(self.onClearDetectionStatsTable)
        self.modeBoxLayout = QVBoxLayout()
        self.modeBoxLayout.addWidget(self.modeSwitchLabel)
        self.modeBoxLayout.addWidget(self.clearDetectionStatsTable)
        modeSwitchBox.setLayout(self.modeBoxLayout)
        return modeSwitchBox

    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        self.pointColorMode = QComboBox()
        self.pointColorMode.addItems([COLOR_MODE_SNR, COLOR_MODE_HEIGHT, COLOR_MODE_DOPPLER, COLOR_MODE_TRACK])

        self.displayFallDet = QCheckBox('Detect Falls')
        self.snapTo2D = QCheckBox('Snap to 2D')
        self.persistentFramesInput = QComboBox()
        self.persistentFramesInput.addItems([str(i) for i in range(1, MAX_PERSISTENT_FRAMES + 1)])
        self.persistentFramesInput.setCurrentIndex(self.plot_3d.numPersistentFrames - 1)
        self.persistentFramesInput.currentIndexChanged.connect(self.persistentFramesChanged)
        plotControlLayout = QFormLayout()
        plotControlLayout.addRow("Color Points By:",self.pointColorMode)
        plotControlLayout.addRow("# of Persistent Frames",self.persistentFramesInput)
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox

    def persistentFramesChanged(self, index):
        self.plot_3d.numPersistentFrames = index + 1

    def parseBoundaryBox(self,args):
        self.plot_3d.parseBoundaryBox(args)

    def parseTrackingCfg(self, args):
        self.maxTracks = int(args[4])
        self.updateNumTracksBuffer() # Update the max number of tracks based off the config file
        self.trackColorMap = get_trackColors(self.maxTracks)
        for m in range(self.maxTracks):
            # Add track gui object
            mesh = gl.GLLinePlotItem()
            mesh.setVisible(False)
            self.plot_3d.addItem(mesh)
            self.ellipsoids.append(mesh)
            # Add track coordinate string
            text = GLTextItem()
            text.setGLViewWidget(self.plot_3d)
            text.setVisible(False)
            self.plot_3d.addItem(text)
            self.coordStr.append(text)
            # Add track classifier label string
            classifierText = GLTextItem()
            classifierText.setGLViewWidget(self.plot_3d)
            classifierText.setVisible(False)
            self.plot_3d.addItem(classifierText)
            self.classifierStr.append(classifierText)
   
    def onClearDetectionStatsTable(self):
        self.detRangeTable.clearContents()
        self.lockMode1DetRange = 0
        self.lockMode2DetRange = 0
        self.lockMode3DetRange = 0

    def resetPowerNumbers(self):
        self.power_report.resetPowerNumbers()