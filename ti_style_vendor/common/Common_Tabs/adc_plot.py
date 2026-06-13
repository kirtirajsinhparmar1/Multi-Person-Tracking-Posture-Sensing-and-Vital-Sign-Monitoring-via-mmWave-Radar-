# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\adc_plot.py

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import copy

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QGraphicsWidget

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from Common_Tabs.plot_2d import Plot2D

class ADCPlotObject():
    def __init__(self):
        
        # Arbitrary Constants for setup
        self.yMin = -300
        self.yMax = 300
        self.xMin = 0
        # Default Max value, will change when data starts flowing in
        self.xMax = 256
        
        # Create plot
        self.adclayout = pg.GraphicsLayoutWidget()
        self.adclayout.setBackground('w')
        self.adcplot2d = self.adclayout.addPlot(title='ADC Data', labels= {'left': ("ADC Codes"), 'bottom': ("Samples")})
        self.adcplot2d.showGrid(x=False,y=False)
        self.adc_curve = []

        # Create curves
        self.adc_curve.append(pg.PlotCurveItem(name="T1R1", pen=pg.mkPen(width=3, color='r')))
        self.adc_curve.append(pg.PlotCurveItem(name="T1R2", pen=pg.mkPen(width=3, color='b')))
        self.adc_curve.append(pg.PlotCurveItem(name="T1R3", pen=pg.mkPen(width=3, color='g')))
        self.adc_curve.append(pg.PlotCurveItem(name="T2R1", pen=pg.mkPen(width=3, color='y')))
        self.adc_curve.append(pg.PlotCurveItem(name="T2R2", pen=pg.mkPen(width=3, color='c')))
        self.adc_curve.append(pg.PlotCurveItem(name="T2R3", pen=pg.mkPen(width=3, color='m')))
        
        # Add Legend
        legend = self.adcplot2d.addLegend(offset=(-30, 30)) # Offset the legend from the top-right corner
    
        # Add Curves
        self.adcplot2d.addItem(self.adc_curve[0])
        self.adcplot2d.addItem(self.adc_curve[1])
        self.adcplot2d.addItem(self.adc_curve[2])
        self.adcplot2d.addItem(self.adc_curve[3])
        self.adcplot2d.addItem(self.adc_curve[4])
        self.adcplot2d.addItem(self.adc_curve[5])
        
        # Configure Plot
        self.adcplot2d.setXRange(self.xMin, self.xMax,padding=0.01)
        self.adcplot2d.setYRange(self.yMin, self.yMax,padding=0.01)
        self.adcplot2d.setLimits(xMin=self.xMin, xMax=self.xMax, yMin=self.yMin, yMax=self.yMax)
        self.adcplot2d.disableAutoRange()

    def updateGraph(self,outputDict):
        if(outputDict is not None):
            if("rawADCData" in outputDict):
                numSamples = outputDict["numADCSamples"]

                # Reset the X range depending on the number of samples
                if(self.xMax != numSamples):
                    self.xMax = numSamples
                    self.adcplot2d.setXRange(self.xMin, self.xMax,padding=0.01)

                x = range(numSamples)
                y = outputDict['rawADCData']
                numVirtualChannels = outputDict['numVirtualChannels']
                # Zero Indexing
                for i in range(numVirtualChannels):
                    channelData = y[(0+i*numSamples):(numSamples+i*numSamples)]
                    self.adc_curve[i].setData(channelData)
