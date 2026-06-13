# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\sleep_monitoring.py
# General Library Imports
import copy
import string
import math

# Imports for recording sleep monitoring data in .csv file
import csv
from datetime import datetime

# Local Imports
from Demo_Classes.people_tracking import PeopleTracking
# Logger
import logging
log = logging.getLogger(__name__)

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QSizePolicy
from PySide2.QtCore import Qt, QThread
import pyqtgraph as pg
import numpy as np
from graph_utilities import get_trackColors, eulerRot
import time
from gui_threads import updateQTTargetThread3D

class SleepMonitoring(PeopleTracking):
    def __init__(self):
        PeopleTracking.__init__(self)
        self.csv_filename = f'sleep_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        self.csv_initialized = False
        self.displayList = ['NA']

        # Activity level buffer and plotting
        self.actBufLen = None
        self.activityAverages = []  # Stores the running averages for plotting
        self.maxPlotPoints = 100  # Maximum number of points to display on the plot
        self.normalizationFactor = 40000 # Normalization Factor for average energy values
        self.sleepMonitoringClassification = str(self.displayList[0]) # Final Classification for sleep monitoring

    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        probBox = self.initProbabilityPane()
        gridLayout.addWidget(probBox,3,0,1,1)

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
        self.surfaceOutputRange.setYRange(0,105,padding=0.00)
        self.surfaceOutputRange.setMouseEnabled(False,False)
        
        # Plot Data
        self.surfaceOutputRangeData = pg.PlotCurveItem(pen=pg.mkPen(width=3, color='b'))
        self.surfaceOutputRange.addItem(self.surfaceOutputRangeData)

        self.surfaceOutputRange.getPlotItem().setLabel('bottom', '<p style="font-size: 20px;color: white">Activity Level over Time</p>')
        self.surfaceOutputRange.getPlotItem().setLabel('left', '<p style="font-size: 20px;color: white">Activity Level</p>')
        self.surfaceOutputRange.getPlotItem().setLabel('right', ' ')
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
        demoTabs.addTab(self.surfaceTab, 'Sleep Monitoring')
        demoTabs.setCurrentIndex(1)
        self.device = device
        self.tabs = demoTabs

    def updateGraph(self, outputDict):
        self.plotStart = int(round(time.time()*1000))
        self.updatePointCloud(outputDict)

        self.cumulativeCloud = None

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
            self.plot_3d_thread = updateQTTargetThread3D(self.cumulativeCloud, tracks, self.scatter, self.plot_3d, 0, self.ellipsoids, "", colorGradient=self.colorGradient, pointColorMode=self.pointColorMode.currentText(), trackColorMap=self.trackColorMap)
            self.plotComplete = 0
            self.plot_3d_thread.done.connect(lambda: self.graphDone(outputDict))
            self.plot_3d_thread.start(priority=QThread.HighPriority)

        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))


        if('sleepData' in outputDict):
            self.normalizationFactor = outputDict['sleepData']['normalizationFactor']
            self.sleep_range_Display.setText('Target Distance: ' + str(outputDict['sleepData']['range']) + ' meters')
            #self.sleep_energyAverage_Display.setText('Sleep Energy Average: ' + str(outputDict['sleepData']['energyAverage']))
            #self.sleep_activityBufferEnergyAverage_Display.setText('activityBufferEnergyAverage: ' + str(outputDict['sleepData']['activityBufferEnergyAverage']))

            # Initialize csv file
            if not self.csv_initialized:
                with open(self.csv_filename, 'w', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(['Timestamp', 'Energy_Average', 'Normalized_Energy_Average', 'Sleep_Classification'])
                self.csv_initialized = True
            
            # When a cycle of activity / energy buffer is completed:
            if outputDict['sleepData']['writeToCSV'] == 1:
                # Average energy of the buffer
                bufferAverage = outputDict['sleepData']['activityBufferEnergyAverage']
                
                # Add to the plotting array
                self.activityAverages.append(bufferAverage)
                
                # Limit the number of points displayed
                if len(self.activityAverages) > self.maxPlotPoints:
                    self.activityAverages.pop(0)
                
                # Update the plot
                self.updateActivityPlot()
                
                # Update the activity level display
                normalizedActivity = min(100, (bufferAverage / self.normalizationFactor) * 100)
                self.activityLevelDisplay.setText(f"<b>Activity Level</b><br>{normalizedActivity:.2f}%")

                # Update the classification display
                if normalizedActivity < outputDict['sleepData']['restlessClassLowerThresh']:
                    self.sleepMonitoringClassification = 'Asleep'
                elif normalizedActivity >= outputDict['sleepData']['restlessClassLowerThresh'] and normalizedActivity <= outputDict['sleepData']['restlessClassUpperThresh']:
                    self.sleepMonitoringClassification = 'Restless'
                elif normalizedActivity > outputDict['sleepData']['restlessClassUpperThresh']:
                    self.sleepMonitoringClassification = 'Awake'
                self.classBoxDisplay.setText(f"<b>Classification</b><br>{self.sleepMonitoringClassification}")
                
                # Calculate normalized energy [energy average of activity buffer ranging from 0-NORMALIZATION_VALUE is normalized to 0-100]
                normalized_energy = round(normalizedActivity, 2)

                with open(self.csv_filename, 'a', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                        outputDict['sleepData']['activityBufferEnergyAverage'],
                        normalized_energy,
                        self.sleepMonitoringClassification
                    ])


        # Classifier
        for cstr in self.classifierStr:
            cstr.setVisible(False)

        # Hold the track IDs detected in the current frame
        trackIDsInCurrFrame = []
        classifierOutput = None
        tracks = None
        if ('ClassificationDecision' in outputDict):
            for trackNum, trackName in enumerate(outputDict['trackData']):
                trackID = int(trackName[0])
                if outputDict['ClassificationDecision'][trackID] is not None:
                    # Decode trackID from the trackName
                    self.classifierStr[trackID].setText(outputDict['ClassificationDecision'][trackID])
                    # Populate string that will display a label      
                    self.classifierStr[trackID].setX(trackName[1])
                    self.classifierStr[trackID].setY(trackName[2])
                    self.classifierStr[trackID].setZ(trackName[3] + 0.1) # Add 0.1 so it doesn't interfere with height text if enabled
                    self.classifierStr[trackID].setVisible(True)

    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.numPointsDisplay = QLabel('Points: 0')
        self.numTargetsDisplay = QLabel('Targets: 0')
        self.avgPower = QLabel('Average Power: 0 mw')

        self.sleep_range_Display = QLabel('Target Distance: 0 meters')
        #self.sleep_energyAverage_Display = QLabel('Sleep Energy Average: 0')
        #self.sleep_activityBufferEnergyAverage_Display = QLabel('activityBufferEnergyAverage: 0')

        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.numPointsDisplay)
        self.statsLayout.addWidget(self.numTargetsDisplay)
        self.statsLayout.addWidget(self.avgPower)

        self.statsLayout.addWidget(self.sleep_range_Display)
        #self.statsLayout.addWidget(self.sleep_energyAverage_Display)
        #self.statsLayout.addWidget(self.sleep_activityBufferEnergyAverage_Display)

        statBox.setLayout(self.statsLayout)
        return statBox
    
    def initProbabilityPane(self):
        probBox = QGroupBox('Sleep Monitoring Information')
        self.probLayout = QVBoxLayout()

        self.classBoxDisplay = QLabel("<b>Classification</b><br>" + str(self.displayList[0]))
        self.classBoxDisplay.setAlignment(Qt.AlignCenter)
        self.classBoxDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')

        self.activityLevelDisplay = QLabel("<b>Activity Level</b><br>" + str(self.displayList[0]))
        self.activityLevelDisplay.setAlignment(Qt.AlignCenter)
        self.activityLevelDisplay.setStyleSheet('background-color: #46484f; color: white; font-size: 20px; font-weight: light')

        self.probLayout.addWidget(self.activityLevelDisplay)
        self.probLayout.addWidget(self.classBoxDisplay)
        probBox.setLayout(self.probLayout)

        return probBox
    
    def updateActivityPlot(self):
        self.surfaceOutputRange.clear()
        if len(self.activityAverages) > 0:
            normalizedAverages = [min(100, (val / self.normalizationFactor) * 100) for val in self.activityAverages]
            x_values = np.arange(len(normalizedAverages))
            curve = pg.PlotCurveItem(
                x=x_values,
                y=normalizedAverages,
                pen=pg.mkPen(width=3, color='b'),
                connect="all"
            )
            self.surfaceOutputRange.addItem(curve)
            self.surfaceOutputRange.setXRange(0, max(self.maxPlotPoints, len(normalizedAverages)), padding=0.00)