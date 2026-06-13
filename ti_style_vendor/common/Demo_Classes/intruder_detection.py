# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\intruder_detection.py
# General Library Imports
import time

# PyQt Imports
from PySide2.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QWidget, QGridLayout, QHBoxLayout, QTabWidget
from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QPixmap, QFont
import pyqtgraph as pg


# Local Imports
from Common_Tabs.plot_1d import Plot1D
from Common_Tabs.plot_2d import Plot2D

# Logger
import logging
log = logging.getLogger(__name__)


###################################################################################################
# Intruder Detection
###################################################################################################

class IntruderDetection(Plot1D):
    def __init__(self):
        # This demo utilizes the 2D plot functionality
        Plot1D.__init__(self,'intruder')  
        
        # Demo Specific Initializations
        self.occBoxes = [] #occupancy box details - for plotting 
        self.occSignals = {} # contains the signal data where key is box number
        self.numBoxes = 0   
        self.colors = ['k', 'g', 'b', 'c', 'y', 'm', 'd', 'r']

        # To keep track of plotting time
        self.plotStart = 0
        
        # Variables from .cfg file (not required)
        self.channelCfgRX = 0
        self.channelCfgTX = 0

        # hard coded to test Kristiens non cfg image:
        #print("hard code: ")
        #for x in range(7):
        #    if self.numBoxes == 7:
        #        break
        #    self.occSignals[self.numBoxes] = [] # this contains the raw data itself
        #    tempItem = pg.PlotCurveItem(pen=pg.mkPen(width=3, color=pg.intColor(self.numBoxes)))
        #    self.OccData.append(tempItem)
        #    self.occThreshPlot.addItem(self.OccData[self.numBoxes])
        #    print("added box# " + str(self.numBoxes) + " manually!")
        #    self.numBoxes += 1

    # Required Function
    # Set up the GUI for this demo
    # gridLayout:   QGridLayout() for whole window
    # demoTabs:     QTabWidget() for holding GUI tabs
    # device:       device name being used
    def setupGUI(self, gridLayout, demoTabs, device):
        # Init setup pane on left hand side
        statBox = self.initStatsPane()
        gridLayout.addWidget(statBox,2,0,1,1)

        # Create a pane for our demo
        self.myTab = QWidget()
        vboxSurface = QVBoxLayout()

        # occupancy boxes inits
        hbox = QHBoxLayout()
        self.occBoxPlot = pg.PlotWidget()
        self.occBoxPlot.setBackground('w')
        self.occBoxPlot.showGrid(x=True,y=True,alpha=0.2)
        self.occBoxPlot.setXRange(-1.5,1.5, padding=0.05)
        self.occBoxPlot.setYRange(-2,2, padding=0.05)
        self.occBoxPlot.setLabel('bottom', 'X, m')
        self.occBoxPlot.setLabel('left', 'Y, m')
        self.occBoxPlot.setMouseEnabled(False, False)
        self.occBoxPlot.setAspectLocked(lock=True, ratio=2)
        hbox.addWidget(self.occBoxPlot)
        self.occBoxRangeX = [0,0] # xMax, xMin  
        self.occBoxRangeY = [0,0] # yMax, yMin

        # occupancy threshold plot inits
        self.occThreshPlot.setFixedWidth(1000)
        hbox.addWidget(self.occThreshPlot)
        vboxSurface.addLayout(hbox)

        # Add pane to actual window
        self.myTab.setLayout(vboxSurface)
        demoTabs.addTab(self.myTab, 'Intruder Detection')
        demoTabs.setCurrentIndex(0)


    # Required Function if some statistics are to be displayed
    def initStatsPane(self):
        statBox = QGroupBox('Statistics')
        self.frameNumDisplay = QLabel('Frame: 0')
        self.plotTimeDisplay = QLabel('Plot Time: 0 ms')
        self.ARMprocTimeData = QLabel('ARM Processing Time: 0 ms')
        self.DSPprocTimeData = QLabel('DSP Processing Time: 0 ms')
        self.UARTTransmitTime = QLabel('UART Transmit Time: 0 ms')

        self.statsLayout = QVBoxLayout()
        self.statsLayout.addWidget(self.frameNumDisplay)
        self.statsLayout.addWidget(self.plotTimeDisplay)
        self.statsLayout.addWidget(self.ARMprocTimeData)
        self.statsLayout.addWidget(self.DSPprocTimeData)
        self.statsLayout.addWidget(self.UARTTransmitTime)
        statBox.setLayout(self.statsLayout)
        return statBox
    
    # Required Function
    # Updates the plot, called after parsing each frame
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def updateGraph(self, outputDict):
        # Update start time
        self.plotStart = int(round(time.time()*1000))
        
        # Check that our data is valid, add it to internal variable to process
        if ('occBoxSignal' in outputDict):
            #print("Printing occBoxSignal: ")
            #print(outputDict['occBoxSignal'])
            for x in range(self.numBoxes):
                if len(self.occSignals[x]) >= 50: 
                    self.occSignals[x].pop(0)
                    #print("popping oldest element")
                #print(x)
                self.occSignals[x].append(outputDict['occBoxSignal'][x])
                #print("Length of occSignal for a single box: " + str(len(self.occSignals[x])))
            
        
                
        outputDict['occPlot'] = self.occSignals
        self.update1DGraph(outputDict) # Update the occupancy plot

        for x in range(1,self.numBoxes):
            if outputDict['occBoxDec'][x] == 1:
                #colors = [(255,0,0), (0,255,0), (0,0,255), (255,255,0), (0,255,255), (255,0,255), (128,0,128), (128,128,0), (0,128,128)]
                color = self.colors[x % len(self.colors)]
                self.occBoxes[x].setBrush(pg.mkBrush(color))
                #print("set to change the color")
            else:
                #since I am not setting it back to clear, it should stay red once triggered
                self.occBoxes[x].setBrush(pg.mkBrush((255,0,0,0)))
            
        # Process / Plot our data
        # Call graphDone
        self.graphDone(outputDict)

    # Required Function
    # Generally called by updateGraph
    #
    # outputDict:   Dictionary of all TLV info, updated with each frame
    def graphDone(self, outputDict):
        plotTime = int(round(time.time()*1000)) - self.plotStart
        self.plotTimeDisplay.setText('Plot Time: ' + str(plotTime) + 'ms')
        self.plotComplete = 1

        if ('frameNum' in outputDict):
            self.frameNumDisplay.setText('Frame: ' + str(outputDict['frameNum']))
        
        if ('ARMprocTimeData' in outputDict):
            self.ARMprocTimeData.setText('ARM Processing Time: ' + str(outputDict['ARMprocTimeData'])+ 'ms')

        if ('DSPprocTimeData' in outputDict):
            self.DSPprocTimeData.setText('DSP Processing Time: ' + str(outputDict['DSPprocTimeData'])+ 'ms')

        if ('UARTTransmitTime' in outputDict):
            self.UARTTransmitTime.setText('UART Transmit Time: ' + str(outputDict['UARTTransmitTime'])+ 'ms')

    
    # Parses the occupancy boxes from the cfg file - initializes the signals and boxes
    def parseOccCfg(self, args):
        
        self.occSignals[self.numBoxes] = [] # this contains the raw data itself
        # TODO Change the way that the colors are done because right now it is hard to tell which one is which        

        tempItem = pg.PlotCurveItem(pen=pg.mkPen(width=3, color=self.colors[self.numBoxes % len(self.colors)]), name = "Box " + str(self.numBoxes))
        self.OccData.append(tempItem)
        self.occThreshPlot.addItem(self.OccData[self.numBoxes])
        #print("added occData item through CFG!")
        
        # add a rectangle item to occBoxPlot
        xMin = float(args[2])
        xMax = float(args[3])
        yMin = float(args[4])
        yMax = float(args[5])
        zMin = float(args[6])
        zMax = float(args[7])

        #print("xMin: " + str(xMin))
        #print("xMax: " + str(xMax))
        #print("yMin: " + str(yMin))
        #print("yMax: " + str(yMax))
        #print("zMin: " + str(zMin))
        #print("zMax: " + str(zMax))

        
        rect = pg.QtGui.QGraphicsRectItem(xMin,yMin,abs(xMin-xMax),abs(yMin-yMax))
        rect.setPen(pg.mkPen(width=2, color='k'))

        if self.numBoxes == 0:
            temp = "Car Interior"
            boxWidth = abs(xMin-xMax)
            boxHeight = abs(yMin-yMax)
            scaleFactor = (boxWidth + boxHeight) / (50) # this is an arbitrary number
            scaleFactor = max(scaleFactor,1)   
            fill_temp = 'w'
            color_temp = 'k' 
        else: 
            temp = str(self.numBoxes)
            scaleFactor = 1
            fill_temp = None
            color_temp = 'k'

        label = pg.TextItem(text=temp, color=color_temp, anchor=(0.5,0.5), fill=fill_temp)



        label.setPos(xMin + (abs(xMin-xMax)/2), yMin + (abs(yMin-yMax)/2))
        label.setFont(QFont("Arial", pointSize=15*scaleFactor))
        label.setZValue(1) # this will put the label on top of the box


        self.occBoxPlot.addItem(rect)
        self.occBoxes.append(rect)
        self.occBoxPlot.addItem(label)
        self.occBoxPlot.setAspectLocked(lock=True, ratio=1)

        if self.occBoxRangeX[0] < xMax: 
            self.occBoxRangeX[0] = xMax
        if self.occBoxRangeX[1] > xMin:
            self.occBoxRangeX[1] = xMin
        if self.occBoxRangeY[0] < yMax:
            self.occBoxRangeY[0] = yMax
        if self.occBoxRangeY[1] > yMin:
            self.occBoxRangeY[1] = yMin
        self.occBoxPlot.setXRange(self.occBoxRangeX[1],self.occBoxRangeX[0], padding=0.05)
        self.occBoxPlot.setYRange(self.occBoxRangeY[1],self.occBoxRangeY[0], padding=0.05)
        self.numBoxes += 1

    # Adds the threshold lines for refernce
    def parseDetAdvCfg(self, args):
        boxNum = int(args[1])
        threshHold = int(args[2])
        tempItem = pg.InfiniteLine(pos=threshHold, angle=0, movable=False, pen=pg.mkPen(style=Qt.DashLine, width=2,color=self.colors[boxNum % len(self.colors)]))
        self.occThreshPlot.addItem(tempItem)
        self.occThreshPlot.show()

    #Adds the sensor position to the plot for reference
    def parseSensorPositionCfg(self, args):
        x = float(args[1]) 
        y = float(args[2])
        # add a circle item to occBoxPlot
        circle = pg.QtGui.QGraphicsEllipseItem(x-0.10,y-0.10,0.2,0.2)
        circle.setPen(pg.mkPen(width=2, color='k'))
        #circle.setBrush(pg.mkBrush('k')) # this sets the background a different color
        self.occBoxPlot.addItem(circle)
        # add a label to the center of the circle
        label = pg.TextItem(text="SENSOR", color='r',fill='w', anchor=(0.5,0.5))
        label.setFont(QFont("Arial", pointSize=10))
        label.setPos(x,y)
        label.setZValue(100)
        self.occBoxPlot.addItem(label)
