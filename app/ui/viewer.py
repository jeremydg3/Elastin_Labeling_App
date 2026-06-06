import sys, os
import io
import base64
import requests
import numpy as np
import cv2
import math
import tifffile
from typing import List, Any, Callable, Optional

from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtCore import pyqtSignal, Qt, QObject, QCoreApplication, QThread, pyqtSlot
from PyQt6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication, QInputDialog

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
    prefetch_next_image,
    clean_cache,
    get_cache_stats,
    save_progress_mask,
    load_progress_mask,
    delete_progress_mask,
    mark_image_in_progress,
    get_in_progress_image
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
        self.btnSaveProgress = QPushButton("💾 Save and Quit")
        self.btnSaveProgress.setToolTip("Save your work in progress and quit")
        self.btnSaveProgress.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnCleanCache = QPushButton("🗑️ Clean Cache")
        self.btnCleanCache.setToolTip("Remove completed images from cache")
        self.btnCleanCache.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status = QLabel("")
        self._busy_depth = 0
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        # Status label will use theme's secondary text color
        self.image_title = ""

        ctl = QHBoxLayout()
        ctl.addWidget(self.btnNext)
        ctl.addWidget(self.btnDone)
        ctl.addWidget(self.btnSkip)
        ctl.addWidget(self.btnSaveProgress)
        ctl.addWidget(self.btnCleanCache)
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
        self.btnSaveProgress.clicked.connect(self.on_save_progress)
        self.btnCleanCache.clicked.connect(self.on_clean_cache)
        self.view.tileCompleted.connect(self._on_tile_completed)
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
                
                # Check for in-progress work
                self._check_and_resume_progress()
                
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


    def _check_and_resume_progress(self):
        """Check if user has in-progress work and resume local matches."""
        try:
            # Query backend for all in_progress work for this user
            result = get_in_progress_image(self.web_app_url, self.user)

            items = result.get("items", [])
            if not items:
                return

            local_matches = []
            for item in items:
                file_id = item.get("fileId")
                if not file_id:
                    continue
                file_name = item.get("fileName", file_id)
                mask_data = load_progress_mask(file_id, self.tile_size)
                if mask_data is None:
                    continue

                local_matches.append({
                    "file_id": file_id,
                    "file_name": file_name,
                    "mask_data": mask_data
                })

            # If backend has in-progress work but none exist in this machine's cache,
            # automatically continue with the next available queue image.
            if not local_matches:
                print("In-progress work found on backend, but no local cached progress matches.")
                self.on_next()
                return

            if len(local_matches) == 1:
                selected = local_matches[0]
            else:
                labels = [f"{m['file_name']} ({m['file_id']})" for m in local_matches]
                selection, ok = QInputDialog.getItem(
                    self,
                    "Resume Progress",
                    "Multiple locally saved images found. Select one to resume:",
                    labels,
                    0,
                    False
                )
                if not ok:
                    return
                selected = local_matches[labels.index(selection)]

            mask_data = selected["mask_data"]
            self._resume_progress(
                selected["file_id"],
                selected["file_name"],
                mask_data['mask'],
                mask_data['completed_tiles'],
                mask_data['working_tiles']
            )
            
        except Exception as e:
            print(f"Error checking for in-progress work: {e}")


    def _resume_progress(self, file_id: str, file_name: str, full_mask: np.ndarray, completed_tiles: set, working_tiles: set):
        """Resume work on an in-progress image."""
        try:
            self._busy(True, "Resuming progress...")
            
            def _task_resume():
                # Fetch the image from cache or backend
                from webapp_interface_funcs import _load_from_cache
                
                # Try cache first
                cached_bytes = _load_from_cache(file_id)
                if cached_bytes:
                    img_array = tifffile.imread(io.BytesIO(cached_bytes))
                else:
                    # Fetch from backend (this won't claim it again since it's in_progress)
                    raw_url = f"{self.web_app_url}?raw={file_id}"
                    rb = requests.get(raw_url, timeout=180)
                    rb.raise_for_status()
                    b = base64.b64decode(rb.text.strip())
                    img_array = tifffile.imread(io.BytesIO(b))
                
                # Process image
                img_rgb = self._to_rgb_uint8(img_array)
                tiles_np, enabled_flags, (rows, cols) = self._split_into_tiles_with_padding(
                    img_rgb, tile=self.tile_size, pad_value=0
                )
                
                # Split mask into tiles
                tile_masks = self._split_full_mask_to_tiles(full_mask, (rows, cols))
                
                return {
                    "fileId": file_id,
                    "fileName": file_name,
                    "img_shape": img_rgb.shape,
                    "tiles": tiles_np,
                    "enabled": enabled_flags,
                    "layout": (rows, cols),
                    "tile_masks": tile_masks,
                    "completed_tiles": completed_tiles,
                    "working_tiles": working_tiles
                }
            
            def _on_resume_result(res: dict):
                # Set up current state
                self.current = {
                    "fileId": res["fileId"],
                    "fileName": res["fileName"],
                    "img_h": res["img_shape"][0],
                    "img_w": res["img_shape"][1],
                    "layout": res["layout"]
                }
                self.image_title = res["fileName"]
                self.view.set_title(self.image_title)
                self.tiles_np = res["tiles"]
                
                # Get tile layout info
                rows, cols = res["layout"]
                img_h, img_w = res["img_shape"][0], res["img_shape"][1]
                
                # Restore completed and working tiles
                completed_tiles = res["completed_tiles"]
                working_tiles = res["working_tiles"]
                print(f"DEBUG: Restoring {len(completed_tiles)} completed tiles: {completed_tiles}")
                print(f"DEBUG: Restoring {len(working_tiles)} working tiles: {working_tiles}")
                
                # Set tiles and restore state manually
                from utils import np_to_qpixmap
                self.view.tiles_pix = [np_to_qpixmap(t) for t in self.tiles_np]
                self.view.enabled = res["enabled"][:]
                self.view._rows, self.view._cols = rows, cols
                
                # Restore masks, completed, and working state BEFORE populating grid
                self.view._masks = res["tile_masks"]
                self.view._completed = completed_tiles
                self.view._working = working_tiles
                
                print(f"DEBUG: Before populate_fixed, _completed = {self.view._completed}, _working = {self.view._working}")
                
                # Populate grid with completed and working tiles
                if hasattr(self.view.grid, 'populate_fixed') and self.view.grid.populate_fixed.__code__.co_argcount >= 7:
                    self.view.grid.populate_fixed(self.view.tiles_pix, self.view.enabled, rows, cols, 
                                                  completed=self.view._completed, working=self.view._working)
                else:
                    self.view.grid.populate_fixed(self.view.tiles_pix, self.view.enabled, rows, cols, 
                                                  completed=self.view._completed)
                
                self.view._show_grid()
                
                print(f"DEBUG: After _show_grid, _completed = {self.view._completed}, _working = {self.view._working}")
                print(f"DEBUG: Grid widget completed state: {getattr(self.view.grid, '_completed', 'N/A')}")
                print(f"DEBUG: Grid widget working state: {getattr(self.view.grid, '_working', 'N/A')}")
                
                self.status.setText(f"{self.image_title}  —  image: {img_w}x{img_h}  tiles: {rows}x{cols} (RESUMED)")
                self._set_work_buttons_enabled(True)
                
                # Start prefetching next image
                self._start_prefetch()
            
            self._run_in_thread(_task_resume, on_result=_on_resume_result, on_error=self._show_error)
            
        except Exception as e:
            self._show_error(f"Failed to resume progress: {e}")


    def _on_tile_completed(self, tile_idx: int):
        """Called when a tile is marked complete - auto-save progress."""
        print(f"Tile {tile_idx} marked complete, auto-saving progress...")
        self._auto_save_progress()


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
            self.current["img_h"] = res["img_shape"][0]
            self.current["img_w"] = res["img_shape"][1]
            self.current["layout"] = res["layout"]
            self.image_title = res["fname"]
            self.view.set_title(self.image_title)
            self.tiles_np = res["tiles"]
            enabled_flags = res["enabled"]
            rows, cols = res["layout"]
            img_h, img_w = res["img_shape"][0], res["img_shape"][1]
            self.view.set_tiles_with_flags(self.tiles_np, enabled_flags, (rows, cols))
            self.status.setText(f"{self.image_title}  —  image: {img_w}x{img_h}  tiles: {rows}x{cols}")
            self._set_work_buttons_enabled(True)
            
            # Start prefetching next image in background
            self._start_prefetch()

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


    def on_save_progress(self):
        """Save progress and quit the application."""
        if not self.current:
            return
        
        # Check if there's any work to save
        if not self.view._masks:
            QMessageBox.information(
                self,
                "Nothing to Save",
                "No tiles have been annotated yet. Mark some tiles as complete before saving."
            )
            return
        
        # Save progress
        self._auto_save_progress()
        
        # Show brief confirmation and quit
        QMessageBox.information(
            self,
            "Progress Saved",
            f"Your work on {self.image_title} has been saved.\n\nClosing application..."
        )
        
        # Quit the application
        QApplication.quit()


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


    def on_clean_cache(self):
        """Clean up cache by removing completed images."""
        # Show current cache stats
        stats = get_cache_stats()
        if "error" in stats:
            QMessageBox.warning(self, "Cache Error", f"Failed to get cache stats: {stats['error']}")
            return
        
        msg = f"Current cache: {stats['file_count']} files, {stats['total_size_mb']} MB\n\nClean up completed images?"
        reply = QMessageBox.question(self, "Clean Cache", msg, 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self._busy(True, "Cleaning cache...")
        self.status.setText("Cleaning cache...")
        
        def _task_clean():
            return clean_cache(self.web_app_url)
        
        def _on_cleaned(result):
            if result.get("ok"):
                msg = f"Cache cleaned!\n\nCompleted images: {result['completed_count']}\nFiles deleted: {result['deleted_count']}"
                QMessageBox.information(self, "Cache Cleaned", msg)
                
                # Update stats
                new_stats = get_cache_stats()
                self.status.setText(f"Cache: {new_stats['file_count']} files, {new_stats['total_size_mb']} MB")
            else:
                QMessageBox.warning(self, "Cache Clean Failed", result.get("message", "Unknown error"))
        
        self._run_in_thread(_task_clean, on_result=_on_cleaned, on_error=self._show_error)


    def mark_done(self):
        if not self.current:
            return
        file_id = self.current["fileId"]
        mark_image_done(self.web_app_url, file_id)
        
        # Delete progress mask and cached image since work is complete
        delete_progress_mask(file_id)
        
        # Also delete the cached image file
        from webapp_interface_funcs import _get_cache_path
        cache_path = _get_cache_path(file_id)
        if cache_path.exists():
            try:
                cache_path.unlink()
                print(f"Deleted cached image: {cache_path}")
            except Exception as e:
                print(f"Failed to delete cached image: {e}")
        
        self.current = None
        self._set_work_buttons_enabled(False)


    def closeEvent(self, event: QCloseEvent):
        # Stop any running prefetch thread
        if self._prefetch_thread and self._prefetch_thread.isRunning():
            self._prefetch_thread.quit()
            self._prefetch_thread.wait(1000)  # Wait up to 1 second
        
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
        """Enable or disable the Done, Skip, and Save Progress buttons.

        Args:
            enabled: True to enable the buttons, False to disable them.
        """
        self.btnDone.setEnabled(enabled)
        self.btnSkip.setEnabled(enabled)
        self.btnSaveProgress.setEnabled(enabled)


    def _start_prefetch(self):
        """Start prefetching the next image in the background."""
        # Cancel any existing prefetch
        if self._prefetch_thread and self._prefetch_thread.isRunning():
            self._prefetch_thread.quit()
            self._prefetch_thread.wait(500)  # Wait briefly for cleanup
        
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


    def _stitch_masks_to_full_image(self, tile_masks: dict[int, np.ndarray], img_shape: tuple, layout: tuple) -> np.ndarray:
        """
        Stitch individual tile masks back into a full image mask.
        
        Args:
            tile_masks: Dictionary mapping tile index to mask array (tile_size x tile_size)
            img_shape: Original image shape (H, W, C)
            layout: Tile layout (rows, cols)
        
        Returns:
            Full image mask (H, W) filled with 255 (empty) and mask data where tiles exist
        """
        rows, cols = layout
        img_h, img_w = img_shape[0], img_shape[1]
        
        # Create full mask initialized to 255 (empty)
        full_mask = np.full((img_h, img_w), 255, dtype=np.uint8)
        
        # Place each tile mask into the full mask
        for tile_idx, mask in tile_masks.items():
            r = tile_idx // cols
            c = tile_idx % cols
            
            y0 = r * self.tile_size
            x0 = c * self.tile_size
            y1 = min(y0 + self.tile_size, img_h)
            x1 = min(x0 + self.tile_size, img_w)
            
            # Extract only the valid portion (no padding)
            h_valid = y1 - y0
            w_valid = x1 - x0
            
            full_mask[y0:y1, x0:x1] = mask[:h_valid, :w_valid]
        
        return full_mask


    def _split_full_mask_to_tiles(self, full_mask: np.ndarray, layout: tuple) -> dict[int, np.ndarray]:
        """
        Split a full image mask into individual tile masks.
        
        Args:
            full_mask: Full image mask (H, W)
            layout: Tile layout (rows, cols)
        
        Returns:
            Dictionary mapping tile index to mask array (tile_size x tile_size)
        """
        rows, cols = layout
        img_h, img_w = full_mask.shape
        tile_masks = {}
        
        for r in range(rows):
            for c in range(cols):
                tile_idx = r * cols + c
                
                y0 = r * self.tile_size
                x0 = c * self.tile_size
                y1 = min(y0 + self.tile_size, img_h)
                x1 = min(x0 + self.tile_size, img_w)
                
                # Extract tile region
                tile_mask = full_mask[y0:y1, x0:x1]
                
                # Pad if necessary
                h, w = tile_mask.shape
                if h < self.tile_size or w < self.tile_size:
                    pad_h = self.tile_size - h
                    pad_w = self.tile_size - w
                    tile_mask = np.pad(
                        tile_mask,
                        ((0, pad_h), (0, pad_w)),
                        mode="constant",
                        constant_values=255
                    )
                
                # Only store if there's actual mask data (not all 255)
                if not np.all(tile_mask == 255):
                    tile_masks[tile_idx] = tile_mask.astype(np.uint8)
        
        return tile_masks


    def _auto_save_progress(self):
        """Automatically save progress after user makes changes."""
        if not self.current:
            return
        
        file_id = self.current["fileId"]
        
        # Get all tile masks from the view
        tile_masks = self.view._masks  # Access internal masks dict
        
        if not tile_masks:
            # No work done yet, don't save
            return
        
        # Stitch masks into full image mask
        img_shape = (self.current.get("img_h", 0), self.current.get("img_w", 0), 3)
        layout = self.current.get("layout", (0, 0))
        
        full_mask = self._stitch_masks_to_full_image(tile_masks, img_shape, layout)
        
        # Get tile completion status and working status
        completed_tiles_dict = {idx: True for idx in self.view.get_completed_indices()}
        working_tiles_set = self.view._working
        
        # Save to cache with completion and working status encoded as decimals
        if save_progress_mask(file_id, full_mask, completed_tiles_dict, working_tiles_set, self.tile_size, layout):
            # Mark as in_progress on backend
            mark_image_in_progress(self.web_app_url, file_id, self.user)
            print(f"Auto-saved progress for {file_id}")



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
