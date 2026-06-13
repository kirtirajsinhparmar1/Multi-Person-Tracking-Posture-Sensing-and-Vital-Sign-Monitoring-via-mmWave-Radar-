# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\smart_toilet.py
# General Library Imports
import time
import numpy as np
import math
from collections import deque

# Constants
COLOR_MODE_SNR = 'SNR'
COLOR_MODE_HEIGHT = 'Height'
COLOR_MODE_DOPPLER = 'Doppler'
COLOR_MODE_TRACK = 'Associated Track'

MAX_PERSISTENT_FRAMES = 30

# PyQt Imports
from PySide2.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget, QFrame, QComboBox, QCheckBox, QFormLayout
from PySide2.QtCore import Qt, QThread, QTimer
from PySide2.QtGui import QFont
from gui_threads import updateQTTargetThread3D
import pyqtgraph as pg


# Local Imports
from Common_Tabs.plot_3d import Plot3D
from Common_Tabs.false_alarm_test import FalseAlarm
from demo_defines import *
from graph_utilities import get_trackColors
import pyqtgraph.opengl as gl

# Logger
import logging
log = logging.getLogger(__name__)

class SmartToiletDemo():
    def __init__(self):
        # Init 3D plot
        self.plot_3d = Plot3D()
        self.ellipsoids = []
        mesh = gl.GLLinePlotItem()
        mesh.setVisible(False)
        self.plot_3d.plot_3d.addItem(mesh)
        self.ellipsoids.append(mesh)
        self.tabs = None
        self.numPoints = 0
        self.clusterLocs = None
        self.cumulativeCloud = None
        self.dataCom = None
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)
        self.maxTracks = int(5) # default to 5 tracks
        self.trackColorMap = get_trackColors(self.maxTracks)
        self.coordStr = []
        self.false_alarm = FalseAlarm()
        self.prevModeState = None
        self.prevCamState = 0
        self.totalUsers = 0
        self.prevXVal = 0.0
        self.x_str = ""
        self.y_str = ""
        self.r_str = ""
        self.t_str = ""

        # Create timers  used for gesture display and person detection hold.
        self.currentGesture = 0
        self.gestureResetTimer = QTimer()
        self.gestureResetTimer.setSingleShot(True)

        self.trackingResetTimer = QTimer()
        self.trackingResetTimer.setSingleShot(True)

        # To keep track of plotting time
        self.plotStart = 0

        # Define the initial state of 'Person Detected' output.
        self.personDetectedLabel = QLabel("Person Detected")
        self.personDetected = QLabel("False")
        self.personDetected.setStyleSheet("QLabel { background-color: red }")
        self.personDetected.setFrameShape(QFrame.Panel)
        self.personDetected.setAlignment(Qt.AlignCenter)
        self.personDetected.setFont(QFont('Arial', 12))
        self.personDetected.resize(2000,100)

        # Define initial state of 'Walking direction' output. Commented out as flag used to determine walking direction is not reliable.

        # self.personDirectionLabel = QLabel("Walking Direction")
        # self.personDirection = QLabel("None")
        # self.personDirection.setStyleSheet("QLabel { background-color: gray }")
        # self.personDirection.setFrameShape(QFrame.Panel)
        # self.personDirection.setAlignment(Qt.AlignCenter)
        # self.personDirection.setFont(QFont('Arial', 12))      

        # Define initial states for standing vs. sitting widget. Current appimage not able to determine standing vs sitting. Commenting out for now.

        # self.personPostureLabel = QLabel("Standing or Sitting")
        # self.personPosture = QLabel("None")
        # self.personPosture.setStyleSheet("QLabel { background-color: gray }")
        # self.personPosture.setFrameShape(QFrame.Panel)
        # self.personPosture.setAlignment(Qt.AlignCenter)
        # self.personPosture.setFont(QFont('Arial', 12))      

        # Define initial states for Distance output. 
        self.personDistanceLabel = QLabel("Distance [m]")
        self.personDistance = QLabel("0.0")
        self.personDistance.setStyleSheet("QLabel { background-color: gray }")
        self.personDistance.setFrameShape(QFrame.Panel)
        self.personDistance.setAlignment(Qt.AlignCenter)
        self.personDistance.setFont(QFont('Arial', 12))   

        # Denfine initial state of person counter widget. Commented out as flag used to determine total user count is not reliable.

        # self.personCounterLabel = QLabel("Total Users:")
        # self.personCounter = QLabel("0")
        # self.personCounter.setStyleSheet("QLabel { background-color: gray }")
        # self.personCounter.setFrameShape(QFrame.Panel)
        # self.personCounter.setAlignment(Qt.AlignCenter)
        # self.personCounter.setFont(QFont('Arial', 12)) 

        # Define the initial states of the widgets for the gesture recognition layout 
        self.toiletGestureLabel = QLabel("Hand Gesture - U2D / D2U")
        self.toiletGesture = QLabel("None")
        self.toiletGesture.setStyleSheet("QLabel { background-color: gray }")
        self.toiletGesture.setFrameShape(QFrame.Panel)
        self.toiletGesture.setAlignment(Qt.AlignCenter)
        self.toiletGesture.setFont(QFont('Arial', 14))   

        # Removes boundary boxes from the display
    def removeAllBoundBoxes(self):
        self.plot_3d.removeAllBoundBoxes()
                
    def persistentFramesChanged(self, index):
        self.plot_3d.numPersistentFrames = index + 1

    def setupGUI(self, gridLayout, demoTabs, device):
       
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        self.device = device
        self.tabs = demoTabs

        demoGroupBox = self.initPlotControlPane()
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        # Need this to link the snapTo2D to render the boxes right
        self.plot_3d.snapTo2D = self.snapTo2D

        # Create and define the layout for the 3D plot
        self.pointCloudPlotPane = QGroupBox("Radar Point Cloud Plot")
        self.pointCloudPlotPaneLayout = QVBoxLayout()
        self.pointCloudPlotPane.setLayout(self.pointCloudPlotPaneLayout)

        # Create and define the layout for the radar stats to be displayed
        self.toiletFeatures = QGroupBox("Smart Toilet Features")
        self.toiletFeaturesLayout = QVBoxLayout()
        self.toiletFeatures.setLayout(self.toiletFeaturesLayout)

        # Create and define the layout for the person tracking stats
        self.personTracking = QGroupBox("Person Tracking")
        self.personTrackingLayout = QGridLayout()
        self.personTracking.setLayout(self.personTrackingLayout)

        # Create and define the layout for the gesture recognition stats
        self.gestureDisplay = QGroupBox("Gesture Recognition")
        self.gestureDisplayLayout = QVBoxLayout()
        self.gestureDisplay.setLayout(self.gestureDisplayLayout)
       
        # Add 3D plot into the 'Toilet data' plot pane
        self.pointCloudPlotPaneLayout.addWidget(self.plot_3d.plot_3d)

        # Add person tracking QLabels into the person tracking grid layout
        self.personTrackingLayout.addWidget(self.personDetectedLabel, 0, 0)
        self.personTrackingLayout.addWidget(self.personDetected, 0, 1)
        self.personTrackingLayout.addWidget(self.personDistanceLabel, 1, 0)
        self.personTrackingLayout.addWidget(self.personDistance, 1, 1)

        # Commented out as flag used to determine walking direction is not reliable.
        # Commented out as flag used to determine total user count is not reliable.
        # Current appimage not able to determine standing vs sitting. Commenting out for now.

        # self.personTrackingLayout.addWidget(self.personDirectionLabel, 2, 0)
        # self.personTrackingLayout.addWidget(self.personDirection, 2, 1)
        # self.personTrackingLayout.addWidget(self.personCounterLabel, 3, 0)
        # self.personTrackingLayout.addWidget(self.personCounter, 3, 1)
        # self.personTrackingLayout.addWidget(self.personPostureLabel, 4, 0)
        # self.personTrackingLayout.addWidget(self.personPosture, 4, 1)

        # Add gesture recognition QLabels into the gesture recognition VBox layout
        self.gestureDisplayLayout.addWidget(self.toiletGestureLabel)
        self.gestureDisplayLayout.addWidget(self.toiletGesture)

        # This is the main widget in which the other widgets are contained
        self.mainPane = QWidget()
        self.mainPaneLayout = QHBoxLayout()

        # Adds the person tracking and gesture recognition displays to the 'Features' layout
        self.toiletFeaturesLayout.addWidget(self.personTracking)
        self.toiletFeaturesLayout.addWidget(self.gestureDisplay)

        self.mainPaneLayout.addWidget(self.pointCloudPlotPane, stretch=2.5)
        self.mainPaneLayout.addWidget(self.toiletFeatures, stretch=1)

        self.mainPane.setLayout(self.mainPaneLayout)

        # Adds the main layout to the actual window
        demoTabs.addTab(self.mainPane, 'Smart Toilet')

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

    # Required Function if some statistics are to be displayed
    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.avgPower = QLabel('Measured Power: Calculating...')
        self.numPointsDisplay = QLabel('Points: 0')
        self.numTargetsDisplay = QLabel('Targets: 0')
        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.numPointsDisplay)
        self.statsLayout.addWidget(self.numTargetsDisplay)
        self.statsLayout.addWidget(self.avgPower)
        statBox.setLayout(self.statsLayout)

        return statBox

    # Updates 3d plot with data from tlv 368. Tracks tlv 368 and 351 flags and updates person status boxes.
    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))
        self.plot_3d.updatePointCloud(outputDict)

        self.cumulativeCloud = None

        if('clusterLocs' in outputDict):
            self.clusterLocs = outputDict['clusterLocs']

        if('frameNum' in outputDict):
            self.frameNum = outputDict['frameNum']

        # Track indexes on 6843 are delayed a frame. So, delay showing the current points by 1 frame for 6843
        if ('frameNum' in outputDict and outputDict['frameNum'] > 1 and len(self.plot_3d.previousClouds[:-1]) > 0 and DEVICE_DEMO_DICT[self.device]["isxWRx843"]):
            # For all the previous point clouds (except the most recent, whose tracks are being computed mid-frame)
            for frame in range(len(self.plot_3d.previousClouds[:-1])):
                # If it's not empty
                if(len(self.plot_3d.previousClouds[frame]) > 0):
                    # If it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.plot_3d.previousClouds[frame]
                    # If it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.plot_3d.previousClouds[frame]),axis=0)
        elif (len(self.plot_3d.previousClouds) > 0):
            # For all the previous point clouds, including the current frame's
            for frame in range(len(self.plot_3d.previousClouds[:])):
                # If it's not empty
                if(len(self.plot_3d.previousClouds[frame]) > 0):
                    # If it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.plot_3d.previousClouds[frame]
                    # If it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.plot_3d.previousClouds[frame]),axis=0)
        # If we're snapping to 2D, set Z coordinate of each point to 0
        if(self.snapTo2D.isChecked() is True and self.cumulativeCloud is not None):
            self.cumulativeCloud[:,2] = 0

        # Check flags from TLV 368 to change display boxes.
        if (self.tabs.currentWidget() == self.mainPane):
            if ('DPCPointOutput' in outputDict):
                self.x = float(outputDict["DPCPointOutput"]["x"])
                self.y = float(outputDict["DPCPointOutput"]["y"])
                towardRadar = outputDict["DPCPointOutput"]["flag_towards_radar"]
                gestureRegion = outputDict["DPCPointOutput"]["flag_gesture_region"]
                trackingRegion = outputDict["DPCPointOutput"]["flag_tracking_region"]

                # Qlabel for standing vs. sitting. Current appimage not able to determine standing vs sitting. Commenting out for now.
                # Changes 'person detected' display box true and false. 

                # if (trackingRegion == True):
                #     self.personDetected.setText("True")
                #     self.personDetected.setStyleSheet("QLabel { background-color: green }")
                # else:
                #     self.personDetected.setText("False")
                #     self.personDetected.setStyleSheet("QLabel { background-color: red }")

                # Demo uses this to determine whether a person is detected in frame. X value only receives data when appimage goes into 'major motion processing'.

                # This is the current active version. Testing a new iteration below. Commening out while testing.
                # if (x != 0.0):
                #     self.personDetected.setText("True")
                #     self.personDetected.setStyleSheet("QLabel { background-color: green }")
                # else:
                #     self.personDetected.setText("False")
                #     self.personDetected.setStyleSheet("QLabel { background-color: red }") 
                
                if(self.x != 0.0):
                # if(trackingRegion == True):
                    if(self.trackingResetTimer.isActive()):
                        self.trackingResetTimer.stop()
                
                    self.personDetected.setText("True")
                    self.personDetected.setStyleSheet("QLabel { background-color: green }")

                    self.trackingResetTimer.start(1000)
                else:
                    if(self.trackingResetTimer.isActive()):
                        return
                    self.personDetected.setText("False")
                    self.personDetected.setStyleSheet("QLabel { background-color: red }")


                # Changes 'walking direction' display box towards/away from toilet.
                # Commening out, not getting great results on the 'Walking Direction' output using this logic.

                # if (towardRadar == True):
                #     self.personDirection.setText("Towards Toilet")
                #     self.personDirection.setStyleSheet("QLabel { background-color: green }")             
                # else:
                #     self.personDirection.setText("None")
                #     self.personDirection.setStyleSheet("QLabel { background-color: gray }")
                
                # Logic for iterating total person count.

                # if (x != 0.0 and self.prevXVal == 0.0):
                #     self.totalUsers += 1
                #     self.personCounter.setText(str(self.totalUsers))
                # self.prevXVal = x

            # Checks input from TLV 351 gesture tracking. 0 is no gesture, 1 is U to D, 2 is D to U.
            if ('gesture' in outputDict):
                # Define gesture flag.
                self.currentGesture = outputDict['gesture']

                # Check current status of flag and change QLabel for gesture recognition box accordingly.
                if (self.currentGesture in [1, 2]):
                    # If gesture is recognized, start a 3 second timer. This will hold the QLabel with the gesture recognized for 3 seconds (even though the TLV only shows gesture output for 1 frame).
                    if (self.gestureResetTimer.isActive()):
                        self.gestureResetTimer.stop()

                    if (self.currentGesture == 1):
                        self.toiletGesture.setText("Up to Down")
                        self.toiletGesture.setStyleSheet("QLabel { background-color: green }")

                    elif (self.currentGesture == 2):
                        self.toiletGesture.setText("Down to Up")
                        self.toiletGesture.setStyleSheet("QLabel { background-color: blue }")
                    
                    self.gestureResetTimer.start(3000)

                # If there is no gesture recognized check if the timer is active. If timer not active, move QLabel back to 'none'. 
                else:
                    if (self.gestureResetTimer.isActive()):
                        return
                    self.toiletGesture.setText("None")
                    self.toiletGesture.setStyleSheet("QLabel { background-color: gray }")  


        # Plot
        if (self.tabs.currentWidget() == self.mainPane):
            tracks = [[0] * 4]
            numTracks = 0
            if ('DPCPointOutput' in outputDict):
                self.radius = outputDict["DPCPointOutput"]["range"]
                self.angle = outputDict["DPCPointOutput"]["angle"]
                tracks[0][0] = 0
                if (self.x != 0.0):
                    tracks[0][1] = self.y
                    tracks[0][2] = self.x
                else:
                    tracks[0][1] = self.radius * math.sin(math.radians(self.angle))
                    tracks[0][2] = self.radius * math.cos(math.radians(self.angle))
                tracks[0][3] = 0
                numTracks = 1
            else:
                tracks = None
            if (self.plot_3d.plotComplete):
                self.plotStart = int(round(time.time()*1000))
                self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.plot_3d.scatter, self.plot_3d, numTracks, self.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=self.pointColorMode.currentText(), trackColorMap=self.trackColorMap, clusterLocs=self.clusterLocs)
                self.plot_3d.plotComplete = 0
                self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
                self.plot_3d_thread.start(priority=QThread.HighPriority)
                self.personDistance.setText(f"{tracks[0][2]:.{2}f}")
            else:
                log.error("Previous frame did not complete, omitting frame " + str(outputDict["frameNum"]))
        else:
            self.graphDone(outputDict)

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

    # TLV 368 not configured to send power data. Leaving this in incase this functionality is to be added in the future.
    def updatePowerNumbers(self, powerData):
        if powerData['power1v2'] == 65535:
            self.avgPower.setText('Average Power: N/A')
        else:
            powerStr = str((powerData['power1v2'] \
                + powerData['power1v2RF'] + powerData['power1v8'] + powerData['power3v3']) * 0.1)
            self.avgPower.setText('Average Power: ' + powerStr[:5] + ' mW')

    def parseBoundaryBox(self,args):
        self.plot_3d.parseBoundaryBox(args)

