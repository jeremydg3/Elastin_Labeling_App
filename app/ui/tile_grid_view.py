import numpy as np
from typing import List, Optional
from PyQt6 import QtWidgets, QtGui, QtCore
from group_bar import GROUP_COLORS, GroupBar
from typing import List, Tuple
from pathlib import Path


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

class TileItem(QtWidgets.QGraphicsObject):
    tileClicked = QtCore.pyqtSignal(int)
    contextRequested = QtCore.pyqtSignal(int, QtCore.QPoint)  # (index, global point)
    _badge_icon: QtGui.QPixmap | None = None  # lazy-loaded checkmark icon

    @staticmethod
    def _load_badge_icon() -> QtGui.QPixmap | None:
        if TileItem._badge_icon is not None:
            return TileItem._badge_icon
        try:
            icon_path = Path(__file__).resolve().parent.parent / "assets" / "complete_icon.png"
            pm = QtGui.QPixmap(str(icon_path))
            if not pm.isNull():
                TileItem._badge_icon = pm
                return pm
        except Exception:
            pass
        TileItem._badge_icon = None
        return None

    def __init__(self, index: int, pix: QtGui.QPixmap, tile_size: int, enabled: bool, completed: bool = False):
        super().__init__()
        self.index = index
        self.pix = pix
        self.tile_size = tile_size
        self.enabled_flag = enabled
        self.completed = completed
        self._hover = False

        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor if enabled else QtCore.Qt.CursorShape.ArrowCursor)

    # --- QGraphicsObject requirements ---
    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0, 0, self.tile_size, self.tile_size)

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget=None):
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)

        # draw the tile pixmap scaled to the box
        painter.drawPixmap(0, 0, self.tile_size, self.tile_size, self.pix)

        # subtle outline
        painter.setPen(QtGui.QPen(QtGui.QColor(230, 230, 230)))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(1, 1, self.tile_size - 1, self.tile_size - 1)

        # hover highlight (enabled tiles only)
        if self._hover and self.enabled_flag:
            pen = QtGui.QPen(QtGui.QColor(66, 133, 244))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(2, 2, self.tile_size - 2, self.tile_size - 2)

        # dim overlay for disabled/partial tiles
        if not self.enabled_flag:
            painter.fillRect(self.boundingRect(), QtGui.QColor(255, 255, 255, 140))

        # completed overlay (semi-transparent green) + small badge in top-right
        if self.completed:
            painter.fillRect(self.boundingRect(), QtGui.QColor(76, 175, 80, 110))

            # draw badge
            margin = max(3, self.tile_size // 40)
            badge = max(14, min(24, self.tile_size // 10))
            x = self.tile_size - margin - badge
            y = margin

            painter.save()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            # background circle for contrast
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(255, 255, 255, 220))
            painter.drawEllipse(x, y, badge, badge)

            icon = TileItem._load_badge_icon()
            if icon is not None:
                painter.drawPixmap(x, y, badge, badge, icon)
            else:
                # Fallback: draw a green checkmark
                pen = QtGui.QPen(QtGui.QColor(76, 175, 80))
                pen.setWidth(max(2, badge // 8))
                pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                # simple check path
                x0 = x + badge * 0.25
                y0 = y + badge * 0.55
                x1 = x + badge * 0.45
                y1 = y + badge * 0.75
                x2 = x + badge * 0.78
                y2 = y + badge * 0.30
                painter.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y1))
                painter.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
            painter.restore()

    def set_completed(self, done: bool):
        if self.completed != done:
            self.completed = done
            self.update()

    # --- events ---
    def hoverEnterEvent(self, e: QtWidgets.QGraphicsSceneHoverEvent):
        if self.enabled_flag:
            self._hover = True
            self.update()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e: QtWidgets.QGraphicsSceneHoverEvent):
        if self._hover:
            self._hover = False
            self.update()
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e: QtWidgets.QGraphicsSceneMouseEvent):
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            # request context menu at screen position
            gp = e.screenPos()
            self.contextRequested.emit(self.index, gp)
            e.accept()
            return
        if self.enabled_flag and e.button() == QtCore.Qt.MouseButton.LeftButton:
            self.tileClicked.emit(self.index)
        # swallow clicks when disabled
        super().mousePressEvent(e)


