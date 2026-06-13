# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\false_alarm_test.py
from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines

from PySide2.QtCore import Qt, QThread
from PySide2.QtGui import QPixmap, QFont
import pyqtgraph.opengl as gl
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from PySide2.QtWidgets import QPushButton, QSizePolicy, QHeaderView, QTableWidget, QTableWidgetItem, QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QLineEdit, QPushButton
from Common_Tabs.plot_3d import Plot3D
import numpy as np
import time
# Logger
import logging
log = logging.getLogger(__name__)

class FalseAlarm():
    def __init__(self):

        # False Alarm Testing
        self.timeInMode1 = 0
        self.timeInMode2 = 0
        self.timeInMode3 = 0
        self.timeInModeCam = 0

        self.timesMode1Entered = 0
        self.timesMode2Entered = 0
        self.timesMode3Entered = 0
        self.timesModeCamEntered = 0
        self.boxArr = [ [0]*20 for i in range(20)]
        self.totalFA = 0

        self.runningModeTimer = 0
        self.falseAlarmGrid = np.zeros((20,20))

        self.plot_3d = Plot3D()

        self.detStatsPane = QGroupBox("False Alarm Stats")
        self.detStatsPaneLayout = QVBoxLayout()
        self.detStatsPane.setLayout(self.detStatsPaneLayout)
        self.detStatsPane.setMaximumHeight(150)
        self.initFalseAlarmTable()

        self.pointCloudPlotPane = QGroupBox("False Alarm Locations")
        self.pointCloudPlotPaneLayout = QVBoxLayout()
        self.pointCloudPlotPane.setLayout(self.pointCloudPlotPaneLayout)
        self.addFADisplayTo3DPlot()

        self.plot_3d.plot_3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.pointCloudPlotPaneLayout.addWidget(self.plot_3d.plot_3d)

        pointCloudPlotSizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        pointCloudPlotSizePolicy.setVerticalStretch(12)
        self.pointCloudPlotPane.setSizePolicy(pointCloudPlotSizePolicy)

        self.falseAlarmTab = QWidget()
        self.detRangePaneLayout = QVBoxLayout()

        self.detRangePaneLayout.addWidget(self.pointCloudPlotPane)
        self.detRangePaneLayout.addWidget(self.detStatsPane)
        
        self.falseAlarmTab.setLayout(self.detRangePaneLayout)

    # Create the table in the FA screen showing the statistics on time in each mode
    def initFalseAlarmTable(self):
        # Set parameter names

        self.falseAlarmTable = QTableWidget(2, 4)
        self.firstPassFAStats = QTableWidgetItem('Mode 1')
        self.secondPassFAStats = QTableWidgetItem('Mode 2')
        self.thirdPassFAStats = QTableWidgetItem('Mode 3')
        self.cameraOnFAStats = QTableWidgetItem('Camera On')

        self.percentTimeTableItem = QTableWidgetItem('% of time in mode')
        self.numTimesTableItem = QTableWidgetItem('# of times mode entered')

        self.falseAlarmTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.falseAlarmTable.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.falseAlarmTable.setVerticalHeaderItem(0, self.percentTimeTableItem)
        self.falseAlarmTable.setVerticalHeaderItem(1, self.numTimesTableItem)
        
        self.falseAlarmTable.setHorizontalHeaderItem(0, self.firstPassFAStats)
        self.falseAlarmTable.setHorizontalHeaderItem(1, self.secondPassFAStats)
        self.falseAlarmTable.setHorizontalHeaderItem(2, self.thirdPassFAStats)
        self.falseAlarmTable.setHorizontalHeaderItem(3, self.cameraOnFAStats)

        self.falseAlarmTable.setRowHeight(0,100)
        self.falseAlarmTable.setRowHeight(1,100)

        self.detStatsPaneLayout.addWidget(self.falseAlarmTable)
        

    # Create the grid that will be used for the false alarm heatmap
    def addFADisplayTo3DPlot(self):            
        for i in range(20):
            for j in range(20):
                x = np.array([i-10,i-9])
                y = np.array([j,j+1])
                z = np.array([[0,0],[0,0]])
                c = QtGui.QColor(0, 0, 50)
                self.boxArr[i][j] = gl.GLSurfacePlotItem(x=x, y = y, z = z, color=c)
                self.plot_3d.plot_3d.addItem(self.boxArr[i][j])

    # Main logic for computing false alarm table. Computes time in each mode and updates table
    def run_false_alarm_state_machine(self, frameNum, prevModeState,outputDict, prevCamState):     
        # Start the timer for the first frame for counting the time per mode    
        if(frameNum <= 10):
            self.runningModeTimer = int(round(time.time()*1000))
            self.resetFalseAlarmTimers()
        else:
            if('modeState' in outputDict and outputDict['modeState'] == 3 and prevModeState == 2):
                if('clusterLocs' in outputDict):
                    self.addClustersToFalseAlarmGrid(outputDict['clusterLocs'])

            # If the mode changes
            if(prevModeState is not None and "modeState" in outputDict):
                # If we came from first pass mode (going into 2nd pass mode)
                if(prevModeState == 0):
                    # Count the number of msec spent in mode 1
                    self.timeInMode1 += int(round(time.time()*1000)) - self.runningModeTimer
                    # reset the running mode timer for the next mode
                    self.runningModeTimer = int(round(time.time()*1000))
                    self.timesMode1Entered += 1
                # If we came from second pass mode (going into 3rd or 1st pass mode)
                elif(prevModeState == 1):
                    # Count the number of msec spent in mode 1
                    self.timeInMode2 += int(round(time.time()*1000)) - self.runningModeTimer
                    # reset the running mode timer for the next mode
                    self.runningModeTimer = int(round(time.time()*1000))
                    self.timesMode2Entered += 1
                # If we came from third pass mode (going into camera on or 1st pass mode)
                elif(prevModeState == 2):
                    # Count the number of msec spent in mode 1
                    self.timeInMode3 += int(round(time.time()*1000)) - self.runningModeTimer
                    # reset the running mode timer for the next mode
                    self.runningModeTimer = int(round(time.time()*1000))
                    self.timesMode3Entered += 1
                    outputDict['modeState'] == 3
                # If we came from camera on mode
                elif(prevModeState == 3):
                    # Count the number of msec spent in mode 1
                    self.timeInModeCam += int(round(time.time()*1000)) - self.runningModeTimer
                    # reset the running mode timer for the next mode
                    self.runningModeTimer = int(round(time.time()*1000))
                    self.timesModeCamEntered += 1

                self.updateFalseAlarmTable()

    # Reset the false alarm timers, called when the sensor restarts
    def resetFalseAlarmTimers(self):
        self.timeInMode1 = 0
        self.timeInMode2 = 0
        self.timeInMode3 = 0
        self.timesMode1Entered = 0
        self.timesMode2Entered = 0
        self.timesMode3Entered = 0
        self.timeInModeCam = 0

    # Updates the FA table with the current statistics
    def updateFalseAlarmTable(self):
        totalTime = self.timeInMode1 + self.timeInMode2 + self.timeInMode3 + self.timeInModeCam

        if(totalTime == 0):
            log.error("Device needs to be reset before operation can begin for proper measurement")
        else:
            self.falseAlarmTable.setItem(0,0, QTableWidgetItem(str(round(100 * self.timeInMode1 / totalTime))))
            self.falseAlarmTable.setItem(0,1, QTableWidgetItem(str(round(100 * self.timeInMode2 / totalTime))))
            self.falseAlarmTable.setItem(0,2, QTableWidgetItem(str(round(100 * self.timeInMode3 / totalTime))))
            self.falseAlarmTable.setItem(0,3, QTableWidgetItem(str(round(100 * self.timeInModeCam / totalTime))))

            self.falseAlarmTable.setItem(1,0, QTableWidgetItem(str(self.timesMode1Entered)))
            self.falseAlarmTable.setItem(1,1, QTableWidgetItem(str(self.timesMode2Entered)))
            self.falseAlarmTable.setItem(1,2, QTableWidgetItem(str(self.timesMode3Entered)))
            self.falseAlarmTable.setItem(1,3, QTableWidgetItem(str(self.timesModeCamEntered)))
    
    # Computes which area in the grid should get the false alarm based off location
    def addClustersToFalseAlarmGrid(self, clusterLocs):
        if(clusterLocs is not None):
            for cluster in clusterLocs:
                x = int(np.floor(cluster[0]))
                y = int(np.floor(cluster[1]))
                if(x < 10 and x >= -10 and y >= 0 and y < 20):
                    self.falseAlarmGrid[x+10,y] += 1
                self.totalFA += 1
        else:
            print("Error : Changed modes without a cluster")

        if(self.totalFA > 0):
            for i in range(20):
                for j in range(20):
                    if(self.falseAlarmGrid[i,j] > 0):
                        x = np.array([i-10,i-9])
                        y = np.array([j,j+1])
                        z = np.array([[0,0],[0,0]])
                        c_mag = self.falseAlarmGrid[i,j] / self.totalFA
                        c = QtGui.QColor(round(c_mag * 200)+55, 0, 50 - round(c_mag * 50))#round(c_mag * 255)) # Make square red, translucence determines prevalence
                        self.boxArr[i][j].setColor(c)
        
    