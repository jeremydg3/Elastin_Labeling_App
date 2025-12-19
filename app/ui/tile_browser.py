import numpy as np
from typing import List, Tuple

from PyQt6.QtGui import QPixmap, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QLabel, QWidget, QVBoxLayout, QPushButton, 
                             QHBoxLayout, QStackedLayout)

from group_bar import GroupBar
from tile_detail_view import TileDetailView
from utils import np_to_qpixmap
from tile_grid_view import TileGridView

class TileBrowser(QWidget):
    """
    Grid + detail with paint overlay per tile.
    """
    tileChosen = pyqtSignal(int)
    tileCompleted = pyqtSignal(int)  # emits tile index when marked complete

    def __init__(self, parent=None, tile_px: int = 256):
        super().__init__(parent)
        self.tile_px = tile_px
        self.tiles_pix: List[QPixmap] = []
        self.enabled: List[bool] = []
        self._rows = 0
        self._cols = 0
        self._masks: dict[int, np.ndarray] = {}  # tile_index -> mask (uint8 HxW, 0..9, 255=empty)
        self._completed: set[int] = set()
        self._working: set[int] = set()

        # Top bar: Back + swatches + Mark complete button
        self.btnBack = QPushButton("← Back")
        self.btnBack.setVisible(False)
        self.btnBack.setToolTip("Return to tile grid view")
        self.btnBack.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnMarkComplete = QPushButton("✓ Mark Complete")
        self.btnMarkComplete.setVisible(False)
        self.btnMarkComplete.setProperty("success", True)  # Use dark theme success button style
        self.btnMarkComplete.setToolTip("Mark this tile as complete")
        self.btnMarkComplete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnMarkWorking = QPushButton("⧗ Mark Working")
        self.btnMarkWorking.setVisible(False)
        self.btnMarkWorking.setProperty("working", True)  # Use dark theme working button style
        self.btnMarkWorking.setToolTip("Mark this tile as 'working on it'")
        self.btnMarkWorking.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title = QLabel("")
        self.title.setProperty("heading", True)  # Use dark theme heading style
        self.groups = GroupBar()
        self.groups.setVisible(False)  # Hidden by default (grid view)
        self.groups.eraserChanged.connect(self._on_eraser_changed)

        top = QHBoxLayout()
        top.addWidget(self.btnBack)
        top.addSpacing(12)
        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.btnMarkWorking)
        header.addWidget(self.btnMarkComplete)

        topwrap = QVBoxLayout()
        topwrap.setContentsMargins(0,0,0,0)
        topwrap.setSpacing(4)
        topwrap.addLayout(header)
        topwrap.addWidget(self.groups)

        top.addLayout(topwrap, 1)

        # Views
        self.grid = TileGridView(tile_px=self.tile_px)
        self.detail = TileDetailView(brush_radius=10)

        self.stack = QStackedLayout()
        self.stack.addWidget(self.grid)    # 0
        self.stack.addWidget(self.detail)  # 1

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(self.stack, 1)

        # wiring
        self.grid.tileChosen.connect(self._on_tile_clicked)
        self.grid.toggleComplete.connect(self._on_grid_toggle_complete)

        # Connect working toggle if available on grid
        if hasattr(self.grid, 'toggleWorking'):
            self.grid.toggleWorking.connect(self._on_grid_toggle_working)
        self.btnBack.clicked.connect(self._on_back)
        self.btnMarkComplete.clicked.connect(self._on_mark_complete)
        self.btnMarkWorking.clicked.connect(self._on_mark_working)
        self.groups.activeChanged.connect(self._on_group_changed)

        # Connect detail view firstPaintStroke for auto-marking as working
        self.detail.firstPaintStroke.connect(self._on_first_paint_stroke)

        # keyboard focus for number hotkeys
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._current_idx = None

    # ---- public API ----
    def set_title(self, text: str):
        self.title.setText(text)


    def set_tiles_with_flags(self, tiles_np: List[np.ndarray], enabled: List[bool], layout: Tuple[int,int]):
        # New image: reset all per-image state
        self.tiles_pix = [np_to_qpixmap(t) for t in tiles_np]
        self.enabled = enabled[:]
        self._rows, self._cols = layout
        self._completed.clear()    # reset completed state for new image
        self._working.clear()      # reset working state for new image
        self._masks.clear()        # reset stored masks for all tiles
        self._current_idx = None   # clear any in-progress detail selection
        # populate with both completed and working sets if supported
        if hasattr(self.grid, 'populate_fixed') and self.grid.populate_fixed.__code__.co_argcount >= 7:
            self.grid.populate_fixed(self.tiles_pix, self.enabled, self._rows, self._cols, completed=self._completed, working=self._working)
        else:
            self.grid.populate_fixed(self.tiles_pix, self.enabled, self._rows, self._cols, completed=self._completed)
        self._show_grid()


    def set_tiles(self, tiles_np: List[np.ndarray], layout: Tuple[int,int]):
        self.set_tiles_with_flags(tiles_np, [True]*len(tiles_np), layout)


    def get_mask_for_tile(self, idx: int) -> np.ndarray:
        """Return saved mask for tile idx, or None if none exists."""
        mask = self._masks.get(idx)
        if mask is None:
            return np.full((self.tile_px, self.tile_px), 255, dtype=np.uint8)
        return mask.copy()


    def get_completed_indices(self) -> List[int]:
        """Return a sorted list of tile indices marked as complete."""
        return sorted(self._completed)
    

    # ---- interactions ----
    def _on_eraser_changed(self, on: bool):
        self.detail.set_eraser(on)


    def _on_tile_clicked(self, idx: int):
        if not self.enabled[idx]: return
        self._current_idx = idx
        self.detail.set_base_pixmap(self.tiles_pix[idx])
        self.detail.set_mask(self._masks.get(idx))
        
        # Set surrounding tiles for context
        neighbors = self._get_surrounding_tiles(idx)
        self.detail.set_surrounding_tiles(neighbors)
        
        self.btnBack.setVisible(True)
        self.btnMarkComplete.setVisible(True)
        self.btnMarkWorking.setVisible(True)
        # Toggle button label based on completion state
        if idx in self._completed:
            self.btnMarkComplete.setText("Unmark Complete")
        else:
            self.btnMarkComplete.setText("✓ Mark Complete")
        # Toggle button label based on working state
        if idx in self._working:
            self.btnMarkWorking.setText("Unmark Working")
        else:
            self.btnMarkWorking.setText("⧗ Mark Working")
        self.groups.setVisible(True)  # Show swatch bar in detail view
        self.stack.setCurrentIndex(1)
        # sync current states
        self.detail.set_active_group(self.groups.active())
        self.detail.set_eraser(self.groups.eraser())


    def _get_surrounding_tiles(self, idx: int) -> list[tuple]:
        """
        Get the 8 surrounding tiles for a given index.
        Returns list of 8 tuples (pixmap, mask) in order: [TL, T, TR, L, R, BL, B, BR]
        Returns (None, None) for positions outside the grid.
        """
        row = idx // self._cols
        col = idx % self._cols
        
        neighbors = []
        # Order: [top-left, top, top-right, left, right, bottom-left, bottom, bottom-right]
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        
        for dr, dc in offsets:
            nr, nc = row + dr, col + dc
            # Check if neighbor is within grid bounds
            if 0 <= nr < self._rows and 0 <= nc < self._cols:
                n_idx = nr * self._cols + nc
                pix = self.tiles_pix[n_idx] if n_idx < len(self.tiles_pix) else None
                mask = self._masks.get(n_idx)
                neighbors.append((pix, mask))
            else:
                neighbors.append((None, None))
        
        return neighbors


    def _on_back(self):
        # save mask for current tile
        if self._current_idx is not None:
            m = self.detail.get_mask()
            if m is not None:
                self._masks[self._current_idx] = m
        self._show_grid()


    def _on_mark_complete(self):
        """Mark current tile as complete and save mask."""
        if self._current_idx is not None:
            m = self.detail.get_mask()
            if m is not None:
                self._masks[self._current_idx] = m
            # toggle completion state and update grid overlays
            if self._current_idx in self._completed: # If already completed, unmark
                self._completed.remove(self._current_idx)
                self.btnMarkComplete.setText("✓ Mark Complete")
            else: # Mark as complete
                self._completed.add(self._current_idx)
                self.btnMarkComplete.setText("Unmark Complete")
                self.tileCompleted.emit(self._current_idx)
                if self._current_idx in self._working: # Remove from working if completed
                    self._working.remove(self._current_idx)
                    self.btnMarkWorking.setText("⧗ Mark Working")
            self.grid.set_completed(self._completed)
            # if hasattr(self.grid, 'set_working'):
            self.grid.set_working(self._working)
            self._show_grid()

    def _on_mark_working(self):
        """Mark current tile as working and save mask."""
        if self._current_idx is not None:
            m = self.detail.get_mask()
            if m is not None:
                self._masks[self._current_idx] = m
            # toggle working state and update grid overlays
            if self._current_idx in self._working: # If already working, unmark
                self._working.remove(self._current_idx)
                self.btnMarkWorking.setText("⧗ Mark Working")
            else: # Mark as working
                self._working.add(self._current_idx)
                self.btnMarkWorking.setText("Unmark Working")
                if self._current_idx in self._completed: # Remove from completed if working
                    self._completed.remove(self._current_idx)
                    self.btnMarkComplete.setText("✓ Mark Complete")
            # if hasattr(self.grid, 'set_working'):
            self.grid.set_working(self._working)
            self.grid.set_completed(self._completed)
            self._show_grid()


    def _on_first_paint_stroke(self):
        """Auto-mark tile as working when user begins painting (if not already complete)."""
        if self._current_idx is None:
            return
        # Don't auto-mark if tile is already completed
        if self._current_idx in self._completed:
            return
        # Don't auto-mark if already working
        if self._current_idx in self._working:
            return
        # Add to working set and update UI
        self._working.add(self._current_idx)
        self.btnMarkWorking.setText("Unmark Working")
        # Update grid overlays
        # if hasattr(self.grid, 'set_working'):
        self.grid.set_working(self._working)
        self.grid.set_completed(self._completed)


    def _show_grid(self):
        self.stack.setCurrentIndex(0)
        self.btnBack.setVisible(False)
        self.btnMarkComplete.setVisible(False)
        self.btnMarkWorking.setVisible(False)
        self.groups.setVisible(False)  # Hide swatch bar in grid view


    def _on_group_changed(self, gid: int):
        # Only force eraser OFF when a concrete group is selected (gid != -1).
        # When gid == -1 (e.g., switching to eraser), don't turn it off here.
        if gid != -1 and self.groups.eraser():
            self.groups.set_eraser(False)
        self.detail.set_active_group(gid)


    def _on_grid_toggle_complete(self, idx: int):
        # Toggle completion in the browser's source-of-truth set
        # States are mutually exclusive: completed, working, or neither
        if idx in self._completed:
            # Already completed -> remove (clear status)
            self._completed.remove(idx)
        else:
            # Mark as completed and remove from working if present
            self._completed.add(idx)
            if idx in self._working:
                self._working.remove(idx)
        
        # Update grid display
        self.grid.set_working(self._working)
        self.grid.set_completed(self._completed)
        
        # If currently viewing this tile in detail, update button labels
        if self._current_idx == idx and self.btnMarkComplete.isVisible():
            self.btnMarkComplete.setText("Unmark Complete" if idx in self._completed else "✓ Mark Complete")
            self.btnMarkWorking.setText("⧗ Mark Working" if idx not in self._working else "Unmark Working")

    def _on_grid_toggle_working(self, idx: int):
        # Toggle working in the browser's source-of-truth set
        # States are mutually exclusive: completed, working, or neither
        if idx in self._working:
            # Already working -> remove (clear status)
            self._working.remove(idx)
        else:
            # Mark as working and remove from completed if present
            self._working.add(idx)
            if idx in self._completed:
                self._completed.remove(idx)
        
        # Update grid display
        self.grid.set_working(self._working)
        self.grid.set_completed(self._completed)
        
        # If currently viewing this tile in detail, update button labels
        if self._current_idx == idx and self.btnMarkWorking.isVisible():
            self.btnMarkWorking.setText("Unmark Working" if idx in self._working else "⧗ Mark Working")
            self.btnMarkComplete.setText("✓ Mark Complete" if idx not in self._completed else "Unmark Complete")


    # ---- hotkeys 0..9 to toggle active group or 'e' to toggle eraser ----
    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            gid = key - Qt.Key.Key_0
            self.groups.set_eraser(False)  # numbers always paint
            self.groups.set_active(-1 if self.groups.active() == gid else gid)
            e.accept(); return
        if key == Qt.Key.Key_E:
            self.groups.set_eraser(not self.groups.eraser())
            e.accept(); return
        super().keyPressEvent(e)