class TileGridView(QtWidgets.QGraphicsView):
    tileChosen = QtCore.pyqtSignal(int)
    toggleComplete = QtCore.pyqtSignal(int)  # request from context menu

    def __init__(self, parent=None, tile_px: int = 255, pad: int = 8):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QtGui.QColor("#f8f9fa"))
        self.tile_px = tile_px
        self.pad = pad
        self._pixmaps: list[QtGui.QPixmap] = []
        self._enabled: list[bool] = []
        self._rows = 0
        self._cols = 0

    def populate_fixed(self, tiles_pix: list[QtGui.QPixmap], enabled: list[bool], rows: int, cols: int, completed: Optional[set[int]] = None):
        """Fixed grid layout (rows x cols). No re-arranging on resize."""
        assert rows * cols == len(tiles_pix), "rows*cols must equal number of tiles"

        self._pixmaps = tiles_pix[:]
        self._enabled = enabled[:]
        self._rows, self._cols = rows, cols
        if completed is None:
            completed = set()
        self._completed_set = set(completed)

        sc = self.scene()
        if sc is None:
            sc = QtWidgets.QGraphicsScene(self)
            self.setScene(sc)
        sc.clear()

        tp, pad = self.tile_px, self.pad
        idx = 0
        self._items: list[TileItem] = []
        for r in range(rows):
            for c in range(cols):
                pix = self._pixmaps[idx]
                it = TileItem(idx, pix, tp, enabled=self._enabled[idx], completed=(idx in completed))  # QGraphicsObject
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

    def _on_item_context(self, idx: int, global_pt: QtCore.QPoint):
        # Build a simple context menu to toggle completion
        menu = QtWidgets.QMenu()
        is_completed = idx in getattr(self, "_completed_set", set())
        action_text = "Unmark Complete" if is_completed else "✓ Mark Complete"
        act_toggle = menu.addAction(action_text)
        chosen = menu.exec(global_pt)
        if chosen == act_toggle:
            self.toggleComplete.emit(idx)

    def _fit_scene(self):
        scene = self.scene()
        if scene is None or not scene.items():
            return
        self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        # DO NOT reflow—just scale the view to fit the fixed scene rect
        self._fit_scene()
        super().resizeEvent(e)


