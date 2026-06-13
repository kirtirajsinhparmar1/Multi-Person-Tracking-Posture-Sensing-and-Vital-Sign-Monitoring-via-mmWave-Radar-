# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\power_consumption_report.py
import pyqtgraph as pg
from PySide2.QtWidgets import QPushButton, QSizePolicy, QHeaderView, QTableWidget, QTableWidgetItem, QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QLineEdit, QPushButton
import os
import datetime
import time
# import pandas as pd

class PowerReport():
    def __init__(self):

        self.currentAvgPwr = 0
        self.numPwrSamples = 0
        self.currentAvgNumPoints = 0
        self.numPointsSamples = 0
        self.start = 0
        self.length = 0
        self.measuredPwr = 0
        self.uartTime = 0
        self.processingTime = 0
        self.maxPwr = 0
        self.minPwr = 10000

        self.avgNumPointsList = []
        self.avgPowerList = []
        self.numPointsList = []
        self.uartTimeList = []
        self.processingTimeList = []
        self.timeStampList = []

        self.powerReportTab = QWidget()
        self.powerReportTabLayout = QVBoxLayout()
        
        self.powerVsTimePlotBoxGroup = QGroupBox("Power Consumption Over Time")
        self.powerVsTimePlot = pg.PlotWidget()
        self.powerVsTimePlot.setLabel("left", "Measured Power Consumption (mW)")
        self.powerVsTimePlot.setLabel("bottom", "Time (seconds) ")
        self.powerVsTimePlot.setBackground('w')
        self.powerVsTimePlot.showGrid(x=True,y=True)
        self.powerVsTimePlot.enableAutoRange(enable=True)
        self.powerVsTimePlot.setMouseEnabled(True,True)
        self.powerVsTimePlot.addLegend()
        self.powerVsTimePlot.plot([], [], pen=None, name='Measured Power Consumption', symbol='o', symbolPen=pg.mkPen(color='b'), symbolSize=7)
        self.powerVsTimeLayout = QVBoxLayout()
        self.powerVsTimePlotBoxGroup.setLayout(self.powerVsTimeLayout)
        self.powerVsTimeLayout.addWidget(self.powerVsTimePlot)

        powerVsTimePlotSizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        powerVsTimePlotSizePolicy.setVerticalStretch(8)
        self.powerVsTimePlotBoxGroup.setSizePolicy(powerVsTimePlotSizePolicy)

        self.powerStatsPane = QGroupBox("Power Consumption Stats")
        self.powerStatsPaneLayout = QVBoxLayout()
        self.powerStatsPane.setLayout(self.powerStatsPaneLayout)
        self.initPowerStatsTable()

        powerStatsSizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        powerStatsSizePolicy.setVerticalStretch(1)
        self.powerStatsPane.setSizePolicy(powerStatsSizePolicy)

        self.powerReportTabLayout.addWidget(self.powerVsTimePlotBoxGroup)
        self.powerReportTabLayout.addWidget(self.powerStatsPane)
        self.powerReportTab.setLayout(self.powerReportTabLayout)


    # Initializes the table showing statistics on the power consumption
    def initPowerStatsTable(self):
        # Set parameter names

        self.powerStatsTable = QTableWidget(1, 3)
        self.avgPowerLabelCell = QTableWidgetItem('Average Power :')
        self.maxPowerLabelCell = QTableWidgetItem('Max Power :')
        self.minPowerLabelCell = QTableWidgetItem('Min Power :')

        self.powerStatsTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.powerStatsTable.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.powerStatsTable.setHorizontalHeaderItem(0, self.minPowerLabelCell)
        self.powerStatsTable.setHorizontalHeaderItem(1, self.avgPowerLabelCell)
        self.powerStatsTable.setHorizontalHeaderItem(2, self.maxPowerLabelCell)
        self.powerStatsTable.setVerticalHeaderItem(0, QTableWidgetItem(''))
        self.powerStatsPaneLayout.addWidget(self.powerStatsTable)


    # Updates the table showing statistics on the power consumption
    def updatePowerStatsTable(self, numPoints):
        self.numPointsList.append(numPoints)
        self.avgPowerList.append(self.measuredPwr)
        self.timeStampList.append(self.timeStamp)

        self.powerVsTimePlot.clear()        
        self.powerVsTimePlot.plot(self.timeStampList, self.avgPowerList, pen=None, name='Measured Power Consumption', symbol='o', symbolPen=pg.mkPen(color='b'), symbolSize=7)
        self.currentAvgPwr = len(self.avgPowerList) / (len(self.avgPowerList) + 1) * self.currentAvgPwr + self.measuredPwr / (len(self.avgPowerList) + 1)
        self.maxPwr = max(self.measuredPwr, self.maxPwr)
        self.minPwr = min(self.measuredPwr, self.minPwr)

        self.avgPowerCell = QTableWidgetItem(QTableWidgetItem(str(round(self.currentAvgPwr,2))))
        self.powerStatsTable.setItem(0,1, self.avgPowerCell)

        self.maxPowerCell = QTableWidgetItem(QTableWidgetItem(str(round(self.maxPwr,2))))
        self.powerStatsTable.setItem(0,2, self.maxPowerCell)

        self.minPowerCell = QTableWidgetItem(QTableWidgetItem(str(round(self.minPwr,2))))
        self.powerStatsTable.setItem(0,0, self.minPowerCell)

    # Resets the table showing statistics on the power consumption
    def resetPowerStatsTable(self):
        self.powerVsTimePlot.clear()
        self.avgNumPointsList = []
        self.timeStampList = []
        self.avgPowerList = []
        self.numPointsList = []
        self.uartTimeList = []
        self.processingTimeList = []

    # Resets the power display
    def resetPowerNumbers(self):
        self.start = 0
        self.length = 0
        self.resetPowerStatsTable()

    # Not used yet, exports the power consumption via CSV
    def exportPowerData(self):
        data = {'Measured Power Consumption': self.avgPowerList,
                '# of Points Detected': self.numPointsList,
                'Processing Time': self.processingTimeList,
                'UART Time': self.uartTimeList}
        # dataframe be removed or enabled a different way
        df = pd.DataFrame(data)
        fileName = datetime.datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
        if (os.path.exists('powerData/') == False):
            os.mkdir('powerData/')
        df.to_csv(f"powerData/{fileName}.csv")

    # Recompute avg power consumption
    def computeUpdatedPowerNumbers(self, outputDict):
        if self.start == 0:
            self.start = time.time()
        end = time.time()
        self.timeStamp = end - self.start

        if self.timeStamp > 30:
            if ('powerData' in outputDict):
                powerData = outputDict['powerData']
                if powerData['power1v2'] != 65535:
                    self.measuredPwr = (powerData['power1v2'] \
                        + powerData['power1v2RF'] + powerData['power1v8'] + powerData['power3v3']) * 0.1
                    self.currentAvgPwr = self.numPwrSamples / (self.numPwrSamples + 1) * self.currentAvgPwr + self.measuredPwr / (self.numPwrSamples + 1)
                    self.numPwrSamples += 1

            if ('procTimeData' in outputDict):
                self.uartTime = outputDict['procTimeData']['transmitOutTime'] / 1000
                self.processingTime = outputDict['procTimeData']['interFrameProcTime'] / 1000
            if ('numDetectedPoints' in outputDict):
                self.numPoints = outputDict['numDetectedPoints']
                self.currentAvgNumPoints = self.numPointsSamples / (self.numPointsSamples + 1) * self.currentAvgNumPoints + self.numPoints / (self.numPointsSamples + 1)
                self.numPointsSamples += 1
        powerNumbers = {}
        powerNumbers["timeStamp"] = self.timeStamp
        powerNumbers["currentMeasuredPwr"] = self.measuredPwr
        return powerNumbers


