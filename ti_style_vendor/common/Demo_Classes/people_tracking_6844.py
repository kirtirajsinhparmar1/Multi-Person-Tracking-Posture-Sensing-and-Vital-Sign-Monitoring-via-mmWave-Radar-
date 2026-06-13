# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\people_tracking_6844.py
# General Library Imports
import copy
import string
import math
import numpy as np
import time


from PySide2.QtCore import QThread
from PySide2.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QComboBox, QCheckBox, QFormLayout
from Demo_Classes.people_tracking import PeopleTracking
from demo_defines import *
from graph_utilities import eulerRot
from gui_threads import updateQTTargetThread3D, COLOR_MODE_3DPT, COLOR_MODE_TRACK

import logging

log = logging.getLogger(__name__)

MAJOR_MOTION = 0
MINOR_MOTION = 1

class PeopleTracking6844(PeopleTracking):
    def __init__(self):
        PeopleTracking.__init__(self)
    
    def initStatsPane3DPT6844(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.numPointsMajorDisplay = QLabel('Major Motion Points: 0')
        self.numPointsMinorDisplay = QLabel('Minor Motion Points: 0')
        self.numTargetsDisplay = QLabel('Targets: 0')
        self.avgPower = QLabel('Average Power: 0 mw')
        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.numPointsMajorDisplay)
        self.statsLayout.addWidget(self.numPointsMinorDisplay)
        self.statsLayout.addWidget(self.numTargetsDisplay)
        self.statsLayout.addWidget(self.avgPower)
        statBox.setLayout(self.statsLayout)
        return statBox

    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        self.pointColorMode = QComboBox()
        self.pointColorMode.addItems([COLOR_MODE_3DPT, COLOR_MODE_TRACK])

        self.displayFallDet = QCheckBox('Detect Falls')
        self.snapTo2D = QCheckBox('Snap to 2D')
        self.displayFallDet.stateChanged.connect(self.fallDetDisplayChanged)
        self.displayFallDet.setEnabled(False)
        self.persistentFramesInput = QComboBox()
        self.persistentFramesInput.addItems([str(i) for i in range(1, 30 + 1)])
        self.persistentFramesInput.setCurrentIndex(self.numPersistentFrames - 1)
        self.persistentFramesInput.currentIndexChanged.connect(self.persistentFramesChanged)
        plotControlLayout = QFormLayout()
        plotControlLayout.addRow("Color Points By:",self.pointColorMode)
        plotControlLayout.addRow("Enable Fall Detection", self.displayFallDet)
        plotControlLayout.addRow("# of Persistent Frames",self.persistentFramesInput)
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)
        return plotControlBox

    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane3DPT6844()
        gridLayout.addWidget(statBox,2,0,1,1)

        demoGroupBox = self.initPlotControlPane()
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        fallDetectionOptionsBox = self.initFallDetectPane()
        gridLayout.addWidget(fallDetectionOptionsBox, 4,0,1,1)

        demoTabs.addTab(self.plot_3d, '3D Plot')
        demoTabs.addTab(self.rangePlot, 'Range Plot')
        self.device = device
        self.tabs = demoTabs
        
    def updatePointCloud3DPT6844(self, outputDict):
        combinedPointCloud = []

        if ('pointCloud' in outputDict and 'numDetectedPoints' in outputDict):
            pointCloud = outputDict['pointCloud']
            pointCloud = np.asarray(pointCloud)
            self.numPointsMajorDisplay.setText('Major Motion Points: '+ str(outputDict['numDetectedPoints']))

            # Rotate point cloud and tracks to account for elevation and azimuth tilt
            if (self.elev_tilt != 0 or self.az_tilt != 0):
                for i in range(outputDict['numDetectedPoints']):
                    rotX, rotY, rotZ = eulerRot (pointCloud[i,0], pointCloud[i,1], pointCloud[i,2], self.elev_tilt, self.az_tilt)
                    pointCloud[i,0] = rotX
                    pointCloud[i,1] = rotY
                    pointCloud[i,2] = rotZ
                    pointCloud[i,5] = MAJOR_MOTION


            # Shift points to account for sensor height
            if (self.sensorHeight != 0):
                pointCloud[:,2] = pointCloud[:,2] + self.sensorHeight

            if self.demo == "LPD":
                outputDict['pointCloud'] = self.filterPointCloud(outputDict['pointCloud'])
            
            # Add current point cloud to the cumulative cloud if it's not empty
            combinedPointCloud = pointCloud
            # print("Major Motion:\n", outputDict['pointCloud'])


        if ('pointCloudMinor' in outputDict and 'numDetectedPointsMinor' in outputDict):
            pointCloudMinor = outputDict['pointCloudMinor']
            pointCloudMinor = np.asarray(pointCloudMinor)
            self.numPointsMinorDisplay.setText('Minor Motion Points: '+ str(outputDict['numDetectedPointsMinor']))

            # Apply same transformations to minor point cloud
            if (self.elev_tilt != 0 or self.az_tilt != 0):
                for i in range(outputDict['numDetectedPointsMinor']):
                    rotX, rotY, rotZ = eulerRot (pointCloudMinor[i,0], pointCloudMinor[i,1], pointCloudMinor[i,2], self.elev_tilt, self.az_tilt)
                    pointCloudMinor[i,0] = rotX
                    pointCloudMinor[i,1] = rotY
                    pointCloudMinor[i,2] = rotZ
                    pointCloudMinor[i,5] = MINOR_MOTION

            if (self.sensorHeight != 0):
                pointCloudMinor[:,2] = pointCloudMinor[:,2] + self.sensorHeight

            if self.demo == "LPD":
                pointCloudMinor = self.filterPointCloud(pointCloudMinor)

            # Combine with existing point cloud
            if len(combinedPointCloud) > 0:
                combinedPointCloud = np.concatenate((combinedPointCloud, pointCloudMinor), axis=0)
            else:
                combinedPointCloud = pointCloudMinor

            # print("Minor Motion:\n", outputDict['pointCloudMinor'])

        # Single append statement for all cases
        self.previousClouds.append(combinedPointCloud)

        # If we have more point clouds than needed, stated by numPersistentFrames, delete the oldest ones 
        while(len(self.previousClouds) > self.numPersistentFrames):
            self.previousClouds.pop(0)
            
    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))
        self.updatePointCloud3DPT6844(outputDict)

        self.cumulativeCloud = None

        # Track indexes on 6843 are delayed a frame. So, delay showing the current points by 1 frame for 6843
        if ('frameNum' in outputDict and outputDict['frameNum'] > 1 and len(self.previousClouds[:-1]) > 0 and DEVICE_DEMO_DICT[self.device]["isxWRLx844"]):
            # For all the previous point clouds (except the most recent, whose tracks are being computed mid-frame)
            for frame in range(len(self.previousClouds[:-1])):
                # if it's not empty
                if(len(self.previousClouds[frame]) > 0):
                    # if it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.previousClouds[frame]
                    # if it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.previousClouds[frame]),axis=0)
        elif (len(self.previousClouds) > 0):
            # For all the previous point clouds, including the current frame's
            for frame in range(len(self.previousClouds[:])):
                # if it's not empty
                if(len(self.previousClouds[frame]) > 0):
                    # if it's the first member, assign it equal
                    if(self.cumulativeCloud is None):
                        self.cumulativeCloud = self.previousClouds[frame]
                    # if it's not the first member, concatinate it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.previousClouds[frame]),axis=0)

        # Tracks
        for cstr in self.coordStr:
            cstr.setVisible(False)

        # Plot
        if (self.tabs.currentWidget() == self.plot_3d):
            if ('trackData' in outputDict):
                tracks = outputDict['trackData']
                for i in range(outputDict['numDetectedTracks']):
                    rotX, rotY, rotZ = eulerRot(tracks[i,1], tracks[i,2], tracks[i,3], self.elev_tilt, self.az_tilt)
                    tracks[i,1] = rotX
                    tracks[i,2] = rotY
                    tracks[i,3] = rotZ
                    tracks[i,3] = tracks[i,3] + self.sensorHeight

                # If there are heights to display
                if ('heightData' in outputDict):
                    if (len(outputDict['heightData']) != len(outputDict['trackData'])):
                        log.warning("WARNING: number of heights does not match number of tracks")

                    # For each height heights for current tracks
                    for height in outputDict['heightData']:
                        # Find track with correct TID
                        for track in outputDict['trackData']:
                            # Found correct track
                            if (int(track[0]) == int(height[0])):
                                tid = int(height[0])
                                height_str = 'tid : ' + str(height[0]) + ', height : ' + str(round(height[1], 2)) + ' m'
                                # If this track was computed to have fallen, display it on the screen
                                if(self.displayFallDet.checkState() == 2):
                                    # Compute the fall detection results for each object
                                    fallDetectionDisplayResults = self.fallDetection.step(outputDict['heightData'], outputDict['trackData'])
                                    if (fallDetectionDisplayResults[tid] > 0): 
                                        height_str = height_str + " FALL DETECTED"
                                self.coordStr[tid].setText(height_str)
                                self.coordStr[tid].setX(track[1])
                                self.coordStr[tid].setY(track[2])
                                self.coordStr[tid].setZ(track[3])
                                self.coordStr[tid].setVisible(True)
                                break
            else:
                tracks = None
            if (self.plotComplete):
                self.plotStart = int(round(time.time()*1000))
                self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.scatter, self.plot_3d, 0, self.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=COLOR_MODE_3DPT, trackColorMap=self.trackColorMap)
                self.plotComplete = 0
                self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
                self.plot_3d_thread.start(priority=QThread.HighPriority)
        elif (self.tabs.currentWidget() == self.rangePlot):
            self.update1DGraph(outputDict)
            self.graphDone(outputDict)

        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))