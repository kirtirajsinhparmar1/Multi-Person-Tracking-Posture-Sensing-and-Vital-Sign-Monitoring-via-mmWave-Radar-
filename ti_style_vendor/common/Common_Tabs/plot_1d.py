# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\plot_1d.py
# General Library Imports
import numpy as np 

# PyQt Imports
import pyqtgraph as pg

# Local Imports
from gui_common import next_power_of_2

# Logger
import logging
log = logging.getLogger(__name__)

class Plot1D():
    def __init__(self, demo = None):
        self.rangeProfileType = -1
        self.NumOfAdcSamples = -1
        self.rangeAxisVals = -1
        self.DigOutputSampRate = -1
        self.ChirpRfFreqSlope = -1
        self.rangeProfile = np.zeros(128)
        self.ChirpTxMimoPatSel = -1

        # rangePlot
        if demo == None:
            self.rangePlot = pg.PlotWidget()
            self.rangePlot.setBackground('w')
            self.rangePlot.showGrid(x=True,y=True)
            self.rangePlot.setXRange(0,self.NumOfAdcSamples/2,padding=0.01)
            self.rangePlot.setYRange(0,150,padding=0.01)
            self.rangePlot.setMouseEnabled(False,False)
            self.rangeData = pg.PlotCurveItem(pen=pg.mkPen(width=3, color='r'))
            self.rangePlot.addItem(self.rangeData)
        elif demo == 'intruder':
            # occupancy plot - TODO: only initialize if intruder is the demo
            self.occThreshPlot = pg.PlotWidget()
            self.occThreshPlot.setBackground('k')
            self.occThreshPlot.showGrid(x=True,y=True)
            self.occThreshPlot.setLabel('bottom', 'Frames')
            self.occThreshPlot.setLabel('left', 'Occupancy Signals')
            #self.occThreshPlot.setAspectLocked(lock=True, ratio=2)
            self.occThreshPlot.setXRange(0,50,padding=0.01)
            self.occThreshPlot.setYRange(0,30,padding=0.01)
            self.occThreshPlot.setMouseEnabled(False,False)
            self.occThreshPlot.addLegend()
            self.OccData =  []  # this contains all the plot curve items
        elif demo == "LPD":
            # probability plot for SBR and CPD
            self.probPlot = pg.PlotWidget()
            self.probPlot.setBackground('k')
            self.probPlot.showGrid(x=True,y=True)
            self.probPlot.setLabel('bottom', 'Frames')
            self.probPlot.setLabel('left', 'probability')
            #self.probPlot.setAspectLocked(lock=True, ratio=2)
            self.probPlot.setXRange(0,50,padding=0.01)
            self.probPlot.setYRange(0,1,padding=0.01)
            self.probPlot.setMouseEnabled(False,False)
            self.probPlot.getPlotItem().addLegend()
            self.probLines = [] # contains the plot curve items

    def update1DGraph(self, outputDict):
        # TODO add range profile to 6843
        if ('rangeProfile' in outputDict) :
            # 6432 Major Motion or Minor Motion
            if (self.rangeProfileType == 1 or self.rangeProfileType == 2):
                    numRangeBinsParsed = len(outputDict['rangeProfile'])
                    # Check size of rangeData matches expected size
                    if (numRangeBinsParsed == next_power_of_2(round(self.NumOfAdcSamples / 2))):
                        self.rangeProfile = [np.log10(max(1, item)) * 20 for item in outputDict['rangeProfile']] # list comprehension required so we don't take log(0)         
                        # Update graph data
                        # print("Range Axis"+str(self.rangeAxisVals))
                        # print("Range Profile"+str(self.rangeProfile))
                        self.rangeData.setData(self.rangeAxisVals, self.rangeProfile)
                    else:
                        log.error(f'Size of rangeProfile (${numRangeBinsParsed}) did not match the expected size (${next_power_of_2(round(self.NumOfAdcSamples / 2))})')
        if ('occPlot' in outputDict):
            # For each occupancy plot, update the data with the new data from outputDict
            # print("printing BOX: ")
            # print(outputDict['occPlot'])
            for box in range(1,len(outputDict['occPlot'])): # skip plotting the first one
                # print("box: " + str(box))
                data = outputDict['occPlot'][box]
                # print("Data lenghth: " + str(len(data)))
                self.FrameLen = list(range(1,len(data)+1))
                # Update the data for the plot with the new data
                self.OccData[box].setData(self.FrameLen,data)
            # Enable auto-range on the y-axis to make sure the plot data is always visible
            self.occThreshPlot.enableAutoRange(axis='y')
            # Make sure that if the y-axis range changes, the plot is automatically resized to show the new range
            self.occThreshPlot.setAutoVisible(y=True)
    def updateOccPred(self, outputDict, plotType):
        self.probPlot.showLabel('bottom',show=True)
        if plotType == 'SBR':
            dataFrom = outputDict['OccPredPlot']
        elif plotType == 'CPD':
            dataFrom = outputDict['OccHeightPlot']

        for zone in range(len(self.probLines)):
            data = dataFrom[zone]
            self.FrameLen = list(range(1,len(data)+1))
            self.probLines[zone][0].setData(self.FrameLen,data)
            self.probPlot.enableAutoRange(axis='y')
            self.probPlot.setAutoVisible(y=True)

#-----------------------------------------------------
# Config Parsing Functions
#-----------------------------------------------------

    def parseChirpComnCfg(self, args):
        self.DigOutputSampRate = int(args[1])
        self.NumOfAdcSamples = int(args[4])
        self.ChirpTxMimoPatSel = int(args[5])

    def parseChirpTimingCfg(self, args):
        self.ChirpRfFreqSlope = float(args[4])

    def parseGuiMonitor(self, args):
        self.rangeProfileType = int(args[2])
             
    def setRangeValues(self):
        # Set range resolution
        self.rangeRes = (3e8*(100/self.DigOutputSampRate)*1e6)/(2*self.ChirpRfFreqSlope*1e12*self.NumOfAdcSamples)
        self.rangePlot.setXRange(0,(self.NumOfAdcSamples/2)*self.rangeRes,padding=0.01)
        self.rangeAxisVals = np.arange(0, self.NumOfAdcSamples/2*self.rangeRes, self.rangeRes)

        # Set title based on selected range profile type
        if (self.rangeProfileType == 1):
            self.rangePlot.getPlotItem().setLabel('top','Major Range Profile')
        elif (self.rangeProfileType == 2):
            self.rangePlot.getPlotItem().setLabel('top','Minor Range Profile')
        else:
            self.rangePlot.getPlotItem().setLabel('top','Range Profile DISABLED')
