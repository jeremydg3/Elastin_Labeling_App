import sys, io
import numpy as np
import requests
from PyQt6 import QtWidgets, QtGui, QtCore
import tifffile
import base64
import io


WEB_APP_URL = "https://script.google.com/macros/s/AKfycbw8mQLmfC5dYQ2Hc41M3d-nTKsxx_oRsgIl_c6iFdpkeoerrrI1OaoIJdbCSkoHPNHDSg/exec"

class ImageView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.pix_item = None
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing |
                            QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def show_array(self, arr):
        """
        arr: numpy array (H,W), (H,W,3) or (H,W,4). We'll display as RGBA8888.
        """
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr, np.full_like(arr, 255)], axis=-1)
        elif arr.shape[2] == 3:
            alpha = np.full(arr.shape[:2] + (1,), 255, dtype=arr.dtype)
            arr = np.concatenate([arr, alpha], axis=-1)

        h, w, _ = arr.shape
        # Ensure uint8 RGBA
        if arr.dtype != np.uint8:
            # Scale if it's a larger bit depth
            arr = arr.astype(np.float32)
            arr = np.clip(arr, 0, 255)
            arr = arr.astype(np.uint8)

        bytes_per_line = 4 * w
        qimg = QtGui.QImage(arr.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGBA8888)
        # Keep a reference to the numpy buffer so it doesn't get GC'd
        self._buf_ref = arr
        pix = QtGui.QPixmap.fromImage(qimg)

        if self.pix_item is None:
            self.pix_item = self.scene().addPixmap(pix)
        else:
            self.pix_item.setPixmap(pix)

        self.scene().setSceneRect(0, 0, w, h)
        self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        # Zoom with wheel
        if event.angleDelta().y() > 0:
            factor = 1.15
        else:
            factor = 1.0 / 1.15
        self.scale(factor, factor)

class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Queue TIFF Viewer")

        self.view = ImageView()
        self.btnNext = QtWidgets.QPushButton("Get Next")
        self.btnDone = QtWidgets.QPushButton("Mark Done")
        self.btnSkip = QtWidgets.QPushButton("Skip / Return")
        self.label = QtWidgets.QLabel("")

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.btnNext)
        hl.addWidget(self.btnDone)
        hl.addWidget(self.btnSkip)
        hl.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(hl)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(self.label)

        self.current = None  # will hold dict: {fileId, fileName, ...}

        self.btnNext.clicked.connect(self.on_next)
        self.btnDone.clicked.connect(self.on_done)
        self.btnSkip.clicked.connect(self.on_skip)
        self._set_work_buttons_enabled(False)

    def _set_work_buttons_enabled(self, enabled: bool):
        self.btnDone.setEnabled(enabled)
        self.btnSkip.setEnabled(enabled)

    def on_next(self):
        try:
            # POST {action: "next"}
            r = requests.post(WEB_APP_URL, json={"action": "next"}, timeout=60)
            r.raise_for_status()
            data = r.json()
            if data.get("done"):
                self.current = None
                self.label.setText(data.get("message", "Queue empty."))
                self._set_work_buttons_enabled(False)
                self.view.scene().clear()
                return

            self.current = data  # {fileId, fileName, ...}
            self.label.setText(f"{data.get('fileName','(no name)')}")

            # GET raw bytes ?raw=FILE_ID
            raw_url = WEB_APP_URL + "?raw=" + data["fileId"]
            rb = requests.get(raw_url, timeout=120)
            rb.raise_for_status()
            b = base64.b64decode(rb.text)

            # Decode TIFF (single-page)
            arr = tifffile.imread(io.BytesIO(b))  # returns numpy array; handles multi-bit depths

            # Normalize if >8-bit
            if arr.dtype == np.uint16:
                # scale to 8-bit for display (simple min/max or 0..65535 stretch)
                # You can choose smarter windowing if needed
                arr_8 = (arr / 257.0).astype(np.uint8)  # 16->8 bit
                arr = arr_8
            elif arr.dtype != np.uint8:
                # generic clamp
                arr = np.clip(arr, 0, 255).astype(np.uint8)

            # If it's grayscale shape (H,W), treat as 2D; if planar (C,H,W), transpose
            if arr.ndim == 3 and arr.shape[0] in (1,3,4) and arr.shape[2] not in (3,4):
                # likely (C,H,W)
                arr = np.transpose(arr, (1, 2, 0))

            self.view.show_array(arr)
            self._set_work_buttons_enabled(True)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_done(self):
        if not self.current: return
        try:
            r = requests.post(WEB_APP_URL, json={"action":"done","fileId":self.current["fileId"]}, timeout=30)
            # ignore response details for now
            self.on_next()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_skip(self):
        if not self.current: return
        try:
            r = requests.post(WEB_APP_URL, json={"action":"skip","fileId":self.current["fileId"]}, timeout=30)
            self.on_next()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.resize(1100, 800)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
