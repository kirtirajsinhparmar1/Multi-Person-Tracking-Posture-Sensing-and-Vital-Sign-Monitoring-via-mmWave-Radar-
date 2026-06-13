# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\people_tracking.py
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
import os
import time
import string

from PySide2.QtCore import Qt, QThread
from PySide2.QtGui import QPixmap, QFont
import pyqtgraph.opengl as gl
import pyqtgraph as pg
from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView

from Common_Tabs.plot_3d import Plot3D
from Common_Tabs.plot_1d import Plot1D
from Demo_Classes.Helper_Classes.fall_detection import *
from demo_defines import *
from graph_utilities import get_trackColors, eulerRot
from gl_text import GLTextItem

from gui_threads import updateQTTargetThread3D

import logging

log = logging.getLogger(__name__)


def _pose_percent_text(confidence):
    try:
        percent = float(confidence) * 100.0
    except Exception:
        return '-'
    if not np.isfinite(percent):
        return '-'
    if abs(percent - round(percent)) < 0.05:
        return '{:.0f}%'.format(percent)
    return '{:.1f}%'.format(percent)


class DisabledGLTextItem:
    # TODO: Replace disabled GL text with a Qt 2D overlay label layer for PySide6.
    def setGLViewWidget(self, *_args, **_kwargs):
        pass

    def setVisible(self, *_args, **_kwargs):
        pass

    def setText(self, *_args, **_kwargs):
        pass

    def setX(self, *_args, **_kwargs):
        pass

    def setY(self, *_args, **_kwargs):
        pass

    def setZ(self, *_args, **_kwargs):
        pass

    def visible(self):
        return False


