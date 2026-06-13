# Vendored from: tools\visualizers\Applications_Visualizer\common\gui_common.py
import os
import sys
import numpy as np

import logging
log = logging.getLogger(__name__)

def fixStringCase(st):
    return ''.join(''.join([w[0].upper(), w[1:].lower()]) for w in st.split())

def next_power_of_2(x):  
    return 1 if x == 0 else 2**(x - 1).bit_length()

def median(lst):
    lst.sort()
    if len(lst) % 2 == 1:
        return lst[len(lst)//2]
    else:
        return (lst[len(lst)//2-1] + lst[len(lst)//2])/2

# Convert 3D Spherical Points to Cartesian
# Assumes sphericalPointCloud is an numpy array with at LEAST 3 dimensions
# Order should be Range, Elevation, Azimuth
def sphericalToCartesianPointCloud(sphericalPointCloud):
    shape = sphericalPointCloud.shape
    cartesianPointCloud = sphericalPointCloud.copy()
    if (shape[1] < 3):
        log.error('Error: Failed to convert spherical point cloud to cartesian due to numpy array with too few dimensions')
        return sphericalPointCloud

    # Compute X
    # Range * sin (azimuth) * cos (elevation)
    cartesianPointCloud[:,0] = sphericalPointCloud[:,0] * np.sin(sphericalPointCloud[:,1]) * np.cos(sphericalPointCloud[:,2]) 
    # Compute Y
    # Range * cos (azimuth) * cos (elevation)
    cartesianPointCloud[:,1] = sphericalPointCloud[:,0] * np.cos(sphericalPointCloud[:,1]) * np.cos(sphericalPointCloud[:,2]) 
    # Compute Z
    # Range * sin (elevation)
    cartesianPointCloud[:,2] = sphericalPointCloud[:,0] * np.sin(sphericalPointCloud[:,2])
    return cartesianPointCloud
