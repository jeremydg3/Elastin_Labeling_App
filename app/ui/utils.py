import numpy as np
from PyQt6 import QtGui

def np_to_qpixmap(arr: np.ndarray) -> QtGui.QPixmap:
    assert arr.ndim == 3 and arr.shape[2] in (3, 4)
    h, w, c = arr.shape
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if c == 3:
        qimg = QtGui.QImage(arr.data, w, h, 3*w, QtGui.QImage.Format.Format_RGB888)
    else:
        qimg = QtGui.QImage(arr.data, w, h, 4*w, QtGui.QImage.Format.Format_RGBA8888)
    # qimg._arr_ref = arr
    return QtGui.QPixmap.fromImage(qimg)