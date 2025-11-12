from typing import Optional

from PyQt6.QtGui import QPixmap, QPainter, QResizeEvent, QColor
from PyQt6.QtCore import pyqtSignal, Qt, QPoint
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QMenu

import os
from tile_item import TileItem
from styles import get_tile_grid_background

basedir = os.path.dirname(__file__)


class TileGridView(QGraphicsView):
    """
    A fixed grid view of tiles with context menu support.
    Emits signals when tiles are clicked or context menu actions are requested.
    """
    tileChosen = pyqtSignal(int)
    toggleComplete = pyqtSignal(int)  # request from context menu
    toggleWorking = pyqtSignal(int)   # request from context menu

    def __init__(self, parent=None, tile_px: int = 255, pad: int = 8):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QColor(get_tile_grid_background()))
        self.tile_px = tile_px
        self.pad = pad
        self._pixmaps: list[QPixmap] = []
        self._enabled: list[bool] = []
        self._rows = 0
        self._cols = 0


    def populate_fixed(self, tiles_pix: list[QPixmap], enabled: list[bool], rows: int, cols: int,
                       completed: Optional[set[int]] = None, working: Optional[set[int]] = None):
        """
        Fixed grid layout (rows x cols). No re-arranging on resize.
        
        Args:
            tiles_pix: List of QPixmap tiles
            enabled: List of booleans indicating if each tile is enabled
            rows: Number of rows in the grid
            cols: Number of columns in the grid
            completed: Optional set of indices that are marked as completed
        """
        assert rows * cols == len(tiles_pix), "rows*cols must equal number of tiles"

        self._pixmaps = tiles_pix[:]
        self._enabled = enabled[:]
        self._rows, self._cols = rows, cols
        if completed is None:
            completed = set()
        if working is None:
            working = set()
        self._completed_set = set(completed)
        self._working_set = set(working)

        sc = self.scene()
        if sc is None:
            sc = QGraphicsScene(self)
            self.setScene(sc)
        sc.clear()

        tp, pad = self.tile_px, self.pad
        idx = 0
        self._items: list[TileItem] = []
        for r in range(rows):
            for c in range(cols):
                pix = self._pixmaps[idx]
                it = TileItem(idx, pix, tp, enabled=self._enabled[idx], completed=(idx in completed), working=(idx in working))  # QGraphicsObject
                it.setPos(c * (tp + pad), r * (tp + pad))  # fixed slots
                it.tileClicked.connect(self.tileChosen.emit)
                it.contextRequested.connect(self._on_item_context)
                sc.addItem(it)
                self._items.append(it)
                idx += 1

        total_w = cols * (tp + pad) - pad
        total_h = rows * (tp + pad) - pad
        sc.setSceneRect(0, 0, total_w, total_h)

        # Fit once initially
        self._fit_scene()


    def set_completed(self, completed: set[int]):
        """Update completion overlay for all items based on a set of indices."""
        self._completed_set = set(completed)
        if not hasattr(self, "_items"):
            return
        for it in self._items:
            it.set_completed(it.index in self._completed_set)

    def set_working(self, working: set[int]):
        """Update working overlay for all items based on a set of indices."""
        self._working_set = set(working)
        if not hasattr(self, "_items"):
            return
        for it in self._items:
            it.set_working(it.index in self._working_set)


    def _on_item_context(self, idx: int, global_pt: QPoint):
        # Build a context menu with 3 mutually exclusive states
        menu = QMenu()
        is_completed = idx in getattr(self, "_completed_set", set())
        is_working = idx in getattr(self, "_working_set", set())

        # Show options based on current state (3 mutually exclusive states)
        if is_completed:
            # Currently completed -> offer to mark working or clear
            act_mark_working = menu.addAction("⧗ Mark Working")
            act_clear = menu.addAction("Clear Status")
            
            chosen = menu.exec(global_pt)
            if chosen == act_mark_working:
                self.toggleWorking.emit(idx)
            elif chosen == act_clear:
                self.toggleComplete.emit(idx)  # Remove completed status
        elif is_working:
            # Currently working -> offer to mark complete or clear
            act_mark_complete = menu.addAction("✓ Mark Complete")
            act_clear = menu.addAction("Clear Status")
            
            chosen = menu.exec(global_pt)
            if chosen == act_mark_complete:
                self.toggleComplete.emit(idx)
            elif chosen == act_clear:
                self.toggleWorking.emit(idx)  # Remove working status
        else:
            # Currently neither -> offer both options
            act_mark_complete = menu.addAction("✓ Mark Complete")
            act_mark_working = menu.addAction("⧗ Mark Working")
            
            chosen = menu.exec(global_pt)
            if chosen == act_mark_complete:
                self.toggleComplete.emit(idx)
            elif chosen == act_mark_working:
                self.toggleWorking.emit(idx)


    def _fit_scene(self):
        scene = self.scene()
        if scene is None or not scene.items():
            return
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


    def resizeEvent(self, e: QResizeEvent) -> None:
        # DO NOT reflow—just scale the view to fit the fixed scene rect
        self._fit_scene()
        super().resizeEvent(e)
