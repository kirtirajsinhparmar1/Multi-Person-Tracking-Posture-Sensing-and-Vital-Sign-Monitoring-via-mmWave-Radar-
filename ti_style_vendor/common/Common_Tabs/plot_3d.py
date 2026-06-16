# Vendored from: tools\visualizers\Applications_Visualizer\common\Common_Tabs\plot_3d.py
import logging

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide2.QtGui import QPixmap
from PySide2.QtGui import QImage

from graph_utilities import eulerRot, getBoxArcs, getBoxArcs2D ,getBoxLines, getSquareLines
from gl_text import GLTextItem


log = logging.getLogger(__name__)

# Different methods to color the points 
COLOR_MODE_SNR = 'SNR'
COLOR_MODE_HEIGHT = 'Height'
COLOR_MODE_DOPPLER = 'Doppler'
COLOR_MODE_TRACK = 'Associated Track'

class Plot3D():
    def __init__(self, demo=None):
        # Create plot
        self.plot_3d = gl.GLViewWidget()
        # Sets background to a pastel grey
        self.plot_3d.setBackgroundColor(70, 72, 79)
        # Create the background grid
        gz = gl.GLGridItem()
        self.plot_3d.addItem(gz)

        # Create scatter plot for point cloud
        self.scatter = gl.GLScatterPlotItem(size=5)
        self.scatter.setData(pos=np.zeros((1,3)))
        self.plot_3d.addItem(self.scatter)
        self.boundaryBoxList = []

        # Create scatter plot for clusters
        self.scatterClusters = gl.GLScatterPlotItem(size=10)
        self.scatterClusters.setData(pos=np.zeros((1,3)))
        self.plot_3d.addItem(self.scatterClusters)

        # demo specific
        self.demo = demo
        # Sensor position
        self.xOffset = 0
        self.yOffset = 0
        self.sensorHeight = 0
        self.az_tilt = 0
        self.elev_tilt = 0
    
        # Create box to represent EVM
        evmSizeX = 0.0625
        evmSizeZ = 0.125
        verts = np.empty((2,3,3))
        verts[0,0,:] = [-evmSizeX, 0, evmSizeZ]
        verts[0,1,:] = [-evmSizeX,0,-evmSizeZ]
        verts[0,2,:] = [evmSizeX,0,-evmSizeZ]
        verts[1,0,:] = [-evmSizeX, 0, evmSizeZ]
        verts[1,1,:] = [evmSizeX, 0, evmSizeZ]
        verts[1,2,:] = [evmSizeX, 0, -evmSizeZ]
        self.evmBox = gl.GLMeshItem(vertexes=verts,smooth=False,drawEdges=True,edgeColor=pg.glColor('r'),drawFaces=False)
        self.plot_3d.addItem(self.evmBox)

        # Initialize other elements
        self.boundaryBoxViz = []
        self.coordStr = []
        self.classifierStr = []
        self.ellipsoids = []
        self.poseLabelItems = {}
        self.poseLabelsFailed = False
        self.humanModelRenderer = None
        self.humanModelMode = 'overlay_box'
        self.humanModelsFailed = False
        self.poseGroundPlaneItem = None
        self.poseGroundGridItem = None
        self.plotComplete = 1

        self.zRange = [-3, 3]

        # Persistent point cloud
        self.previousClouds = []
        if self.demo == None:
            self.numPersistentFrames = int(3)
        elif self.demo == "LPD":
            self.numPersistentFrames = int(20)
            self.plot_3d.pan(0, 1, 0)

        self.mpdZoneType = None
        self.snapTo2D = None
        self.modeSwitchLabel = None

    def setHumanModelRenderer(self, renderer, mode='overlay_box'):
        self.humanModelRenderer = renderer
        self.humanModelMode = mode or 'overlay_box'
        self.humanModelsFailed = False

    def updateHumanPoseModels(self, model_records):
        if self.humanModelRenderer is None or self.humanModelsFailed:
            return
        try:
            self.humanModelRenderer.update_models(model_records or [])
        except Exception as exc:
            self.humanModelsFailed = True
            log.warning("Human pose models disabled after update failure: %s", exc)
            try:
                self.humanModelRenderer.clear()
            except Exception:
                pass

    def clearHumanPoseModels(self):
        if self.humanModelRenderer is not None:
            try:
                self.humanModelRenderer.clear()
            except Exception:
                pass

    def setPoseGroundPlane(self, enabled=True, ground_z=0.0, size=8.0, grid=True, alpha=0.18):
        self.clearPoseGroundPlane()
        if not enabled:
            return
        try:
            half = float(size) * 0.5
            y_max = float(size)
            z = float(ground_z)
            alpha = max(0.0, min(1.0, float(alpha)))
            verts = np.array(
                [
                    [-half, 0.0, z],
                    [half, 0.0, z],
                    [half, y_max, z],
                    [-half, y_max, z],
                ],
                dtype=float,
            )
            faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
            plane = gl.GLMeshItem(
                vertexes=verts,
                faces=faces,
                smooth=False,
                drawEdges=False,
                drawFaces=True,
                color=(0.22, 0.24, 0.27, alpha),
            )
            plane.setGLOptions('translucent')
            self.plot_3d.addItem(plane)
            self.poseGroundPlaneItem = plane

            if grid:
                grid_item = gl.GLGridItem()
                try:
                    grid_item.setSize(x=float(size), y=float(size), z=0.0)
                    grid_item.setSpacing(x=0.5, y=0.5, z=0.5)
                except TypeError:
                    grid_item.setSize(float(size), float(size), 0.0)
                    grid_item.setSpacing(0.5, 0.5, 0.5)
                grid_item.translate(0.0, half, z + 0.002)
                self.plot_3d.addItem(grid_item)
                self.poseGroundGridItem = grid_item
        except Exception as exc:
            log.warning("Pose ground plane disabled after setup failure: %s", exc)
            self.clearPoseGroundPlane()

    def clearPoseGroundPlane(self):
        for attr in ('poseGroundGridItem', 'poseGroundPlaneItem'):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    self.plot_3d.removeItem(item)
                except Exception:
                    try:
                        item.setVisible(False)
                    except Exception:
                        pass
                setattr(self, attr, None)

    def setTargetBoxesVisible(self, visible):
        for item in getattr(self, 'ellipsoids', []):
            try:
                item.setVisible(bool(visible))
            except Exception:
                pass

    def updatePoseLabels(self, label_records):
        if self.poseLabelsFailed:
            return

        active_tids = set()
        try:
            for record in label_records or []:
                tid = int(record.get("tid"))
                text = str(record.get("text", ""))
                x = float(record.get("x", 0.0))
                y = float(record.get("y", 0.0))
                z = float(record.get("z", 0.0))
                if not text or not np.all(np.isfinite([x, y, z])):
                    continue

                color = self._poseLabelColor(record.get("final_label", ""))
                item = self.poseLabelItems.get(tid)
                if item is None:
                    item = GLTextItem(X=x, Y=y, Z=z, text=text, force_enabled=True, color=color)
                    item.setGLViewWidget(self.plot_3d)
                    item.setVisible(False)
                    self.plot_3d.addItem(item)
                    self.poseLabelItems[tid] = item

                item.setText(text)
                item.setX(x)
                item.setY(y)
                item.setZ(z)
                item.setColor(color)
                item.setVisible(True)
                active_tids.add(tid)

            for tid, item in list(self.poseLabelItems.items()):
                if tid not in active_tids:
                    item.setVisible(False)
        except Exception as exc:
            self.poseLabelsFailed = True
            log.warning("3D pose labels disabled after update failure: %s", exc)
            for item in self.poseLabelItems.values():
                try:
                    item.setVisible(False)
                except Exception:
                    pass

    def _poseLabelColor(self, final_label):
        label = str(final_label).upper()
        if label == "FALLING":
            return (255, 70, 70, 255)
        if label == "MOVING":
            return (255, 190, 50, 255)
        if label == "SITTING":
            return (90, 170, 255, 255)
        if label == "LYING":
            return (190, 120, 255, 255)
        if label in {"UNKNOWN", "LOW_QUALITY", "LOW_POINTS", "NO_POINTS", "NO_POSE", "WARMUP"}:
            return (180, 180, 180, 255)
        return (70, 230, 120, 255)

    def updatePointCloud(self, outputDict):
        if ('pointCloud' in outputDict and 'numDetectedPoints' in outputDict):
            pointCloud = outputDict['pointCloud']
            pointCloud = np.asarray(pointCloud)

            # Rotate point cloud and tracks to account for elevation and azimuth tilt
            if (self.elev_tilt != 0 or self.az_tilt != 0):
                for i in range(outputDict['numDetectedPoints']):
                    rotX, rotY, rotZ = eulerRot (pointCloud[i,0], pointCloud[i,1], pointCloud[i,2], self.elev_tilt, self.az_tilt)
                    pointCloud[i,0] = rotX
                    pointCloud[i,1] = rotY
                    pointCloud[i,2] = rotZ

            # Shift points to account for sensor height
            if (self.sensorHeight != 0):
                pointCloud[:,2] = pointCloud[:,2] + self.sensorHeight

            if self.demo == "LPD":
                outputDict['pointCloud'] = self.filterPointCloud(outputDict['pointCloud'])
            # Add current point cloud to the cumulative cloud if it's not empty
            self.previousClouds.append(outputDict['pointCloud'])
        else:
            # if there is no point cloud, append an empty array
            self.previousClouds.append([])

        # If we have more point clouds than needed, stated by numPersistentFrames, delete the oldest ones 
        while(len(self.previousClouds) > self.numPersistentFrames):
            self.previousClouds.pop(0)
            
    # Add a boundary box to the boundary boxes tab
    def addBoundBox(self, name, minX=0, maxX=0, minY=0, maxY=0, minZ=0, maxZ=0, color='b'):
        newBox = gl.GLLinePlotItem()
        newBox.setVisible(True)
        self.plot_3d.addItem(newBox)     

        if ('mpdBoundaryArc' in name):
            try:
                if(self.snapTo2D.checkState() == 0):
                    boxLines = getBoxArcs(minX,minY,minZ,maxX,maxY,maxZ)
                elif(self.snapTo2D.checkState() == 2):
                    boxLines = getBoxArcs2D(minX,minY,0,maxX,maxY,0)
                
                
                boxColor = pg.glColor('b')
                newBox.setData(pos=boxLines,color=boxColor,width=2,antialias=True,mode='lines')

                # TODO add point boundary back into visualizer

                boundaryBoxItem = {
                    'plot': newBox,
                    'name': name,
                    'boxLines': boxLines,
                    'minX': float(minX),
                    'maxX': float(maxX),
                    'minY': float(minY),
                    'maxY': float(maxY),
                    'minZ': float(minZ),
                    'maxZ': float(maxZ)
                }   

                self.boundaryBoxViz.append(boundaryBoxItem) 
                self.plot_3d.addItem(newBox)
                self.boundaryBoxList.append(newBox)
            except:
                # You get here if you enter an invalid number
                # When you enter a minus sign for a negative value, you will end up here before you type the full number
                pass
        else:
            try:
                if(self.snapTo2D.checkState() == 0):
                    boxLines = getBoxLines(minX,minY,minZ,maxX,maxY,maxZ)
                elif(self.snapTo2D.checkState() == 2):
                    boxLines = getSquareLines(minX,minY,0,maxX,maxY,0)
 
                boxColor = pg.glColor(color)
                newBox.setData(pos=boxLines,color=boxColor,width=2,antialias=True,mode='lines')

                # TODO add point boundary back into visualizer

                boundaryBoxItem = {
                    'plot': newBox,
                    'name': name,
                    'boxLines': boxLines,
                    'minX': float(minX),
                    'maxX': float(maxX),
                    'minY': float(minY),
                    'maxY': float(maxY),
                    'minZ': float(minZ),
                    'maxZ': float(maxZ)
                }   

                self.boundaryBoxViz.append(boundaryBoxItem) 
                self.plot_3d.addItem(newBox)
                self.boundaryBoxList.append(newBox)
            except:
                # You get here if you enter an invalid number
                # When you enter a minus sign for a negative value, you will end up here before you type the full number
                pass

    def removeAllBoundBoxes(self):
        for item in self.boundaryBoxList:
            item.setVisible(False)
        if(self.snapTo2D is not None):
            self.snapTo2D.setEnabled(1)
        if(self.modeSwitchLabel is not None):
            self.modeSwitchLabel.setText('Two Pass Mode Disabled')
            self.modeSwitchLabel.setStyleSheet("background-color: lightgrey; border: 1px solid black;")
        self.boundaryBoxList.clear()

    def changeBoundaryBoxColor(self, box, color):
        box['plot'].setData(pos=box['boxLines'], color=pg.glColor(color),width=2,antialias=True,mode='lines')

    def changeBoundaryBoxBold(self, box, bold, strip):
        if bold:
            box['plot'].setData(width=8)
        else:
            box['plot'].setData(width=2)
        
        if strip:
            box['plot'].setData(mode='line_strip')
        else:
            box['plot'].setData(mode='lines')


    def parseTrackingCfg(self, args):
        self.maxTracks = int(args[4])

    def parseBoundaryBox(self, args):
        self.snapTo2D.setEnabled(0)

        if (args[0] == 'SceneryParam' or args[0] == 'boundaryBox'):
            leftX = float(args[1])
            rightX = float(args[2])
            nearY = float(args[3])
            farY = float(args[4])
            bottomZ = float(args[5])
            topZ = float(args[6])
                        
            self.addBoundBox('trackerBounds', leftX, rightX, nearY, farY, bottomZ, topZ)
        elif (args[0] == 'zoneDef'):
            zoneIdx = int(args[1])
            minX = float(args[2])
            maxX = float(args[3])
            minY = float(args[4])
            maxY = float(args[5])
            # Offset by 3 so it is in center of screen
            minZ = float(args[6]) + self.sensorHeight
            maxZ = float(args[7]) + self.sensorHeight

            name = 'occZone' + str(zoneIdx)
            self.addBoundBox(name, minX, maxX, minY, maxY, minZ, maxZ)
        elif (args[0] == 'mpdBoundaryBox'):
            zoneIdx = int(args[1])
            minX = float(args[2])
            maxX = float(args[3])
            minY = float(args[4])
            maxY = float(args[5])
            minZ = float(args[6])
            maxZ = float(args[7])
            name = 'mpdBoundaryBox' + str(zoneIdx)
            self.addBoundBox(name, minX, maxX, minY, maxY, minZ, maxZ)
        elif (args[0] == 'mpdBoundaryArc'):
            zoneIdx = int(args[1])
            minR = float(args[2])
            maxR = float(args[3])
            minTheta = float(args[4])
            maxTheta = float(args[5])
            minZ = float(args[6])
            maxZ = float(args[7])
            name = 'mpdBoundaryArc' + str(zoneIdx)
            self.addBoundBox(name, minR, maxR, minTheta, maxTheta, minZ, maxZ)

        # TODO print out somewhere these boundary boxes

    def parseSensorPosition(self, args, is_x843):
        #print("parsing sensor position")
        if (is_x843):
            self.sensorHeight = float(args[1])
            self.az_tilt = float(args[2])
            self.elev_tilt = float(args[3])
        else:
            self.xOffset = float(args[1])
            self.yOffset = float(args[2])
            self.sensorHeight = float(args[3])
            self.az_tilt = float(args[4])
            self.elev_tilt = float(args[5])

        self.evmBox.resetTransform()
        if self.demo == "LPD": # TODO REMOVE THIS AFTER FIXING DEMO IMAGE TO PARSE ELEV CORRECTLY
            self.elev_tilt = -1 * self.elev_tilt
            self.az_tilt = -1 * self.az_tilt
        self.evmBox.rotate(-1 * self.elev_tilt, 1, 0, 0)
        self.evmBox.rotate(-1 * self.az_tilt, 0, 0, 1)
        self.evmBox.translate(0, 0, self.sensorHeight)

        # TODO update text showing sensor position text?
    def filterPointCloud(self, pointCloud):
        # filter the point cloud to only include points within the bounds of the boundary boxes
        newPointCloud = []
        #print("Empty new point cloud? : " + str(newPointCloud))
        for point in pointCloud:
            for boxNum in range(len(self.boundaryBoxViz)):
                # check if the point is within the bounds of the box
                if (self.boundaryBoxViz[boxNum]['minX'] <= point[0] and point[0] <= self.boundaryBoxViz[boxNum]['maxX'] and
                    self.boundaryBoxViz[boxNum]['minY'] <= point[1] and point[1] <= self.boundaryBoxViz[boxNum]['maxY'] and
                    self.boundaryBoxViz[boxNum]['minZ'] <= point[2] and point[2] <= self.boundaryBoxViz[boxNum]['maxZ']):
                    newPointCloud.append(point)
                    # TODO STORE WHICH BOX THIS PIN IS INSIDE OF AND USE IT TO COLOR POINT TO THE BOX AND PROB LINES
                    break # if within a box then move on to next point
        return np.asarray(newPointCloud)
