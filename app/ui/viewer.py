import sys, os
import numpy as np
import cv2
import math
from typing import List, Any, Callable, Optional

from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtCore import pyqtSignal, Qt, QObject, QCoreApplication, QThread, pyqtSlot
from PyQt6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication

from tile_browser import TileBrowser
from loading_animation import LoadingDialog
from user_selection_dialog import show_user_selection_dialog
from webapp_interface_funcs import (
    WEB_APP_URL,
    fetch_next_image,
    upload_tiles_batch,
    skip_image,
    get_user_list,
    mark_image_done,
    clean_exit,
    prefetch_next_image
)
from styles import apply_dark_theme

basedir = os.path.dirname(__file__)

TILE_SIZE = 256

class Worker(QObject):
    """Generic worker to run a callable in a QThread and emit results back to UI."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}

    @pyqtSlot()
    def run(self):
        """Run the callable and emit finished or error signals."""
        try:
            res = self._fn(*self._args, **self._kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
 
    
class MainWindow(QWidget):
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
        self.web_app_url = WEB_APP_URL
        self.tile_size = tile_size

        # --- UI ---
        self.view = TileBrowser(tile_px=self.tile_size)  # from tile_grid_view.py
        self.btnNext = QPushButton("Get Next")
        self.btnNext.setProperty("primary", True)  # Use primary button style
        self.btnNext.setToolTip("Fetch the next image from the queue")
        self.btnNext.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnDone = QPushButton("Mark Done")
        self.btnDone.setProperty("success", True)  # Use success button style
        self.btnDone.setToolTip("Mark the current image as done")
        self.btnDone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnSkip = QPushButton("Skip Image")
        self.btnSkip.setProperty("warning", True)  # Use warning button style
        self.btnSkip.setToolTip("Skip the current image")
        self.btnSkip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status = QLabel("")
        self._busy_depth = 0
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        # Status label will use theme's secondary text color
        self.image_title = ""

        ctl = QHBoxLayout()
        ctl.addWidget(self.btnNext)
        ctl.addWidget(self.btnDone)
        ctl.addWidget(self.btnSkip)
        ctl.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(ctl)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)

        # --- state ---
        self.current = None  # {fileId,fileName,...}
        self.tiles_np = []  # type: List[np.ndarray]  # tiles for current image
        self._bg_threads = []  # type: list[QThread]
        self._bg_workers = []  # type: list[Worker]
        self.user = None  # type: Optional[str]  # Selected username
        self._prefetch_thread = None  # type: Optional[QThread]
        self._prefetch_worker = None  # type: Optional[Worker]

        # --- wiring ---
        self.btnNext.clicked.connect(self.on_next)
        self.btnDone.clicked.connect(self.on_done)
        self.btnSkip.clicked.connect(self.on_skip)
        self._set_work_buttons_enabled(False)
    

    def show_user_selection(self):
        """
        Show user selection dialog on startup.
        Returns True if user was selected, False if cancelled.

        Raises:
            Exception: If user selection fails.
        """
        try:
            # Show loading while fetching user list
            loading = LoadingDialog(self, message="Loading user list...")
            loading.show()
            QCoreApplication.processEvents()
            
            # Fetch user list from web app
            usernames = get_user_list(self.web_app_url)
            loading.close()
            
            # Show user selection dialog
            selected_user = show_user_selection_dialog(usernames, self)
            
            if selected_user:
                self.user = selected_user
                self.setWindowTitle(f"Elastin Queue Tile Viewer - User: {self.user}")
                return True
            else:
                # User cancelled - close the app
                return False
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Loading Users",
                f"Failed to load user list: {str(e)}\n\nPlease check your connection and try again."
            )
            return False


    # ------------------ Actions ------------------
    def on_next(self):
        """Fetch next image from web app, split into tiles, and display in grid."""

        # Clear current view immediately
        self.view.set_title("")
        self.view.set_tiles_with_flags([], [], layout=(0, 0))

        self._busy(True, "Fetching image bytes...")
        self.status.setText("Fetching image bytes...")

        def _task_fetch():
            # Use webapp interface function
            result = fetch_next_image(self.web_app_url, user=self.user)
            
            if result.get("done"):
                return result
            
            # Process the image
            img_rgb = self._to_rgb_uint8(result["img_array"])
            tiles_np, enabled_flags, (rows, cols) = self._split_into_tiles_with_padding(
                img_rgb, tile=self.tile_size, pad_value=0
            )
            return {
                "done": False,
                "data": result["data"],
                "fname": result["fname"],
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
            
            # TODO: Start prefetching next image in background (requires backend "peek_next" action)
            # self._start_prefetch()

        self._run_in_thread(_task_fetch, on_result=_on_result, on_error=self._show_error)


    def on_done(self):
        if not self.current:
            return
        # Determine which tiles have been marked complete and upload only those
        completed_idxs = getattr(self.view, "get_completed_indices", lambda: [])()
        if not completed_idxs:
            QMessageBox.information(self, "Nothing to upload", "No tiles are marked complete. Mark tiles as complete before uploading.")
            return

        tiles_to_upload = [self.tiles_np[i] for i in completed_idxs]
        masks_to_upload = [self.view.get_mask_for_tile(i) for i in completed_idxs]

        self._busy(True, "Uploading completed tiles...")
        self.status.setText("Uploading completed tiles...")

        def _task_upload():
            upload_tiles_batch(base_name=self.image_title.replace(" ", "_"),
                               tiles_rgb=tiles_to_upload,
                               masks=masks_to_upload,
                               source_img_fname=f"{self.image_title}",
                               orig_indices=completed_idxs,
                               author=self.user,
                               save_locally=True,
                               local_output_dir="labeled_tiles")
            return {"count": len(tiles_to_upload)}

        def _on_uploaded(_res):
            self.mark_done()
            self.on_next()

        # Run upload in background thread
        self._run_in_thread(_task_upload, on_result=_on_uploaded, on_error=self._show_error)


    def on_skip(self):
        if not self.current:
            return
        self._busy(True, "Skipping image, please wait...")
        self.status.setText("Skipping image...")

        file_id = self.current["fileId"]

        def _task_skip():
            skip_image(self.web_app_url, file_id)
            return True

        def _on_skipped(_res):
            self.on_next()

        self._run_in_thread(_task_skip, on_result=_on_skipped, on_error=self._show_error)


    def mark_done(self):
        if not self.current:
            return
        file_id = self.current["fileId"]
        mark_image_done(self.web_app_url, file_id)
        self.current = None
        self._set_work_buttons_enabled(False)


    def closeEvent(self, event: QCloseEvent):
        def _task_clean_exit():
            file_id = self.current["fileId"] if self.current else None
            clean_exit(self.web_app_url, file_id=file_id)
        if self.current:
            self._run_in_thread(_task_clean_exit)
        event.accept()


    # ------------------ Helpers ------------------
    def _busy(self, yes: bool, action_text: str = "Processing..."):
        if yes:
            if self._busy_depth == 0:
                # Create and show loading dialog
                self.loading_dialog = LoadingDialog(self, message=action_text)
                self.loading_dialog.show()
                
            self._busy_depth += 1
        else:
            if self._busy_depth > 0:
                self._busy_depth -= 1
            if self._busy_depth == 0:
                # Stop animation and close dialog
                if hasattr(self, 'loading_dialog'):
                    self.loading_dialog.close()
                    delattr(self, 'loading_dialog')
                
                # Process events to ensure UI updates
                QCoreApplication.processEvents()

        # Buttons state
        self.btnNext.setEnabled(self._busy_depth == 0 and self.current is None)
        self.btnDone.setEnabled(self._busy_depth == 0 and self.current is not None)
        self.btnSkip.setEnabled(self._busy_depth == 0 and self.current is not None)


    def _run_in_thread(self, fn: Callable, args: Optional[tuple] = None, kwargs: Optional[dict] = None,
                       on_result: Optional[Callable[[Any], None]] = None,
                       on_error: Optional[Callable[[str], None]] = None):
        """
        Run function fn in a background QThread; ensure busy state is cleared when thread ends.

        Args:
            fn: The function to run in the background.
            args: Arguments to pass to the function.
            kwargs: Keyword arguments to pass to the function.
            on_result: Callback for successful completion.
            on_error: Callback for errors.
        """
        
        args = args or ()
        kwargs = kwargs or {}
        thread = QThread(self)
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
        """Display an error message box and update status label.

        Args:
            message: The error message to display.
        """
        QMessageBox.critical(self, "Error", message)
        self.status.setText(message)


    def _set_work_buttons_enabled(self, enabled: bool):
        """Enable or disable the Done and Skip buttons.

        Args:
            enabled: True to enable the buttons, False to disable them.
        """
        self.btnDone.setEnabled(enabled)
        self.btnSkip.setEnabled(enabled)


    def _start_prefetch(self):
        """Start prefetching the next image in the background."""
        # Cancel any existing prefetch
        if self._prefetch_thread and self._prefetch_thread.isRunning():
            return  # Already prefetching
        
        def _prefetch_task():
            prefetch_next_image(self.web_app_url)
            return None
        
        def _on_prefetch_done(_res):
            # Cleanup
            self._prefetch_thread = None
            self._prefetch_worker = None
        
        def _on_prefetch_error(_msg):
            # Silently fail - prefetch is optional
            self._prefetch_thread = None
            self._prefetch_worker = None
        
        # Don't use _run_in_thread because we don't want busy indicator
        thread = QThread(self)
        worker = Worker(_prefetch_task)
        worker.moveToThread(thread)
        
        self._prefetch_thread = thread
        self._prefetch_worker = worker
        
        thread.started.connect(worker.run)
        worker.finished.connect(lambda res: _on_prefetch_done(res))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda msg: _on_prefetch_error(msg))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()


    @staticmethod
    def _to_rgb_uint8(arr: np.ndarray) -> np.ndarray:
        """
        Converts tifffile output to RGB uint8.
        Handles grayscale, uint16, planar (C,H,W), and channel-order.

        Args:
            arr: Input image array from tifffile
        
        Returns:
            RGB uint8 image array

        Raises:
            ValueError: If the image shape is unsupported for RGB conversion.
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
    def _split_into_tiles_with_padding(img_rgb: np.ndarray, tile: int = TILE_SIZE, pad_value: int = 0):
        """
        Split an RGB image into tiles of given size, padding partial edge tiles.

        Args:
            img_rgb: Input RGB uint8 image array
            tile: Size of square tiles (default 255)
            pad_value: Value to use for padding (default 0)

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



if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Apply dark theme to the entire application
    apply_dark_theme(app)
    
    app.setWindowIcon(QIcon(os.path.join(basedir, "assets", "logo.png")))
    w = MainWindow()
    
    # Show user selection dialog before showing main window
    if w.show_user_selection():
        w.resize(1100, 800)
        w.show()
        sys.exit(app.exec())
    else:
        # User cancelled - exit app
        sys.exit(0)
