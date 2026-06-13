# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\out_of_box_x432.py
# General Library Imports
import copy
import string
import math

# Local Imports
from Demo_Classes.people_tracking import PeopleTracking
# Logger
import logging
log = logging.getLogger(__name__)

class OOBx432(PeopleTracking):
    def __init__(self):
        PeopleTracking.__init__(self)

    def updateGraph(self, outputDict):
        PeopleTracking.updateGraph(self, outputDict)
        # Update boundary box colors based on results of Occupancy State Machine
        if ('enhancedPresenceDet' in outputDict):
            enhancedPresenceDet = outputDict['enhancedPresenceDet']
            for box in self.boundaryBoxViz:
                if ('mpdBoundary' in box['name']):
                    # Get index of the occupancy zone from the box name
                    boxIdx = int(box['name'].lstrip(string.ascii_letters))
                    # out of bounds
                    if (boxIdx >= len(enhancedPresenceDet)):
                        log.warning("Warning : Occupancy results for box that does not exist")
                    elif (enhancedPresenceDet[boxIdx] == 0):
                        self.changeBoundaryBoxColor(box, 'b') # Zone unoccupied
                    elif (enhancedPresenceDet[boxIdx] == 1):
                        self.changeBoundaryBoxColor(box, 'y') # Minor Motion Zone Occupancy 
                    elif (enhancedPresenceDet[boxIdx] == 2):
                        self.changeBoundaryBoxColor(box, 'r') # Major Motion Zone Occupancy
                    else:
                        log.error("Invalid result for Enhanced Presence Detection TLV")


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