class TileDetailView(QtWidgets.QGraphicsView):
    """
    Shows one tile pixmap + a paintable overlay mask.
    - Mask is uint8 (0..9 = group id, 255 = empty)
    - Brush paints circle into mask, which is composited to a top overlay pixmap
    """
    maskChanged = QtCore.pyqtSignal()  # emitted on paint edits

    def __init__(self, brush_radius: int = 10, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._base_item = None
        self._overlay_item = None
        self._cursor_item = QtWidgets.QGraphicsEllipseItem()
        self._cursor_item.setZValue(99)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 220))  # default brush outline
        pen.setWidth(10)
        self._cursor_item.setPen(pen)
        self._cursor_item.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        self._cursor_item.setVisible(False)
        self._eraser = False
        
        # Ensure scene exists before adding items
        scene = self.scene()
        if scene is None:
            scene = QtWidgets.QGraphicsScene(self)
            self.setScene(scene)
            scene.addItem(self._cursor_item)

        self._pix = None
        self._mask = None  # uint8 HxW (0..9, 255 empty)
        self._overlay_pm = None
        self._brush_radius = brush_radius
        self._active_group = -1
        self._painting = False

    # ---- public API ----
    def set_eraser(self, active: bool):
        self._eraser = bool(active)
        # Show brush cursor if eraser or a group is active
        self._cursor_item.setVisible(self._eraser or self._active_group != -1)
        # Change cursor ring color to indicate eraser
        pen = QtGui.QPen(QtGui.QColor(255, 170, 0, 240) if self._eraser else QtGui.QColor(255, 255, 255, 220))
        pen.setWidth(1)
        self._cursor_item.setPen(pen)

    # --- tweak existing set_active_group to play nice with eraser ---
    def set_active_group(self, gid: int):
        """-1 to deactivate."""
        self._active_group = gid
        # cursor visible if eraser or group active
        self._cursor_item.setVisible(self._eraser or gid != -1)


    # --- modify _paint_at to erase when eraser is active ---
    def _paint_at(self, x_scene: float, y_scene: float):
        if self._mask is None or self._pix is None:
            return
        if not self._eraser and self._active_group == -1:
            return

        x = int(round(x_scene)); y = int(round(y_scene))
        h, w = self._mask.shape
        r = self._brush_radius
        xmin = max(0, x - r); xmax = min(w - 1, x + r)
        ymin = max(0, y - r); ymax = min(h - 1, y + r)
        rr2 = r * r

        sub = self._mask[ymin:ymax+1, xmin:xmax+1]
        yy, xx = np.ogrid[ymin:ymax+1, xmin:xmax+1]
        dx = xx - x; dy = yy - y
        circle = (dx*dx + dy*dy) <= rr2

        if self._eraser:
            # self._mask[ymin:ymax+1, xmin:xmax+1][circle] = np.uint8(255)   # erase
            sub[circle] = np.uint8(255)  
        else:
            # self._mask[ymin:ymax+1, xmin:xmax+1][circle] = np.uint8(self._active_group)
            sub[circle] = np.uint8(self._active_group)

        self._mask[ymin:ymax+1, xmin:xmax+1] = sub          # <-- write back
        self._rebuild_overlay()
        self.maskChanged.emit()


    def set_base_pixmap(self, pix: QtGui.QPixmap):
        scene = self.scene()
        if scene is not None:
            # Remove cursor from scene before clearing to prevent deletion
            if self._cursor_item.scene() is not None:
                scene.removeItem(self._cursor_item)
            scene.clear()
        else:
            scene = QtWidgets.QGraphicsScene(self)
            self.setScene(scene)
        
        self._base_item = scene.addPixmap(pix)
        # self._base_item.setZValue(0)
        self._pix = pix

        # overlay
        self._overlay_pm = QtGui.QPixmap(pix.size())
        self._overlay_pm.fill(QtCore.Qt.GlobalColor.transparent)
        self._overlay_item = scene.addPixmap(self._overlay_pm)
        if self._overlay_item is not None:
            self._overlay_item.setZValue(10)

        # cursor back on top
        scene.addItem(self._cursor_item)

        if self._base_item is not None:
            scene.setSceneRect(self._base_item.boundingRect())
        self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def set_mask(self, mask: np.ndarray | None):
        """mask: uint8 HxW, values {0..9, 255}, or None -> create empty"""
        if self._pix is None:
            return
        w = self._pix.width()
        h = self._pix.height()
        if mask is None:
            self._mask = np.full((h, w), 255, dtype=np.uint8)
        else:
            assert mask.shape == (h, w) and mask.dtype == np.uint8
            self._mask = mask.copy()
        self._rebuild_overlay()

    def get_mask(self):
        return None if self._mask is None else self._mask.copy()

    # ---- overlay composition ----
    def _rebuild_overlay(self):
        """Rebuild overlay pixmap from mask array (fast path)."""
        if self._mask is None or self._pix is None or self._overlay_item is None:
            return
        h, w = self._mask.shape
        # RGBA overlay
        overlay = np.zeros((h, w, 4), dtype=np.uint8)
        # draw each group color with alpha
        alpha = 110  # semi-transparent
        for gid, hexc in GROUP_COLORS.items():
            sel = (self._mask == gid)
            if not np.any(sel):
                continue
            c = QtGui.QColor(hexc)
            overlay[sel, 0] = c.red()
            overlay[sel, 1] = c.green()
            overlay[sel, 2] = c.blue()
            overlay[sel, 3] = alpha
        # convert to QImage -> QPixmap
        qimg = QtGui.QImage(overlay.data, w, h, 4*w, QtGui.QImage.Format.Format_RGBA8888)
        self._overlay_pm = QtGui.QPixmap.fromImage(qimg)
        self._overlay_item.setPixmap(self._overlay_pm)

    # ---- painting ----
    def _img_pos_from_view(self, ev: QtGui.QMouseEvent | QtGui.QHoverEvent):
        sp = self.mapToScene(ev.position().toPoint())
        return sp.x(), sp.y()

    # ---- events ----
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        # Left-click starts a paint stroke if a tool is active
        if e.button() == QtCore.Qt.MouseButton.LeftButton and (self._eraser or self._active_group != -1):
            # ensure we receive keyboard events (0–9, E, +/-)
            self.setFocus()

            # where in the image (scene) did we click?
            x, y = self._img_pos_from_view(e)

            # show/update brush cursor at press location
            r = int(self._brush_radius)
            self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)
            self._cursor_item.setVisible(True)

            # begin stroke + lay down initial dab
            self._painting = True
            self._paint_at(x, y)   # uses cv2.circle(...) inside
            e.accept()
            return

        # Right-click to pan
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
            # Create a fake left-click event to start panning
            fake_event = QtGui.QMouseEvent(
                e.type(), e.position(), e.globalPosition(),
                QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
                e.modifiers()
            )
            super().mousePressEvent(fake_event)
            e.accept()
            return

        # otherwise, pass to default handler (e.g., for selection, focus, etc.)
        super().mousePressEvent(e)


    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        # move brush cursor
        x, y = self._img_pos_from_view(e)
        r = self._brush_radius
        self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)

        if self._painting and (self._eraser or self._active_group != -1):
            self._paint_at(x, y)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.MouseButton.LeftButton and self._painting:
            self._painting = False
            e.accept()
            return
        
        # Right-click release to stop panning
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            e.accept()
            return
        
        super().mouseReleaseEvent(e)

    # optional: +/− to change brush size
    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() in (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal):
            self._brush_radius = min(128, self._brush_radius + 1)
            # Update cursor size immediately
            if self._cursor_item.isVisible():
                x, y = self._cursor_item.rect().center().x(), self._cursor_item.rect().center().y()
                r = self._brush_radius
                self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)
                e.accept(); return
        if e.key() == QtCore.Qt.Key.Key_Minus:
            self._brush_radius = max(1, self._brush_radius - 1)
            # Update cursor size immediately
            if self._cursor_item.isVisible():
                x, y = self._cursor_item.rect().center().x(), self._cursor_item.rect().center().y()
                r = self._brush_radius
                self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)
                e.accept(); return
        super().keyPressEvent(e)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