class PeopleTracking(Plot3D, Plot1D):
    def __init__(self):
        Plot3D.__init__(self)
        Plot1D.__init__(self)
        self.fallDetection = FallDetection()
        self.tabs = None
        self.cumulativeCloud = None
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)
        self.maxTracks = int(5) # default to 5 tracks
        self.frameTime = int(55) # default : 55 ms
        self.trackColorMap = get_trackColors(self.maxTracks)
        self.poseManager = None
        self.latestPoseResults = {}
        self.pose3dLabelsEnabled = False
        self.poseTable = None

    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        demoGroupBox = self.initPlotControlPane()
        gridLayout.addWidget(demoGroupBox,3,0,1,1)

        fallDetectionOptionsBox = self.initFallDetectPane()
        gridLayout.addWidget(fallDetectionOptionsBox, 4,0,1,1)

        poseBox = self.initPosePane()
        gridLayout.addWidget(poseBox, 5,0,1,1)

        demoTabs.addTab(self.plot_3d, '3D Plot')
        demoTabs.addTab(self.rangePlot, 'Range Plot')
        self.device = device
        self.tabs = demoTabs

    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))
        self.latestPoseResults = self.processPoseResults(outputDict)
        self.updatePosePanel(self.latestPoseResults)
        self.updatePointCloud(outputDict)

        self.cumulativeCloud = None

        # Track indexes on 6843 are delayed a frame. So, delay showing the current points by 1 frame for 6843
        if ('frameNum' in outputDict and outputDict['frameNum'] > 1 and len(self.previousClouds[:-1]) > 0 and DEVICE_DEMO_DICT[self.device]["isxWRx843"]):
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

        if ('numDetectedPoints' in outputDict):
            self.numPointsDisplay.setText('Points: '+ str(outputDict['numDetectedPoints']))
        if ('numDetectedTracks' in outputDict):
            self.numTargetsDisplay.setText('Targets: '+ str(outputDict['numDetectedTracks']))

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
                                if self.pose3dLabelsEnabled and tid in self.latestPoseResults:
                                    pose = self.latestPoseResults[tid]
                                    if pose.get("window_ready"):
                                        quality_mark = " *" if pose.get("quality", "OK") != "OK" else ""
                                        height_str = (
                                            height_str
                                            + " | "
                                            + str(pose.get("final_label", pose.get("smoothed_label", "")))
                                            + " "
                                            + _pose_percent_text(pose.get("final_confidence", 0.0))
                                            + quality_mark
                                        )
                                self.coordStr[tid].setText(height_str)
                                self.coordStr[tid].setX(track[1])
                                self.coordStr[tid].setY(track[2])
                                self.coordStr[tid].setZ(track[3])
                                self.coordStr[tid].setVisible(True)
                                break
                self.updatePose3DLabels(tracks, outputDict.get('heightData'))
            else:
                tracks = None
                self.updatePose3DLabels([], None)
            if (self.plotComplete):
                self.plotStart = int(round(time.time()*1000))
                self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.scatter, self.plot_3d, 0, self.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=self.pointColorMode.currentText(), trackColorMap=self.trackColorMap)
                self.plotComplete = 0
                self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
                self.plot_3d_thread.start(priority=QThread.HighPriority)
        elif (self.tabs.currentWidget() == self.rangePlot):
            self.updatePoseLabels([])
            self.update1DGraph(outputDict)
            self.graphDone(outputDict)

        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

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

    def setPoseManager(self, manager):
        self.poseManager = manager
        self.pose3dLabelsEnabled = bool(getattr(manager, "enable_3d_labels", False)) if manager is not None else False
        self.updatePosePanel({})
        if not self.pose3dLabelsEnabled:
            self.updatePoseLabels([])

    def processPoseResults(self, outputDict):
        if self.poseManager is None:
            return {}
        raw_output = {}
        if isinstance(outputDict, dict):
            for key, value in outputDict.items():
                if key in ("trackData", "pointCloud", "heightData"):
                    try:
                        raw_output[key] = np.array(value, copy=True)
                    except Exception:
                        raw_output[key] = value
                else:
                    raw_output[key] = value
        try:
            return self.poseManager.process_output_dict(raw_output)
        except Exception:
            log.exception("Pose manager failed to process frame")
            return {}

    def updatePose3DLabels(self, tracks, heightData):
        if not self.pose3dLabelsEnabled or self.poseManager is None:
            self.updatePoseLabels([])
            return
        try:
            label_records = self.poseManager.get_3d_label_records(
                track_data=tracks,
                height_data=heightData,
            )
            self.updatePoseLabels(label_records)
        except Exception:
            log.exception("Failed to update 3D pose labels")
            self.updatePoseLabels([])

    def initPosePane(self):
        poseBox = QGroupBox('Live Posture / Pose')
        layout = QVBoxLayout()
        self.poseStatus = QLabel('Pose model disabled')
        self.poseTable = QTableWidget(0, 8)
        self.poseTable.setHorizontalHeaderLabels([
            'TID',
            'Final',
            'PostureML',
            'Conf',
            'Motion',
            'Points',
            'Quality',
            'Window',
        ])
        self.poseTable.verticalHeader().setVisible(False)
        try:
            self.poseTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.poseTable.setSelectionMode(QAbstractItemView.NoSelection)
        except AttributeError:
            self.poseTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.poseTable.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.poseTable.setMinimumHeight(110)
        try:
            self.poseTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        except Exception:
            pass
        layout.addWidget(self.poseStatus)
        layout.addWidget(self.poseTable)
        poseBox.setLayout(layout)
        return poseBox

    def updatePosePanel(self, poseResults):
        if self.poseTable is None:
            return
        if self.poseManager is None:
            self.poseStatus.setText('Pose model disabled')
            self.poseTable.setRowCount(0)
            return
        if not poseResults:
            self.poseStatus.setText('Pose model enabled: waiting for tracks')
            self.poseTable.setRowCount(0)
            return

        tids = sorted(poseResults.keys())
        self.poseStatus.setText('Pose model enabled')
        self.poseTable.setRowCount(len(tids))
        for row, tid in enumerate(tids):
            pose = poseResults[tid]
            window_age = int(pose.get('window_age', 0))
            ready = bool(pose.get('window_ready', False))
            if ready:
                final_label = str(pose.get('final_label', pose.get('smoothed_label', '')))
                ml_label = str(pose.get('smoothed_label', ''))
                confidence = _pose_percent_text(pose.get('final_confidence', 0.0))
            else:
                final_label = 'WARMUP'
                ml_label = 'warmup {}/8'.format(window_age)
                confidence = '-'

            quality = str(pose.get('quality', 'OK'))
            if not quality:
                quality = 'OK'

            values = [
                str(tid),
                final_label,
                ml_label,
                confidence,
                str(pose.get('motion_state', '')),
                str(int(pose.get('num_points', 0))),
                quality,
                '{}/8'.format(window_age),
            ]
            for column, value in enumerate(values):
                self.poseTable.setItem(row, column, QTableWidgetItem(value))

    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        self.pointColorMode = QComboBox()
        self.pointColorMode.addItems([COLOR_MODE_SNR, COLOR_MODE_HEIGHT, COLOR_MODE_DOPPLER, COLOR_MODE_TRACK])

        self.displayFallDet = QCheckBox('Detect Falls')
        self.snapTo2D = QCheckBox('Snap to 2D')
        self.displayFallDet.stateChanged.connect(self.fallDetDisplayChanged)
        self.persistentFramesInput = QComboBox()
        self.persistentFramesInput.addItems([str(i) for i in range(1, MAX_PERSISTENT_FRAMES + 1)])
        self.persistentFramesInput.setCurrentIndex(self.numPersistentFrames - 1)
        self.persistentFramesInput.currentIndexChanged.connect(self.persistentFramesChanged)
        plotControlLayout = QFormLayout()
        plotControlLayout.addRow("Color Points By:",self.pointColorMode)
        plotControlLayout.addRow("Enable Fall Detection", self.displayFallDet)
        plotControlLayout.addRow("# of Persistent Frames",self.persistentFramesInput)
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox

    def persistentFramesChanged(self, index):
        self.numPersistentFrames = index + 1

    def fallDetDisplayChanged(self, state):
        if state:
            self.fallDetectionOptionsBox.setVisible(True)
        else:
            self.fallDetectionOptionsBox.setVisible(False)

    def updateFallDetectionSensitivity(self):
        self.fallDetection.setFallSensitivity(((self.fallDetSlider.value() / self.fallDetSlider.maximum()) * 0.4) + 0.4) # Range from 0.4 to 0.8

    def initFallDetectPane(self):
        self.fallDetectionOptionsBox = QGroupBox('Fall Detection Sensitivity')
        self.fallDetLayout = QGridLayout()
        self.fallDetSlider = FallDetectionSliderClass(Qt.Horizontal)
        self.fallDetSlider.setTracking(True)
        self.fallDetSlider.setTickPosition(QSlider.TicksBothSides)
        self.fallDetSlider.setTickInterval(10)
        self.fallDetSlider.setRange(0, 100)
        self.fallDetSlider.setSliderPosition(50)
        self.fallDetSlider.valueChanged.connect(self.updateFallDetectionSensitivity)
        self.lessSensitiveLabel = QLabel("Less Sensitive")
        self.fallDetLayout.addWidget(self.lessSensitiveLabel,0,0,1,1)
        self.moreSensitiveLabel = QLabel("More Sensitive")
        self.fallDetLayout.addWidget(self.moreSensitiveLabel,0,10,1,1)
        self.fallDetLayout.addWidget(self.fallDetSlider,1,0,1,11)
        self.fallDetectionOptionsBox.setLayout(self.fallDetLayout)
        if(self.displayFallDet.checkState() == 2):
            self.fallDetectionOptionsBox.setVisible(True)
        else:
            self.fallDetectionOptionsBox.setVisible(False)

        return self.fallDetectionOptionsBox

    def parseTrackingCfg(self, args):
        self.maxTracks = int(args[4])
        # Parse frameTime from trackingCfg only when CLI format with 7 params is used
        if len(args) == 8:
            self.frameTime = int(args[7])
        else:
            self.frameTime = None
        self.updateNumTracksBuffer() # Update the max number of tracks based off the config file
        self.trackColorMap = get_trackColors(self.maxTracks)
        gl_text_enabled = os.environ.get("TI_STYLE_DISABLE_GL_TEXT") != "1"
        for m in range(self.maxTracks):
            # Add track gui object
            mesh = gl.GLLinePlotItem()
            mesh.setVisible(False)
            self.plot_3d.addItem(mesh)
            self.ellipsoids.append(mesh)
            # Add track coordinate string
            if gl_text_enabled:
                text = GLTextItem()
                text.setGLViewWidget(self.plot_3d)
                text.setVisible(False)
                self.plot_3d.addItem(text)
            else:
                text = DisabledGLTextItem()
            self.coordStr.append(text)
            # Add track classifier label string
            if gl_text_enabled:
                classifierText = GLTextItem()
                classifierText.setGLViewWidget(self.plot_3d)
                classifierText.setVisible(False)
                self.plot_3d.addItem(classifierText)
            else:
                classifierText = DisabledGLTextItem()
            self.classifierStr.append(classifierText)

    def updateNumTracksBuffer(self):
        # Update max number of tracks and frame period for Fall Detection
        if self.frameTime is not None:
            self.fallDetection = FallDetection(self.maxTracks, self.frameTime)
        else:
            self.fallDetection = FallDetection(self.maxTracks)
