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
from typing import List


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
                       subfolder: str | None = None):
    """
    Sends tiles in batches; no local files created.
    Returns list of {i, pngId, csvId} for all tiles.
    """
    assert len(tiles_rgb) == len(masks)
    batch_size = len(tiles_rgb)

    items = []
    for i in range(batch_size):
        items.append({
            "i": i,
            "png_b64": encode_png_b64(tiles_rgb[i]),
            "csv_b64": encode_csv_b64(masks[i]),
            # optional custom names:
            "png_name": f"{base_name}_tile_{i:04d}.png",
            "csv_name": f"{base_name}_tile_{i:04d}.csv",
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

        # --- wiring ---
        self.btnNext.clicked.connect(self.on_next)
        self.btnDone.clicked.connect(self.on_done)
        self.btnSkip.clicked.connect(self.on_skip)
        self._set_work_buttons_enabled(False)

    # ------------------ Actions ------------------

    def on_next(self):
        try:
            # Clear tiles
            self.view.set_title("")
            self.view.set_tiles_with_flags([], [], layout=(0, 0))

            self._busy(True)
            # Claim next
            r = requests.post(self.web_app_url, json={"action": "next"}, timeout=60)
            r.raise_for_status()
            data = r.json()

            # Empty queue
            if data.get("done"):
                self.current = None
                self.view.set_title("")
                self.view.set_tiles_with_flags([], [], layout=(0, 0))
                self.status.setText(data.get("message", "Queue empty."))
                self._set_work_buttons_enabled(False)
                return

            self.current = data
            fname = data.get("fileName", "(unnamed)")
            self.view.set_title(fname)
            self.status.setText("Fetching image bytes...")

            # Fetch base64-encoded TIFF bytes
            raw_url = f"{self.web_app_url}?raw={data['fileId']}"
            rb = requests.get(raw_url, timeout=120)
            rb.raise_for_status()

            # Base64 decode → numpy via tifffile
            b = base64.b64decode(rb.text)
            arr = tifffile.imread(io.BytesIO(b))  # np.ndarray

            # Normalize/convert to 8-bit RGB
            img_rgb = self._to_rgb_uint8(arr)

            # Split into tiles with padding; partial tiles disabled
            self.tiles_np, enabled_flags, (rows, cols) = self._split_into_tiles_with_padding(
                img_rgb, tile=self.tile_size, pad_value=0
            )
            self.image_title = fname
            self.view.set_title(fname)
            self.view.set_tiles_with_flags(self.tiles_np, enabled_flags, (rows, cols))
            self.status.setText(f"{fname}  —  image: {img_rgb.shape[1]}x{img_rgb.shape[0]}  tiles: {rows}x{cols}")
            self._set_work_buttons_enabled(True)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        finally:
            self._busy(False)

    def on_done(self):
        if not self.current:
            return
        try:
            self._busy(True)
            # requests.post(self.web_app_url, json={"action": "done", "fileId": self.current["fileId"]}, timeout=30)
            upload_tiles_batch(base_name=self.image_title.replace(" ", "_"),
                               tiles_rgb=self.tiles_np,
                               masks=[self.view.get_mask_for_tile(i) for i in range(len(self.tiles_np))],
                               subfolder=f"{self.image_title} - annotated")
            self.on_next()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        finally:
            self._busy(False)


    def on_skip(self):
        if not self.current:
            return
        try:
            self._busy(True)
            requests.post(self.web_app_url, json={"action": "skip", "fileId": self.current["fileId"]}, timeout=30)
            self.on_next()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        finally:
            self._busy(False)


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

    def _busy(self, yes: bool):
        app = QtWidgets.QApplication
        if yes:
            if self._busy_depth == 0:
                app.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._busy_depth += 1
        else:
            if self._busy_depth > 0:
                self._busy_depth -= 1
            if self._busy_depth == 0:
                # Pop ALL leftover overrides just in case
                while app.overrideCursor() is not None:
                    app.restoreOverrideCursor()
                # Nudge event loop so cursor updates immediately
                QtCore.QCoreApplication.processEvents()

        # Buttons state (optional)
        self.btnNext.setEnabled(self._busy_depth == 0 and self.current is None)
        self.btnDone.setEnabled(self._busy_depth == 0 and self.current is not None)
        self.btnSkip.setEnabled(self._busy_depth == 0 and self.current is not None)


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