class TileBrowser(QtWidgets.QWidget):
    """
    Grid + detail with paint overlay per tile.
    """
    tileChosen = QtCore.pyqtSignal(int)
    tileCompleted = QtCore.pyqtSignal(int)  # emits tile index when marked complete

    def __init__(self, parent=None, tile_px: int = 256):
        super().__init__(parent)
        self.tile_px = tile_px
        self.tiles_pix: List[QtGui.QPixmap] = []
        self.enabled: List[bool] = []
        self._rows = 0
        self._cols = 0
        self._masks: dict[int, np.ndarray] = {}  # tile_index -> mask (uint8 HxW, 0..9, 255=empty)
        self._completed: set[int] = set()

        # Top bar: Back + swatches + Mark complete button
        self.btnBack = QtWidgets.QPushButton("← Back")
        self.btnBack.setVisible(False)
        self.btnMarkComplete = QtWidgets.QPushButton("✓ Mark Complete")
        self.btnMarkComplete.setVisible(False)
        self.btnMarkComplete.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 6px 12px; font-weight: 600; }")
        self.title = QtWidgets.QLabel("")
        self.title.setStyleSheet("font-weight: 600;")
        self.groups = GroupBar()
        self.groups.setVisible(False)  # Hidden by default (grid view)
        self.groups.eraserChanged.connect(self._on_eraser_changed)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.btnBack)
        top.addSpacing(12)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.btnMarkComplete)

        topwrap = QtWidgets.QVBoxLayout()
        topwrap.setContentsMargins(0,0,0,0)
        topwrap.setSpacing(4)
        topwrap.addLayout(header)
        topwrap.addWidget(self.groups)

        top.addLayout(topwrap, 1)

        # Views
        self.grid = TileGridView(tile_px=self.tile_px)
        self.detail = TileDetailView(brush_radius=10)

        self.stack = QtWidgets.QStackedLayout()
        self.stack.addWidget(self.grid)    # 0
        self.stack.addWidget(self.detail)  # 1

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(self.stack, 1)

        # wiring
        self.grid.tileChosen.connect(self._on_tile_clicked)
        self.grid.toggleComplete.connect(self._on_grid_toggle_complete)
        self.btnBack.clicked.connect(self._on_back)
        self.btnMarkComplete.clicked.connect(self._on_mark_complete)
        self.groups.activeChanged.connect(self._on_group_changed)

        # keyboard focus for number hotkeys
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self._current_idx = None

    # ---- public API ----
    def set_title(self, text: str):
        self.title.setText(text)

    def set_tiles_with_flags(self, tiles_np: List[np.ndarray], enabled: List[bool], layout: Tuple[int,int]):
        self.tiles_pix = [np_to_qpixmap(t) for t in tiles_np]
        self.enabled = enabled[:]
        self._rows, self._cols = layout
        self._completed.clear()  # reset completed state for new image
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
        self.btnBack.setVisible(True)
        self.btnMarkComplete.setVisible(True)
        # Toggle button label based on completion state
        if idx in self._completed:
            self.btnMarkComplete.setText("Unmark Complete")
        else:
            self.btnMarkComplete.setText("✓ Mark Complete")
        self.groups.setVisible(True)  # Show swatch bar in detail view
        self.stack.setCurrentIndex(1)
        # sync current states
        self.detail.set_active_group(self.groups.active())
        self.detail.set_eraser(self.groups.eraser())

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
            if self._current_idx in self._completed:
                self._completed.remove(self._current_idx)
                self.btnMarkComplete.setText("✓ Mark Complete")
            else:
                self._completed.add(self._current_idx)
                self.btnMarkComplete.setText("Unmark Complete")
                self.tileCompleted.emit(self._current_idx)
            self.grid.set_completed(self._completed)
            self._show_grid()

    def _show_grid(self):
        self.stack.setCurrentIndex(0)
        self.btnBack.setVisible(False)
        self.btnMarkComplete.setVisible(False)
        self.groups.setVisible(False)  # Hide swatch bar in grid view

    def _on_group_changed(self, gid: int):
        if self.groups.eraser():      # if bar forced eraser off, this will be False; otherwise ensure
            self.groups.set_eraser(False)
        self.detail.set_active_group(gid)

    def _on_grid_toggle_complete(self, idx: int):
        # Toggle in the browser's source-of-truth set, then push to grid
        if idx in self._completed:
            self._completed.remove(idx)
        else:
            self._completed.add(idx)
        self.grid.set_completed(self._completed)
        # If currently viewing this tile in detail, update button label
        if self._current_idx == idx and self.btnMarkComplete.isVisible():
            self.btnMarkComplete.setText("Unmark Complete" if idx in self._completed else "✓ Mark Complete")

    # ---- hotkeys 0..9 to toggle active group or 'e' to toggle eraser ----
    def keyPressEvent(self, e: QtGui.QKeyEvent):
        key = e.key()
        if QtCore.Qt.Key.Key_0 <= key <= QtCore.Qt.Key.Key_9:
            gid = key - QtCore.Qt.Key.Key_0
            self.groups.set_eraser(False)  # numbers always paint
            self.groups.set_active(-1 if self.groups.active() == gid else gid)
            e.accept(); return
        if key == QtCore.Qt.Key.Key_E:
            self.groups.set_eraser(not self.groups.eraser())
            e.accept(); return
        super().keyPressEvent(e)
