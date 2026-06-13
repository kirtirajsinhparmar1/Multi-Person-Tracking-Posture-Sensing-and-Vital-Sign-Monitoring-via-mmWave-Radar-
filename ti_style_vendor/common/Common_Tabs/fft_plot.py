# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\fft_plot.py
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import copy

from PySide2.QtWidgets import QGroupBox, QGridLayout, QLabel, QWidget, QVBoxLayout, QTabWidget, QComboBox, QCheckBox, QSlider, QFormLayout, QGraphicsWidget

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from Common_Tabs.plot_2d import Plot2D

class FFTPlotObject():
    def __init__(self):
        
        # Arbitrary Constants for setup
        self.yMinFFT = 0
        self.yMaxFFT = 40
        self.xMax = round(256/2)
        self.xMin = 0
        
        # Create plot
        self.fftlayout = pg.GraphicsLayoutWidget()
        self.fftlayout.setBackground('w')
        self.fftplot2d = self.fftlayout.addPlot(title='FFT Data (with A = 0.90 Alpha Filter)', labels= {'left': ("Magnitude (dB)"), 'bottom': ("FFT Index")})
        self.fftplot2d.showGrid(x=True,y=False)
        self.fft_curve = []
        
        # Hold previous fft to implement alpha filter
        self.prev_abs_fft_data = [[],[],[],[],[],[]]
        self.fft_curve.append(pg.PlotCurveItem(name="T1R1", pen=pg.mkPen(width=3, color='r')))
        self.fft_curve.append(pg.PlotCurveItem(name="T1R2", pen=pg.mkPen(width=3, color='b')))
        self.fft_curve.append(pg.PlotCurveItem(name="T1R3", pen=pg.mkPen(width=3, color='g')))
        self.fft_curve.append(pg.PlotCurveItem(name="T2R1", pen=pg.mkPen(width=3, color='y')))
        self.fft_curve.append(pg.PlotCurveItem(name="T2R2", pen=pg.mkPen(width=3, color='c')))
        self.fft_curve.append(pg.PlotCurveItem(name="T2R3", pen=pg.mkPen(width=3, color='m')))
        
        # Alpha Filter value for stability
        self.alpha = 0.9
        
        # Add Legend
        legend = self.fftplot2d.addLegend(offset=(-30, 30)) # Offset the legend from the top-right corner
        # Add Curves
        self.fftplot2d.addItem(self.fft_curve[0])
        self.fftplot2d.addItem(self.fft_curve[1])
        self.fftplot2d.addItem(self.fft_curve[2])
        self.fftplot2d.addItem(self.fft_curve[3])
        self.fftplot2d.addItem(self.fft_curve[4])
        self.fftplot2d.addItem(self.fft_curve[5])

        # Set up plot
        self.fftplot2d.setXRange(self.xMin, self.xMax,padding=0.01)
        self.fftplot2d.setYRange(self.yMinFFT, self.yMaxFFT,padding=0.01)
        self.fftplot2d.disableAutoRange()


    def updateGraph(self,outputDict):
        # If we have raw data
        if(outputDict is not None):
            if("rawADCData" in outputDict):
                numSamples = outputDict["numADCSamples"]
                
                # Reset the X range depending on the number of samples
                if(self.xMax != numSamples):
                    self.xMax = numSamples
                    self.fftplot2d.setXRange(self.xMin, self.xMax,padding=0.01)

                x = range(numSamples)
                y = outputDict['rawADCData']
                numVirtualChannels = outputDict['numVirtualChannels']
                for i in range(numVirtualChannels):
                    # Separate data for each TXRX pair channel
                    channelData = y[(0+i*numSamples):(numSamples+i*numSamples)]
                    # Small alpha-filter to encourage stability in FFT plot
                    absfft = np.abs(np.fft.fft(channelData)) / numSamples
                    if(len(self.prev_abs_fft_data[i]) == 0):
                        self.fft_curve[i].setData(20*np.log10(absfft[0:round(numSamples/2)]))
                        self.prev_abs_fft_data[i] = absfft[0:round(numSamples/2)]
                    else:
                        filtered_data = self.alpha * self.prev_abs_fft_data[i] + (1-self.alpha) * absfft[0:round(numSamples/2)]
                        self.fft_curve[i].setData(20*np.log10(filtered_data))
                        self.prev_abs_fft_data[i] = filtered_data
