import sys, io
import numpy as np
import requests
from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtGui import QIcon
import tifffile
import base64
import io
import cv2
from tile_grid_view import TileBrowser
import math
import mimetypes
import os
import csv
from typing import List, Any, Callable, Optional


WEB_APP_URL = "https://script.google.com/macros/s/AKfycbw8mQLmfC5dYQ2Hc41M3d-nTKsxx_oRsgIl_c6iFdpkeoerrrI1OaoIJdbCSkoHPNHDSg/exec"
TILE_SIZE = 256

def encode_png_b64(tile_rgb: np.ndarray) -> str:
    # tile_rgb: (255,255,3) RGB uint8
    ok, buf = cv2.imencode(".png", cv2.cvtColor(tile_rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("cv2.imencode(.png) failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")

def encode_csv_b64(mask: np.ndarray) -> str:
    # mask: (255,255) uint8 (values 0..9, 255)
    # CSV in-memory text -> utf-8 bytes -> base64
    s = io.StringIO()
    writer = csv.writer(s, lineterminator="\n")
    # write as integers; faster than savetxt for small tiles
    mask_uint16 = mask.astype(np.uint16)
    for i in range(mask_uint16.shape[0]):
        writer.writerow(mask_uint16[i].tolist())
    text = s.getvalue().encode("utf-8")
    return base64.b64encode(text).decode("ascii")

def upload_tiles_batch(base_name: str,
                       tiles_rgb: List[np.ndarray],
                       masks: List[np.ndarray],
                       subfolder: str | None = None,
                       orig_indices: List[int] | None = None):
    """
    Sends tiles in batches; no local files created.
    If orig_indices is provided, it is used for naming and the "i" field to
    preserve the original tile indices from the source image grid.
    Returns list of {i, pngId, csvId} for all tiles.
    """
    assert len(tiles_rgb) == len(masks)
    batch_size = len(tiles_rgb)

    items = []
    for i in range(batch_size):
        i_orig = orig_indices[i] if orig_indices is not None else i
        items.append({
            "i": i_orig,
            "png_b64": encode_png_b64(tiles_rgb[i]),
            "csv_b64": encode_csv_b64(masks[i]),
            # optional custom names:
            "png_name": f"{base_name}_tile_{i_orig:04d}.png",
            "csv_name": f"{base_name}_tile_{i_orig:04d}.csv",
        })

    payload = {
        "action": "upload_tiles",
        "baseName": base_name,
        "subfolder": subfolder,  # optional label for folder under parent
        "items": items,
    }
    r = requests.post(WEB_APP_URL, json=payload, timeout=300)
    r.raise_for_status()
    try:
        res = r.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")
        print(f"Response text: {e.response.text}")
    except requests.exceptions.JSONDecodeError as e:
        print(f"JSONDecodeError: {e}")
        print(f"Response text that caused the error: {r.text if 'response' in locals() else 'No response available'}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    if not res.get("ok"):
        raise RuntimeError(f"Upload failed: {res}")

class Worker(QtCore.QObject):
    """Generic worker to run a callable in a QThread and emit results back to UI."""
    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}

    @QtCore.pyqtSlot()
    def run(self):
        try:
            res = self._fn(*self._args, **self._kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
 
    
class MainWindow(QtWidgets.QWidget):
    """
    Queue-backed TIFF viewer with tile grid:
      - Fetches next image from Apps Script web app
      - Streams base64 TIFF bytes, decodes with tifffile
      - Converts to RGB (cv2), splits into 255x255 tiles
      - Pads partial edge tiles (dimmed & not clickable)
      - Grid hover highlight; click opens full tile; Back returns to grid
    """
    def __init__(self, tile_size: int = TILE_SIZE):
        super().__init__()
        self.setWindowTitle("Elastin Queue Tile Viewer")
        self.setWindowIcon(QIcon(r"app/assets/logo.png"))
        self.web_app_url = WEB_APP_URL
        self.tile_size = tile_size

        # --- UI ---
        self.view = TileBrowser(tile_px=self.tile_size)  # from tile_grid_view.py
        self.btnNext = QtWidgets.QPushButton("Get Next")
        self.btnDone = QtWidgets.QPushButton("Mark Done")
        self.btnSkip = QtWidgets.QPushButton("Skip Image")
        self.status = QtWidgets.QLabel("")
        self._busy_depth = 0
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setStyleSheet("color:#444;")
        self.image_title = ""

        ctl = QtWidgets.QHBoxLayout()
        ctl.addWidget(self.btnNext)
        ctl.addWidget(self.btnDone)
        ctl.addWidget(self.btnSkip)
        ctl.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(ctl)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)

        # --- state ---
        self.current = None  # {fileId,fileName,...}
        self.tiles_np = []  # type: List[np.ndarray]  # tiles for current image
        self._bg_threads = []  # type: list[QtCore.QThread]
        self._bg_workers = []  # type: list[Worker]

        # --- wiring ---
        self.btnNext.clicked.connect(self.on_next)
        self.btnDone.clicked.connect(self.on_done)
        self.btnSkip.clicked.connect(self.on_skip)
        self._set_work_buttons_enabled(False)

    # ------------------ Actions ------------------

    def on_next(self):
        # Clear current view immediately
        self.view.set_title("")
        self.view.set_tiles_with_flags([], [], layout=(0, 0))

        self._busy(True, "Fetching image bytes...")
        self.status.setText("Fetching image bytes...")

        def _task_fetch():
            # Claim next
            r = requests.post(self.web_app_url, json={"action": "next"}, timeout=60)
            r.raise_for_status()
            data = r.json()
            if data.get("done"):
                return {"done": True, "message": data.get("message", "Queue empty.")}

            fname = data.get("fileName", "(unnamed)")
            raw_url = f"{self.web_app_url}?raw={data['fileId']}"
            rb = requests.get(raw_url, timeout=120)
            rb.raise_for_status()
            b = base64.b64decode(rb.text)
            arr = tifffile.imread(io.BytesIO(b))
            img_rgb = self._to_rgb_uint8(arr)
            tiles_np, enabled_flags, (rows, cols) = self._split_into_tiles_with_padding(
                img_rgb, tile=self.tile_size, pad_value=0
            )
            return {
                "done": False,
                "data": data,
                "fname": fname,
                "img_shape": img_rgb.shape,
                "tiles": tiles_np,
                "enabled": enabled_flags,
                "layout": (rows, cols),
            }

        def _on_result(res: dict):
            if res.get("done"):
                self.current = None
                self.view.set_title("")
                self.view.set_tiles_with_flags([], [], layout=(0, 0))
                self.status.setText(res.get("message", "Queue empty."))
                self._set_work_buttons_enabled(False)
                return
            self.current = res["data"]
            self.image_title = res["fname"]
            self.view.set_title(self.image_title)
            self.tiles_np = res["tiles"]
            enabled_flags = res["enabled"]
            rows, cols = res["layout"]
            img_h, img_w = res["img_shape"][0], res["img_shape"][1]
            self.view.set_tiles_with_flags(self.tiles_np, enabled_flags, (rows, cols))
            self.status.setText(f"{self.image_title}  —  image: {img_w}x{img_h}  tiles: {rows}x{cols}")
            self._set_work_buttons_enabled(True)

        self._run_in_thread(_task_fetch, on_result=_on_result, on_error=self._show_error)

    def on_done(self):
        if not self.current:
            return
        # Determine which tiles have been marked complete and upload only those
        completed_idxs = getattr(self.view, "get_completed_indices", lambda: [])()
        if not completed_idxs:
            QtWidgets.QMessageBox.information(self, "Nothing to upload", "No tiles are marked complete. Mark tiles as complete before uploading.")
            return

        tiles_to_upload = [self.tiles_np[i] for i in completed_idxs]
        masks_to_upload = [self.view.get_mask_for_tile(i) for i in completed_idxs]

        self._busy(True, "Uploading completed tiles...")
        self.status.setText("Uploading completed tiles...")

        def _task_upload():
            upload_tiles_batch(base_name=self.image_title.replace(" ", "_"),
                               tiles_rgb=tiles_to_upload,
                               masks=masks_to_upload,
                               subfolder=f"{self.image_title} - annotated",
                               orig_indices=completed_idxs)
            return {"count": len(tiles_to_upload)}

        def _on_uploaded(_res):
            self.on_next()

        self._run_in_thread(_task_upload, on_result=_on_uploaded, on_error=self._show_error)


    def on_skip(self):
        if not self.current:
            return
        self._busy(True, "Skipping image, please wait...")
        self.status.setText("Skipping image...")

        file_id = self.current["fileId"]

        def _task_skip():
            requests.post(self.web_app_url, json={"action": "skip", "fileId": file_id}, timeout=30)
            return True

        def _on_skipped(_res):
            self.on_next()

        self._run_in_thread(_task_skip, on_result=_on_skipped, on_error=self._show_error)


    # def upload_file_to_queue(self, path: str):
    #     with open(path, "rb") as f:
    #         raw = f.read()
    #     b64 = base64.b64encode(raw).decode("ascii")
    #     mime, _ = mimetypes.guess_type(path)
    #     payload = {
    #         "action": "upload",
    #         "filename": os.path.basename(path),
    #         "mimeType": mime or "application/octet-stream",
    #         "b64": b64,
    #     }
    #     r = requests.post(WEB_APP_URL, json=payload, timeout=120)
    #     r.raise_for_status()
    #     res = r.json()
    #     if not res.get("ok"):
    #         raise RuntimeError(f"Upload failed: {res}")
    #     return res["fileId"], res["fileName"]
    

    # def on_upload_clicked(self):
    #     path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select image to upload",
    #                                                     "", "Images (*.tif *.tiff *.png *.jpg *.jpeg)")
    #     if not path:
    #         return
    #     try:
    #         self._busy(True)
    #         file_id, file_name = self.upload_file_to_queue(path)
    #         QtWidgets.QMessageBox.information(self, "Uploaded",
    #             f"Uploaded:\n{file_name}\n(fileId: {file_id})\nIt is now in the queue.")
    #     except Exception as e:
    #         QtWidgets.QMessageBox.critical(self, "Upload failed", str(e))
    #     finally:
    #         self._busy(False)


    # ------------------ Helpers ------------------
    def _busy(self, yes: bool, action_text: str = "Processing..."):
        if yes:
            if self._busy_depth == 0:
                # Create and show loading dialog
                self.loading_dialog = QtWidgets.QDialog(self)
                self.loading_dialog.setWindowTitle("Loading...")
                self.loading_dialog.setModal(True)
                self.loading_dialog.setWindowFlags(
                    QtCore.Qt.WindowType.Dialog | 
                    QtCore.Qt.WindowType.CustomizeWindowHint |
                    QtCore.Qt.WindowType.WindowTitleHint
                )
                
                # Create loading animation (spinning icon)
                self.loading_label = QtWidgets.QLabel()
                self.loading_movie = QtGui.QMovie()
                
                # Create a simple spinning animation programmatically
                pixmap = QtGui.QPixmap(50, 50)
                pixmap.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(pixmap)
                painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                painter.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.blue))
                painter.drawEllipse(20, 5, 10, 10)
                painter.end()
                
                self.loading_label.setPixmap(pixmap)
                self.loading_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                
                # Add rotation animation
                self.rotation_timer = QtCore.QTimer()
                self.rotation_angle = 0
                self.rotation_timer.timeout.connect(self._rotate_loading_icon)
                self.rotation_timer.start(50)  # Update every 50ms
                
                # Layout
                layout = QtWidgets.QVBoxLayout()
                layout.addWidget(QtWidgets.QLabel(action_text))
                layout.addWidget(self.loading_label)
                self.loading_dialog.setLayout(layout)
                self.loading_dialog.resize(200, 100)
                
                # Center on parent
                if self.parentWidget():
                    parent_geo = self.geometry()
                    x = parent_geo.x() + (parent_geo.width() - 200) // 2
                    y = parent_geo.y() + (parent_geo.height() - 100) // 2
                    self.loading_dialog.move(x, y)
                
                self.loading_dialog.show()
                
            self._busy_depth += 1
        else:
            if self._busy_depth > 0:
                self._busy_depth -= 1
            if self._busy_depth == 0:
                # Stop animation and close dialog
                if hasattr(self, 'rotation_timer'):
                    self.rotation_timer.stop()
                if hasattr(self, 'loading_dialog'):
                    self.loading_dialog.close()
                    delattr(self, 'loading_dialog')
                
                # Process events to ensure UI updates
                QtCore.QCoreApplication.processEvents()

        # Buttons state
        self.btnNext.setEnabled(self._busy_depth == 0 and self.current is None)
        self.btnDone.setEnabled(self._busy_depth == 0 and self.current is not None)
        self.btnSkip.setEnabled(self._busy_depth == 0 and self.current is not None)

    def _run_in_thread(self, fn: Callable, args: Optional[tuple] = None, kwargs: Optional[dict] = None,
                       on_result: Optional[Callable[[Any], None]] = None,
                       on_error: Optional[Callable[[str], None]] = None):
        """Run fn in a background QThread; ensure busy state is cleared when thread ends."""
        args = args or ()
        kwargs = kwargs or {}
        thread = QtCore.QThread(self)
        worker = Worker(fn, *args, **kwargs)
        worker.moveToThread(thread)

        # Retain references to prevent Python GC from collecting them prematurely
        self._bg_threads.append(thread)
        self._bg_workers.append(worker)

        def _thread_finished():
            # Always clear busy when the operation finishes (success or error)
            self._busy(False)
            # Cleanup references
            try:
                self._bg_threads.remove(thread)
            except ValueError:
                pass
            try:
                self._bg_workers.remove(worker)
            except ValueError:
                pass
            thread.deleteLater()

        thread.started.connect(worker.run)
        worker.finished.connect(lambda res: (on_result and on_result(res)))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda msg: (on_error and on_error(msg)))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(_thread_finished)
        thread.start()

    def _show_error(self, message: str):
        QtWidgets.QMessageBox.critical(self, "Error", message)
        self.status.setText(message)

    def _rotate_loading_icon(self):
        """Helper method to rotate the loading icon"""
        if hasattr(self, 'loading_label'):
            self.rotation_angle = (self.rotation_angle + 15) % 360
            
            # Create rotated pixmap
            pixmap = QtGui.QPixmap(50, 50)
            pixmap.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.translate(25, 25)
            painter.rotate(self.rotation_angle)
            painter.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.blue))
            painter.drawEllipse(-5, -20, 10, 10)
            painter.drawEllipse(-5, 10, 10, 10)
            painter.end()
            
            self.loading_label.setPixmap(pixmap)


    def _set_work_buttons_enabled(self, enabled: bool):
        self.btnDone.setEnabled(enabled)
        self.btnSkip.setEnabled(enabled)

    @staticmethod
    def _to_rgb_uint8(arr: np.ndarray) -> np.ndarray:
        """
        Converts tifffile output to RGB uint8.
        Handles grayscale, uint16, planar (C,H,W), and channel-order.
        """
        # Planar to interleaved if needed: (C,H,W) -> (H,W,C)
        if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (3, 4):
            arr = np.transpose(arr, (1, 2, 0))

        # Convert dtype to 8-bit
        if arr.dtype == np.uint16:
            # Scale 16→8 (0..65535 → 0..255)
            arr8 = cv2.convertScaleAbs(arr, alpha=255.0 / 65535.0)
        elif arr.dtype != np.uint8:
            arr8 = np.clip(arr, 0, 255).astype(np.uint8)
        else:
            arr8 = arr

        # Grayscale to RGB
        if arr8.ndim == 2:
            rgb = cv2.cvtColor(arr8, cv2.COLOR_GRAY2RGB)
            return rgb

        # If already 3/4 channels, assume it's RGB(A) — drop alpha if present
        if arr8.ndim == 3 and arr8.shape[2] == 4:
            return arr8[:, :, :3]
        if arr8.ndim == 3 and arr8.shape[2] == 3:
            return arr8

        # Fallback: replicate first channel
        if arr8.ndim == 3 and arr8.shape[2] == 1:
            return np.repeat(arr8, 3, axis=2)

        raise ValueError(f"Unsupported image shape for RGB conversion: {arr8.shape}")

    @staticmethod
    def _split_into_tiles_with_padding(img_rgb: np.ndarray, tile: int = 255, pad_value: int = 0):
        """
        Returns:
          tiles: List[(tile,tile,3) uint8]
          enabled: List[bool] (True = full tile; False = partial edge tile)
          layout: (rows, cols)
        """
        H, W, _ = img_rgb.shape
        rows = math.ceil(H / tile)
        cols = math.ceil(W / tile)

        tiles, enabled = [], []
        for r in range(rows):
            for c in range(cols):
                y0, x0 = r * tile, c * tile
                y1, x1 = min(y0 + tile, H), min(x0 + tile, W)
                sub = img_rgb[y0:y1, x0:x1, :]

                h, w = sub.shape[:2]
                is_full = (h == tile and w == tile)

                if not is_full:
                    pad_h = tile - h
                    pad_w = tile - w
                    sub = np.pad(
                        sub,
                        ((0, pad_h), (0, pad_w), (0, 0)),
                        mode="constant",
                        constant_values=pad_value,
                    )

                tiles.append(sub.astype(np.uint8))
                enabled.append(is_full)

        return tiles, enabled, (rows, cols)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.resize(1100, 800)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
