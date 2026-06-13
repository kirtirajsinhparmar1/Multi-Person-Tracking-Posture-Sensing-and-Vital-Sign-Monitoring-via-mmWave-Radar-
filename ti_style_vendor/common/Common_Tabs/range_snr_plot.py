# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\range_snr_plot.py
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import copy

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QGraphicsWidget

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from Common_Tabs.plot_2d import Plot2D

class RangeSNRPlotObject():
    def __init__(self):
        # Create plot
        self.rangeSNRlayout = pg.GraphicsLayoutWidget()
        self.rangeSNRlayout.setBackground('w')
        self.rangeSNRplot2d = self.rangeSNRlayout.addPlot(title='Range vs SNR Plot', labels= {'left': ("SNR (dB)"), 'bottom': ("Range (m)")})
        self.rangeSNRplot2d.showGrid(x=True,y=True)
        
        # Add multiple scatter plots to the plot to 
        # allow users to look at the detection SNR at different angles.
        # Not used right now
        self.rangeSNR_curve0 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 255, 0, 255))
        self.rangeSNR_curve1 = pg.ScatterPlotItem(brush=pg.mkBrush(255, 0, 0, 255), hoverable = True)
        self.rangeSNR_curve2 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 0,255, 255))
        self.rangeSNR_curve3 = pg.ScatterPlotItem(brush=pg.mkBrush(255, 0, 0, 255), hoverable = True, symbol='s')
        self.rangeSNR_curve4 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 255, 0, 255), symbol='s')
        self.rangeSNR_curve5 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 0,255, 255), symbol='s')

        # Add curves to plot
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve1)
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve2)
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve0)
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve3)
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve4)
        self.rangeSNRplot2d.addItem(self.rangeSNR_curve5)

        # Basic Plot Setup
        self.yMinFFT = 0
        self.yMaxFFT = 50
        self.xMaxFFT = 12
        self.xMin = 0
        self.rangeSNRplot2d.setXRange(self.xMin, self.xMaxFFT,padding=0.01)
        self.rangeSNRplot2d.setYRange(self.yMinFFT, self.yMaxFFT,padding=0.01)
        self.rangeSNRplot2d.setLimits(xMin=-0.1, xMax=20, yMin=-0.1, yMax=100)
        self.rangeSNRplot2d.disableAutoRange()

        # theta_bounds allow users to look at the detection SNR at different angles. 
        # They aren't used right now (hence -91 to 91 is the entire FOV)
        self.theta_bounds = [-91, 91]
        self.clearPlot()

    # Removes all points from the plot
    def clearPlot(self):
        self.rList = [[]]
        self.tList = [[]]
        self.snrList = [[]]
        self.minorPlotList = [[]]
        self.majorPlotList = [[]]
        self.localFrameCounter = 1
        for i in range(len(self.theta_bounds)):
            self.rList.append([])
            self.tList.append([])
            self.snrList.append([])
            self.majorPlotList.append([])
            self.minorPlotList.append([])

    def updateGraph(self,outputDict):
        # If point cloud is detected
        if(outputDict is not None and 'pointCloud' in outputDict):
            for point in outputDict['pointCloud']:
                # Compute range and angle 
                x = point[0]
                y = point[1]
                z = point[2]
                snr = point[4]
                r = np.sqrt(np.power(x,2) + np.power(y,2) + np.power(z,2))
                if(y>0):
                    theta = np.arctan(x / y) * 180 / 3.14159
                else:
                    theta = 0
                
                # This exists to allow users to separate points based off AOA. 
                # It isn't used right now bc theta_bounds[1] will catch all points
                i = 0
                while(theta > self.theta_bounds[i]):
                    i = i + 1
                    if(i == len(self.theta_bounds)):
                        break
                self.tList[i].append(theta)
                self.rList[i].append(r)
                self.snrList[i].append(snr)
                self.majorPlotList[i].append([r, snr])

        # Since theta_bounds[1] = +91, all points are in curve1
        self.rangeSNR_curve0.setData(pos=self.majorPlotList[0])
        self.rangeSNR_curve1.setData(pos=self.majorPlotList[1])
        self.rangeSNR_curve2.setData(pos=self.majorPlotList[2])
        self.rangeSNR_curve3.setData(pos=self.minorPlotList[0])
        self.rangeSNR_curve4.setData(pos=self.minorPlotList[1])
        self.rangeSNR_curve5.setData(pos=self.minorPlotList[2])


