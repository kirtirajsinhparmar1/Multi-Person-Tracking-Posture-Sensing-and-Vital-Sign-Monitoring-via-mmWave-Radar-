# Vendored from: tools\visualizers\Applications_Visualizer\common\Demo_Classes\out_of_box_x844.py
# General Library Imports
import copy
import string
import math

from Demo_Classes.people_tracking import PeopleTracking

class OOBx844(PeopleTracking):
    def __init__(self):
        PeopleTracking.__init__(self)

    def updateGraph(self, outputDict):
        PeopleTracking.updateGraph(self, outputDict)