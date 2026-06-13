# Vendored from: tools\visualizers\Applications_Visualizer\common\demo_defines.py
# OOB demo names must be different
DEMO_OOB_x843 = 'x843 Out of Box Demo'
DEMO_OOB_x432 = 'x432 Out of Box Demo'
DEMO_OOB_x844 = 'x844 Out of Box Demo'

DEMO_3D_PEOPLE_TRACKING = '3D People Tracking'
DEMO_VITALS = 'Vital Signs with People Tracking'
DEMO_LONG_RANGE = 'Long Range People Detection'
DEMO_MOBILE_TRACKER = 'Mobile Tracker'
DEMO_SMALL_OBSTACLE = 'Small Obstacle Detection'
DEMO_GESTURE = 'Gesture Recognition'
DEMO_SURFACE = 'Surface Classification'
DEMO_PC_CLASS = 'Point Cloud Classification'
DEMO_LEVEL_SENSING = 'Level Sensing'
DEMO_1D_SENSING = '1D Sensing'
DEMO_GROUND_SPEED = 'True Ground Speed'
DEMO_KTO = 'Kick to Open'
DEMO_CALIBRATION = 'Calibration'
DEMO_DASHCAM = 'Exterior Intrusion Monitoring'
DEMO_EBIKES = 'Bike Radar'
DEMO_VIDEO_DOORBELL = "Video Doorbell"
DEMO_DEBUG_PLOTS = "Debug Plots"
DEMO_REPLAY = 'Replay Mode'
DEMO_INTRUDER = 'Intruder Detection'
DEMO_SBR = 'Seat Belt Reminder'
# DEMO_CPD = "Child Presence Detection V1" no longer supporting this
DEMO_LPD = "Child Presence Detection"
DEMO_TOILET = 'Smart Toilet Demo'
DEMO_3DPT_6844 = '3D People Tracking 6844'
DEMO_SLEEP_MONITORING = 'Sleep Monitoring'

# Com Port names
CLI_XDS_SERIAL_PORT_NAME = 'XDS110 Class Application/User UART'
DATA_XDS_SERIAL_PORT_NAME = 'XDS110 Class Auxiliary Data Port'
CLI_SIL_SERIAL_PORT_NAME = 'Enhanced COM Port'
DATA_SIL_SERIAL_PORT_NAME = 'Standard COM Port'

BUSINESS_DEMOS = {
    "Industrial": [
        DEMO_OOB_x843, DEMO_OOB_x432, DEMO_OOB_x844, DEMO_3D_PEOPLE_TRACKING, DEMO_VITALS, DEMO_LONG_RANGE, DEMO_MOBILE_TRACKER, DEMO_SMALL_OBSTACLE, 
        DEMO_GESTURE, DEMO_SURFACE, DEMO_PC_CLASS, DEMO_LEVEL_SENSING, DEMO_1D_SENSING, DEMO_GROUND_SPEED, DEMO_CALIBRATION, DEMO_EBIKES, DEMO_REPLAY, DEMO_VIDEO_DOORBELL, DEMO_DEBUG_PLOTS, DEMO_TOILET, DEMO_SLEEP_MONITORING, DEMO_3DPT_6844
    ],
    "BAC": [
        DEMO_OOB_x843, DEMO_OOB_x432, DEMO_OOB_x844, DEMO_3D_PEOPLE_TRACKING, DEMO_GESTURE, DEMO_KTO, DEMO_CALIBRATION, DEMO_DASHCAM, DEMO_REPLAY, DEMO_INTRUDER, DEMO_SBR, DEMO_LPD, DEMO_DEBUG_PLOTS
    ]
}

# Populated with all devices and the demos each of them can run
DEVICE_DEMO_DICT = {
    "xWR6843": {
        "isxWRx843": True,
        "isxWRLx432": False,
        "isxWRLx844" : False,
        "singleCOM": False,
        "demos": [DEMO_OOB_x843, DEMO_3D_PEOPLE_TRACKING, DEMO_SMALL_OBSTACLE, DEMO_GESTURE, DEMO_SURFACE, DEMO_LONG_RANGE, DEMO_MOBILE_TRACKER, DEMO_VITALS, DEMO_GROUND_SPEED]
    },
    "xWR1843": {
        "isxWRx843": True,
        "isxWRLx432": False,
        "isxWRLx844" : False,
        "singleCOM": False,
        "demos": [DEMO_OOB_x843, DEMO_3D_PEOPLE_TRACKING, DEMO_GESTURE, DEMO_SURFACE, DEMO_LONG_RANGE, DEMO_MOBILE_TRACKER]
    },
    "xWRL6432": {
        "isxWRx843": False,
        "isxWRLx432": True,
        "isxWRLx844" : False,
        "singleCOM": True,
        "demos": [DEMO_OOB_x432, DEMO_LEVEL_SENSING, DEMO_1D_SENSING, DEMO_GESTURE, DEMO_SURFACE, DEMO_PC_CLASS, DEMO_GROUND_SPEED, DEMO_SMALL_OBSTACLE, DEMO_KTO, DEMO_VITALS, DEMO_DASHCAM, DEMO_REPLAY, DEMO_EBIKES, DEMO_VIDEO_DOORBELL, DEMO_CALIBRATION, DEMO_DEBUG_PLOTS, DEMO_TOILET, DEMO_SLEEP_MONITORING]
    },
    "xWRL1432": {
        "isxWRx843": False,
        "isxWRLx432": True,
        "isxWRLx844" : False,
        "singleCOM": True,
        "demos": [DEMO_OOB_x432, DEMO_LEVEL_SENSING, DEMO_1D_SENSING, DEMO_GESTURE, DEMO_GROUND_SPEED, DEMO_KTO, DEMO_CALIBRATION, DEMO_DASHCAM, DEMO_EBIKES, DEMO_REPLAY, DEMO_DEBUG_PLOTS]
    },
    "xWRL6844": {
        "isxWRx843": False,
        "isxWRLx432": False,
        "isxWRLx844" : True,
        "singleCOM" : False,
        "demos" : [DEMO_OOB_x844, DEMO_INTRUDER, DEMO_SBR, DEMO_LPD, DEMO_3DPT_6844]

    }
}
