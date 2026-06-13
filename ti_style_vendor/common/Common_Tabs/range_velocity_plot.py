# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\range_velocity_plot.py
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import copy

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QGraphicsWidget

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from Common_Tabs.plot_2d import Plot2D

class RangeVelocityPlotObject():
    def __init__(self):
        # Create plot
        self.rangeVellayout = pg.GraphicsLayoutWidget()
        self.rangeVellayout.setBackground('w')
        self.rangeVelplot2d = self.rangeVellayout.addPlot(title='Range vel Comp')
        self.rangeVelplot2d.showGrid(x=True,y=True)

        self.rangeVel_curve0 = pg.ScatterPlotItem(brush=pg.mkBrush(255, 0, 0, 255), hoverable = True)
        self.rangeVel_curve1 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 255, 0, 255))
        self.rangeVel_curve2 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 0,255, 255))

        self.rangeVel_curve3 = pg.ScatterPlotItem(brush=pg.mkBrush(255, 0, 0, 255), hoverable = True, symbol='s')
        self.rangeVel_curve4 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 255, 0, 255), symbol='s')
        self.rangeVel_curve5 = pg.ScatterPlotItem(brush=pg.mkBrush(0, 0,255, 255), symbol='s')

 
        self.rangeVelplot2d.addItem(self.rangeVel_curve1)
        self.rangeVelplot2d.addItem(self.rangeVel_curve2)
        self.rangeVelplot2d.addItem(self.rangeVel_curve0)
        self.rangeVelplot2d.addItem(self.rangeVel_curve3)
        self.rangeVelplot2d.addItem(self.rangeVel_curve4)
        self.rangeVelplot2d.addItem(self.rangeVel_curve5)

        self.yMinFFT = 0
        self.yMaxFFT = 50
        self.xMaxFFT = 12
        self.xMin = 0
        self.rangeVelplot2d.setXRange(self.xMin, self.xMaxFFT,padding=0.01)
        self.rangeVelplot2d.setYRange(-2, 2,padding=0.01)
        # self.rangeVelplot2d.setLimits(xMin=-0.1, xMax=20, yMin=-2, yMax=2)
        self.rangeVelplot2d.disableAutoRange()

        self.theta_bounds = [-45, 45]
        self.clearPlot()

    def addPointsToLists(self,outputDict):
        print("ADD THIS")

    def clearPlot(self):
        self.rList = [[]]
        self.tList = [[]]
        self.velList = [[]]
        self.minorPlotList = [[]]
        self.majorPlotList = [[]]
        self.numVelAboveThreMajor = 0
        self.numVelAboveThreMinor = 0
        self.velThre = 0
        self.localFrameCounter = 1
        for i in range(len(self.theta_bounds)):
            self.rList.append([])
            self.tList.append([])
            self.velList.append([])
            self.majorPlotList.append([])
            self.minorPlotList.append([])


    def updateGraph(self,outputDict):
        self.velThre = outputDict["plotPointVelThre"]
        if(outputDict is not None and 'pointCloud' in outputDict):
            for point in outputDict['pointCloud']:
                x = point[0]
                y = point[1]
                z = point[2]
                vel = point[3]
                if(abs(vel) >= self.velThre):

                    r = np.sqrt(np.power(x,2) + np.power(y,2) + np.power(z,2))
                    if(y>0):
                        theta = np.arctan(x / y) * 180 / 3.14159
                    else:
                        theta = 0
                    i = 0
                    while(theta > self.theta_bounds[i]):
                        i = i + 1
                        if(i == len(self.theta_bounds)):
                            break
                    self.tList[i].append(theta)
                    self.rList[i].append(r)
                    self.velList[i].append(vel)
                    if (point[7] == 1):
                        self.numVelAboveThreMajor = self.numVelAboveThreMajor + 1
                    elif (point[7] == 2):
                        self.numVelAboveThreMinor = self.numVelAboveThreMinor + 1
                    if (point[7] == 1):
                        self.majorPlotList[i].append([r, vel])
                    elif (point[7] == 2):
                        self.minorPlotList[i].append([r, vel])

        print("Avg # hi-vel points, major : " + str(round(self.numVelAboveThreMajor / self.localFrameCounter, 2)) + "\t minor : " + str(round(self.numVelAboveThreMajor / self.localFrameCounter, 2)))
        self.localFrameCounter = self.localFrameCounter + 1
        self.rangeVel_curve0.setData(pos=self.majorPlotList[0])
        self.rangeVel_curve1.setData(pos=self.majorPlotList[1])
        self.rangeVel_curve2.setData(pos=self.majorPlotList[2])
        self.rangeVel_curve3.setData(pos=self.minorPlotList[0])
        self.rangeVel_curve4.setData(pos=self.minorPlotList[1])
        self.rangeVel_curve5.setData(pos=self.minorPlotList[2])
        return [str(round(self.numVelAboveThreMajor / self.localFrameCounter, 2)), str(round(self.numVelAboveThreMinor / self.localFrameCounter, 2))]