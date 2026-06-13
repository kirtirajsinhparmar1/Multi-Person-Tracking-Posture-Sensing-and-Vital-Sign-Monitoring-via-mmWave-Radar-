# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\point_cloud_classification.py
COLOR_MODE_SNR = 'SNR'
COLOR_MODE_HEIGHT = 'Height'
COLOR_MODE_DOPPLER = 'Doppler'
COLOR_MODE_TRACK = 'Associated Track'

MAX_PERSISTENT_FRAMES = 30

# General Library Imports
from collections import deque
import time
import numpy as np

# Local Imports
from Common_Tabs.plot_3d import Plot3D
from graph_utilities import get_trackColors
from gui_threads import updateQTTargetThread3D
from demo_defines import *

# PyQt Imports
from PySide2.QtCore import Qt, QThread
from PySide2.QtGui import QPixmap, QFont
import pyqtgraph as pg
from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QSizePolicy, QComboBox, QCheckBox, QFormLayout

# Local Imports
from graph_utilities import get_trackColors, eulerRot
from gl_text import GLTextItem

# Logger
import logging

log = logging.getLogger(__name__)

class PointCloudClassification(Plot3D):
    def __init__(self):
        Plot3D.__init__(self)
        self.tabs = None
        self.cumulativeCloud = None
        self.colorGradient = pg.GradientWidget(orientation='right')
        self.colorGradient.restoreState({'ticks': [ (1, (255, 0, 0, 255)), (0, (131, 238, 255, 255))], 'mode': 'hsv'})
        self.colorGradient.setVisible(False)
        #PEDRHOM
        # It is set to 1 for pose, might want to make this dynamic
        self.maxTracks = int(1) # default to 5 tracks
        self.trackColorMap = get_trackColors(self.maxTracks)

        self.classList = ['Class0', 'Class1']
        self.classLatestResults = deque(100*[0], 100)
        self.currFrameClassification = -1
        self.plotStart = 0

        self.class_buffer = []
        self.buffer_size = 3
        self.current_displayed_class = None

        

    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        probBox = self.initProbabilityPane()
        gridLayout.addWidget(probBox,3,0,1,1)

        # Init setup pane on left hand side
        # demoGroupBox = self.initSurfacePhysicalSetupPane()
        # gridLayout.addWidget(demoGroupBox,3,0,1,1)
        # gridLayout.replaceWidget(gridLayout.itemAt(3).widget(), demoGroupBox)

        self.surfaceTab = QWidget()
        vboxSurface = QVBoxLayout()
        vboxOutput = QVBoxLayout()            

        self.surfaceOutputRange = pg.PlotWidget()
        self.surfaceOutputRange.setBackground((70,72,79))

        self.surfaceOutputRange.showGrid(x=False,y=True,alpha=0.5)

        self.surfaceOutputRange.getAxis('bottom').setPen('w') 
        self.surfaceOutputRange.getAxis('left').setPen('w') 
        self.surfaceOutputRange.getAxis('right').setStyle(showValues=False) 
        self.surfaceOutputRange.hideAxis('top') 
        self.surfaceOutputRange.hideAxis('right') 
        self.surfaceOutputRange.setXRange(0,100,padding=0.00)
        self.surfaceOutputRange.setYRange(0,1,padding=0.00)
        self.surfaceOutputRange.setMouseEnabled(False,False)
        
        # Plot Data
        self.surfaceOutputRangeData = pg.PlotCurveItem(pen=pg.mkPen(width=3, color='b'))
        self.surfaceOutputRange.addItem(self.surfaceOutputRangeData)
        self.probabilityArray = np.empty(0, dtype=float)

        self.surfaceOutputRange.getPlotItem().setLabel('bottom', '<p style="font-size: 20px;color: white">Relative Frame # (0 is most recent)</p>')
        self.surfaceOutputRange.getPlotItem().setLabel('left', '<p style="font-size: 20px;color: white"> Probability Value</p>')
        self.surfaceOutputRange.getPlotItem().setLabel('right', ' ')
        self.surfaceOutputRange.getPlotItem().setTitle('<p style="font-size: 20px;color: white">Probability Value over Time</p>')
        self.surfaceOutputRange.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 3D Plot Controls
        demoGroupBox = self.initPlotControlPane()
               
        gridLayout.addWidget(demoGroupBox,4,0,1,1)

        vboxOutput.addWidget(self.surfaceOutputRange, stretch=1)
        self.plot_3d.setMinimumSize(400, 600)  # Set a minimum size for plot_3d
        vboxOutput.addWidget(self.plot_3d)  # Move plot_3d here
        vboxSurface.addLayout(vboxOutput)

        self.surfaceFontSize = '80px' 

        self.surfaceTab.setLayout(vboxSurface)
        demoTabs.addTab(self.surfaceTab, 'Point Cloud Classification')
        demoTabs.setCurrentIndex(1)
        self.device = device
        self.tabs = demoTabs

        # This function taken from people_tracking.py normally requires a cfg file.
        # Since this example uses a hard coded config in the firmware, need to adapt
        self.parseTrackingCfg(0)

    def initSurfacePhysicalSetupPane(self):
        self.surfaceSetupBox = QGroupBox('Physical Setup')

        self.gestureSetupGrid = QGridLayout()
        self.gestureSetupImg = QPixmap('./images/surface_setup.png')
        self.gestureImgLabel = QLabel()
        self.gestureImgLabel.setPixmap(self.gestureSetupImg)
        self.gestureSetupGrid.addWidget(self.gestureImgLabel, 1, 1)

        self.surfaceSetupBox.setLayout(self.gestureSetupGrid)

        return self.surfaceSetupBox

    def initProbabilityPane(self):
        probBox = QGroupBox('Probability')
        self.probLayout = QVBoxLayout()

        self.probBoxDisplay = QLabel("<b>Probability</b><br>0.0%")
        self.probBoxDisplay.setAlignment(Qt.AlignCenter)
        self.probBoxDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')

        self.classBoxDisplay = QLabel("<b>Classification</b><br>" + str(self.classList[0]))
        self.classBoxDisplay.setAlignment(Qt.AlignCenter)
        self.classBoxDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')

        self.probLayout.addWidget(self.probBoxDisplay)
        self.probLayout.addWidget(self.classBoxDisplay)
        probBox.setLayout(self.probLayout)

        return probBox


    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.numPointsDisplay = QLabel('Points: 0')
        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        statBox.setLayout(self.statsLayout)

        
        return statBox
    
    def initPlotControlPane(self):
        plotControlBox = QGroupBox('Plot Controls')
        self.pointColorMode = QComboBox()
        self.pointColorMode.addItems([COLOR_MODE_SNR, COLOR_MODE_HEIGHT, COLOR_MODE_DOPPLER, COLOR_MODE_TRACK])

        self.snapTo2D = QCheckBox('Snap to 2D')
        self.persistentFramesInput = QComboBox()
        self.persistentFramesInput.addItems([str(i) for i in range(1, MAX_PERSISTENT_FRAMES + 1)])
        self.persistentFramesInput.setCurrentIndex(self.numPersistentFrames - 1)
        self.persistentFramesInput.currentIndexChanged.connect(self.persistentFramesChanged)
        plotControlLayout = QFormLayout()
        plotControlLayout.addRow("Color Points By:",self.pointColorMode)
        plotControlLayout.addRow("# of Persistent Frames",self.persistentFramesInput)
        plotControlLayout.addRow(self.snapTo2D)
        plotControlBox.setLayout(plotControlLayout)

        return plotControlBox

    def persistentFramesChanged(self, index):
        self.numPersistentFrames = index + 1

    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))

        if ('mlType' in outputDict) :
            probabilities = outputDict['mlProbabilities']

            # Change the class list here to outputDict's classes
            self.classList = ["STANDING", "SITTING", "LYING", "FALLING", "WALKING"]
            classInferenced = np.argmax(probabilities)

            # Buffer implementation
            current_class = outputDict['mlResult']
            self.class_buffer.append(current_class)
            
            # Keep the buffer at the specified size
            if len(self.class_buffer) > self.buffer_size:
                self.class_buffer.pop(0)
            
            # Check if all elements in the buffer are the same
            stable_classification = (len(self.class_buffer) == self.buffer_size and 
                                    all(x == self.class_buffer[0] for x in self.class_buffer))

            numberOfClasses = len(self.classList)
            self.plotData = {cls: [] for cls in self.classList}
            self.plotCurves = {cls: self.surfaceOutputRange.plot(pen=pg.mkPen(color=pg.intColor(i, hues=len(self.classList)))) for i, cls in enumerate(self.classList)}
            
            if stable_classification and self.current_displayed_class != current_class:
                self.current_displayed_class = current_class
                self.classBoxDisplay.setText("<b>Classification Value</b><br>" + "{:8.5f}".format(float(probabilities[current_class]) * 100) + "%")
                self.probBoxDisplay.setText("<b>Classification</b><br>" + str(self.classList[classInferenced]))
                if str(self.classList[classInferenced]) == "FALLING":
                    self.classBoxDisplay.setStyleSheet('background-color: #ff0000; color: white; font-size: 20px; font-weight: bold')
                    self.probBoxDisplay.setStyleSheet('background-color: #ff0000; color: white; font-size: 20px; font-weight: bold')
                else:
                    self.classBoxDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')
                    self.probBoxDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')

            if self.probabilityArray.size == 0:
                list_of_empty_lists = [[] for _ in range(numberOfClasses)]
                self.probabilityArray = np.array(list_of_empty_lists, dtype=float)

            # Reshape arr1 to column vector
            probabilities_reshape = np.round(probabilities, 3)
            probabilities_reshape = probabilities_reshape.reshape(-1, 1)  # This gives [[1], [2], [3], [4], [5]]
            
            # Limit to 10 columns by removing the oldest one if needed
            if self.probabilityArray.shape[1] > 100:
                self.probabilityArray = self.probabilityArray[:, 1:]
            
            self.probabilityArray = np.hstack((self.probabilityArray, probabilities_reshape))
            
            # Plot each line
            self.surfaceOutputRange.clear()
            self.surfaceOutputRange.addLegend(offset=(30, 35))
            for i, line_data in enumerate(self.probabilityArray):
                x_values = np.arange(self.probabilityArray.shape[1])
                curve = pg.PlotCurveItem(
                    x=x_values, 
                    y=line_data,
                    name=self.classList[i],
                    pen=pg.mkPen(width=3, color=pg.intColor(i, hues=5)),
                    connect="all"
                )
                self.surfaceOutputRange.addItem(curve)
                            
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
                    # if it's not the first member, concat it
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
                    # if it's not the first member, concat it
                    else:
                        self.cumulativeCloud = np.concatenate((self.cumulativeCloud, self.previousClouds[frame]),axis=0)

        if ('numDetectedPoints' in outputDict):
            self.numPointsDisplay.setText('Points: '+ str(outputDict['numDetectedPoints']))

        # Tracks
        for cstr in self.coordStr:
            cstr.setVisible(False)

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
            self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.scatter, self.plot_3d, 0, self.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=self.pointColorMode.currentText(), trackColorMap=self.trackColorMap, demo="point_cloud_classification")
            self.plotComplete = 0
            self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
            self.plot_3d_thread.start(priority=QThread.HighPriority)
        self.graphDone(outputDict)
        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

    def graphDone(self, outputDict):
        plotTime = int(round(time.time()*1000)) - self.plotStart
        self.plotTimeDisplay.setText('Plot Time: ' + str(plotTime) + 'ms')
        self.plotComplete = 1

        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))

        if ('numDetectedPoints' in outputDict):
            self.numPointsDisplay.setText('Points: ' + str(outputDict['numDetectedPoints']))

    def parseTrackingCfg(self, args):
        self.maxTracks = 1
        self.trackColorMap = get_trackColors(self.maxTracks)
        gl = pg.opengl
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
