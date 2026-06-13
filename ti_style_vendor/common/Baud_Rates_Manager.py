# Vendored from: tools\visualizers\Applications_Visualizer\common\Baud_Rates_Manager.py
# General Library Imports
import json
import time
from serial.tools import list_ports
import os
import subprocess
import sys
from contextlib import suppress

# PyQt Imports
from PySide2 import QtGui
from PySide2.QtCore import QTimer, Qt, QUrl
from PySide2.QtGui import QKeySequence
from PySide2.QtWidgets import (
    QAction,QWidget,
    QMenu,
    QInputDialog,
    QActionGroup
)
class BaudRatesManager(QWidget):
    
    def __init__(self,parent=None):
        super(BaudRatesManager, self).__init__(parent)
        self.inputBaudRate = 115200
        self.outputBaudRate = 115200
        self.singleCOMBaudRate = 115200

    def setSingleCOMBaudRate(self, rate: int):
        """
        Called when the user picks a predefined rate.
        """
        self.singleCOMBaudRate = rate

    def setCustomSingleCOMBaudRate(self):
        """
        Pops up a dialog that lets the user type any integer baud rate.
        """
        # The dialog returns (value, ok).  We restrict it to positive ints.
        value, ok = QInputDialog.getInt(
            self,
            "Custom Baud Rate",
            "Enter baud rate (e.g. 9600, 115200, 250000 …):",
            value=self.singleCOMBaudRate,
            min=1,
            max=10_000_000,          # a generous upper bound
        )
        if ok:
            self.setSingleCOMBaudRate(value)
            
    def setInputBaudRate(self, rate: int):
        """
        Called when the user picks a predefined rate.
        """
        self.inputBaudRate = rate

    def setCustomInputBaudRate(self):
        """
        Pops up a dialog that lets the user type any integer baud rate.
        """
        # The dialog returns (value, ok).  We restrict it to positive ints.
        value, ok = QInputDialog.getInt(
            self,
            "Custom Baud Rate",
            "Enter baud rate (e.g. 9600, 115200, 250000 …):",
            value=self.inputBaudRate,
            min=1,
            max=10_000_000,          # a generous upper bound
        )
        if ok:
            self.setInputBaudRate(value)

    def setOutputBaudRate(self, rate: int):
        """
        Called when the user picks a predefined rate.
        """
        self.outputBaudRate = rate

    def setCustomOutputBaudRate(self):
        """
        Pops up a dialog that lets the user type any integer baud rate.
        """
        # The dialog returns (value, ok).  We restrict it to positive ints.
        value, ok = QInputDialog.getInt(
            self,
            "Custom Baud Rate",
            "Enter baud rate (e.g. 9600, 115200, 250000 …):",
            value=self.outputBaudRate,
            min=1,
            max=10_000_000,          # a generous upper bound
        )
        if ok:
            self.setOutputBaudRate(value)
            
            
    def addBaudRatesToSettingsMenu(self, settingsMenu):

        self.BaudRateMenu = QMenu("&Baud Rates", self)
        # Sub‑menu that holds the actual rate choices
        self.changeSingleCOMBaudMenu = QMenu("Baud Rate")
        self.changeInputBaudMenu = QMenu("Input Baud Rate (From Visualizer to Radar)")
        self.changeOutputBaudMenu = QMenu("Output Baud Rate (From Radar to Visualizer)")
        
        self.changeSingleCOMBaudMenu.setToolTip(
            "Note this only changes the baud rate of the visualizer, not the radar device."
            "To change the radar device's baud rate, you will need to change the software running on chip in using CCS and sysconfig"
        )
        self.changeInputBaudMenu.setToolTip(
            "Note this only changes the baud rate the visualizer transmits at, not the rate the radar device is receiving at."
            "To change the radar device's baud rate, you will need to change the software running on chip in using CCS and sysconfig"
        )
        
        self.changeOutputBaudMenu.setToolTip(
            "Note this only changes the baud rate that the visualizer tries to read the radar data at, not the rate that the radar device transmits at."
            "To change the radar device's baud rate, you will need to change the software running on chip in using CCS and sysconfig"
        )
        # ---- create an exclusive QActionGroup ---------------------------
        self.singleCOMBaudRateGroup = QActionGroup(self)
        self.singleCOMBaudRateGroup.setExclusive(True)          # only one can be checked

        # ---- common rates (checkable) ---------------------------------
        self.singleCOMBaud115200Action = QAction("115200", self, checkable=True)
        self.singleCOMBaud921600Action = QAction("921600", self, checkable=True)
        self.singleCOMBaud1250000Action = QAction("1250000", self, checkable=True)

        # ---- custom rate (checkable) ----------------------------------
        self.singleCOMBaudCustomAction = QAction("Custom …", self, checkable=True)
        
        # Add actions to the exclusive group
        self.singleCOMBaudRateGroup.addAction(self.singleCOMBaud115200Action)
        self.singleCOMBaudRateGroup.addAction(self.singleCOMBaud921600Action)
        self.singleCOMBaudRateGroup.addAction(self.singleCOMBaud1250000Action)
        self.singleCOMBaudRateGroup.addAction(self.singleCOMBaudCustomAction)
        
        # Connect each action to the handler
        self.singleCOMBaud115200Action.triggered.connect(lambda: self.setSingleCOMBaudRate(115200))
        self.singleCOMBaud921600Action.triggered.connect(lambda: self.setSingleCOMBaudRate(921600))
        self.singleCOMBaud1250000Action.triggered.connect(lambda: self.setSingleCOMBaudRate(1250000))
        self.singleCOMBaudCustomAction.triggered.connect(self.setCustomSingleCOMBaudRate)
        
        # Add the actions to the submenu
        self.changeSingleCOMBaudMenu.addAction(self.singleCOMBaud115200Action)
        
        # Removed because IWRL6432 doesn't support 921600 baud
        # self.changeSingleCOMBaudMenu.addAction(self.singleCOMBaud921600Action)
        
        self.changeSingleCOMBaudMenu.addAction(self.singleCOMBaud1250000Action)
        self.changeSingleCOMBaudMenu.addSeparator()
        self.changeSingleCOMBaudMenu.addAction(self.singleCOMBaudCustomAction)

        # ---- create an exclusive QActionGroup ---------------------------
        self.inputBaudRateGroup = QActionGroup(self)
        self.inputBaudRateGroup.setExclusive(True)          # only one can be checked

        # ---- common rates (checkable) ---------------------------------
        self.inputBaud115200Action = QAction("115200", self, checkable=True)
        self.inputBaud921600Action = QAction("921600", self, checkable=True)
        self.inputBaud1250000Action = QAction("1250000", self, checkable=True)

        # ---- custom rate (checkable) ----------------------------------
        self.inputBaudCustomAction = QAction("Custom …", self, checkable=True)
        
        # Add actions to the exclusive group
        self.inputBaudRateGroup.addAction(self.inputBaud115200Action)
        self.inputBaudRateGroup.addAction(self.inputBaud921600Action)
        self.inputBaudRateGroup.addAction(self.inputBaud1250000Action)
        self.inputBaudRateGroup.addAction(self.inputBaudCustomAction)
        
        # Connect each action to the handler
        self.inputBaud115200Action.triggered.connect(lambda: self.setInputBaudRate(115200))
        self.inputBaud921600Action.triggered.connect(lambda: self.setInputBaudRate(921600))
        self.inputBaud1250000Action.triggered.connect(lambda: self.setInputBaudRate(1250000))
        self.inputBaudCustomAction.triggered.connect(self.setCustomInputBaudRate)
        
        # Add the actions to the submenu
        self.changeInputBaudMenu.addAction(self.inputBaud115200Action)
        self.changeInputBaudMenu.addAction(self.inputBaud921600Action)
        self.changeInputBaudMenu.addAction(self.inputBaud1250000Action)
        self.changeInputBaudMenu.addSeparator()
        self.changeInputBaudMenu.addAction(self.inputBaudCustomAction)
        
        # ---- create an exclusive QActionGroup ---------------------------
        self.outputBaudRateGroup = QActionGroup(self)
        self.outputBaudRateGroup.setExclusive(True)          # only one can be checked

        # ---- common rates (checkable) ---------------------------------
        self.outputBaud115200Action = QAction("115200", self, checkable=True)
        self.outputBaud921600Action = QAction("921600", self, checkable=True)
        self.outputBaud1250000Action = QAction("1250000", self, checkable=True)

        # ---- custom rate (checkable) ----------------------------------
        self.outputBaudCustomAction = QAction("Custom …", self, checkable=True)
        
        # Add actions to the exclusive group
        self.outputBaudRateGroup.addAction(self.outputBaud115200Action)
        self.outputBaudRateGroup.addAction(self.outputBaud921600Action)
        self.outputBaudRateGroup.addAction(self.outputBaud1250000Action)
        self.outputBaudRateGroup.addAction(self.outputBaudCustomAction)


        # Connect each action to the handler
        self.outputBaud115200Action.triggered.connect(lambda: self.setOutputBaudRate(115200))
        self.outputBaud921600Action.triggered.connect(lambda: self.setOutputBaudRate(921600))
        self.outputBaud1250000Action.triggered.connect(lambda: self.setOutputBaudRate(1250000))
        self.outputBaudCustomAction.triggered.connect(self.setCustomOutputBaudRate)
                
        # Add the actions to the submenu
        self.changeOutputBaudMenu.addAction(self.outputBaud115200Action)
        self.changeOutputBaudMenu.addAction(self.outputBaud921600Action)
        self.changeOutputBaudMenu.addAction(self.outputBaud1250000Action)
        self.changeOutputBaudMenu.addSeparator()
        self.changeOutputBaudMenu.addAction(self.outputBaudCustomAction)

        # Attach the submenu to Settings
        self.BaudRateMenu.addMenu(self.changeSingleCOMBaudMenu)
        self.BaudRateMenu.addMenu(self.changeInputBaudMenu)
        self.BaudRateMenu.addMenu(self.changeOutputBaudMenu)
        settingsMenu.addMenu(self.BaudRateMenu)
        
        # Highlight the default rate when the UI first appears
        self.inputBaud115200Action.setChecked(True)
        self.outputBaud115200Action.setChecked(True)

    def lockBaudMenuState(self):
        self.changeSingleCOMBaudMenu.setEnabled(False)
        self.changeInputBaudMenu.setEnabled(False)
        self.changeOutputBaudMenu.setEnabled(False)

    def updateBaudMenuState(self, device: str):
        # Start by enabling everything – this makes the function idempotent
        self.changeSingleCOMBaudMenu.setEnabled(True)
        self.changeInputBaudMenu.setEnabled(True)
        self.changeOutputBaudMenu.setEnabled(True)

        # ----- 6844 / 6843 -------------------------------------------------
        if device in ("xWRL6844", "xWR6843","xWR1843"):
            self.changeSingleCOMBaudMenu.setDisabled(True)
            self.changeInputBaudMenu.setEnabled(True)
            self.changeOutputBaudMenu.setEnabled(True)
        # ----- 6432 ---------------------------------------------------------
        if device in ("xWRL6432", "xWR6432", "xWRL1432"):
            self.changeSingleCOMBaudMenu.setEnabled(True)
            self.changeInputBaudMenu.setDisabled(True)
            self.changeOutputBaudMenu.setDisabled(True)

    # Specific functions to set the baud rates to the preset options
    def setSingleCOMTo115200(self):
        self.singleCOMBaud115200Action.trigger()
                
    def setSingleCOMTo921600(self):
        self.singleCOMBaud921600Action.trigger()

    def setSingleCOMTo1250000(self):
        self.singleCOMBaud1250000Action.trigger()    

    def setOutputCOMTo115200(self):
        self.outputBaud115200Action.trigger()
        
    def setOutputCOMTo1250000(self):
        self.outputBaud1250000Action.trigger()
                
    def setOutputCOMTo921600(self):
        self.outputBaud921600Action.trigger()

    def setInputCOMTo115200(self):
        self.inputBaud115200Action.trigger()
               
    def setInputCOMTo1250000(self):
        self.inputBaud1250000Action.trigger()
                
    def setInputCOMTo921600(self):
        self.inputBaud921600Action.trigger()
        
    def getInputBaudRate(self):
        return self.inputBaudRate
    
    def getOutputBaudRate(self):
        return self.outputBaudRate
    
    def getSingleBaudRate(self):
        return self.singleCOMBaudRate
    