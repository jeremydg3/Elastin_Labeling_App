import numpy as np
from PyQt6.QtGui import QPixmap, QImage

def np_to_qpixmap(arr: np.ndarray) -> QPixmap:
    assert arr.ndim == 3 and arr.shape[2] in (3, 4)
    h, w, c = arr.shape
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if c == 3:
        qimg = QImage(arr.data, w, h, 3*w, QImage.Format.Format_RGB888)
    else:
        qimg = QImage(arr.data, w, h, 4*w, QImage.Format.Format_RGBA8888)
    # qimg._arr_ref = arr
    return QPixmap.fromImage(qimg)
