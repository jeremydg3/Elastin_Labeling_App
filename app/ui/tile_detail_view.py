import numpy as np


from PyQt6.QtGui import (QPixmap, QKeyEvent, QPainter, QColor, 
                         QBrush, QPen, QShortcut, QKeySequence, 
                         QImage, QMouseEvent, QHoverEvent, QWheelEvent)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem

from group_bar import GROUP_COLORS
import os
import cv2
from utils import np_to_qpixmap

basedir = os.path.abspath(os.path.dirname(__file__))

MAX_HISTORY = 50
MIN_ALPHA = 80
MAX_ALPHA = 160

class TileDetailView(QGraphicsView):
    """
    Shows one tile pixmap + a paintable overlay mask.
    - Mask is uint8 (0..9 = group id, 255 = empty)
    - Brush paints circle into mask, which is composited to a top overlay pixmap
    """
    maskChanged = pyqtSignal()  # emitted on paint edits
    firstPaintStroke = pyqtSignal()  # emitted on first paint stroke (for auto-marking as working)

    def __init__(self, brush_radius: int = 10, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._base_item = None
        self._overlay_item = None
        self._cursor_item = QGraphicsEllipseItem()
        self._cursor_item.setZValue(99)
        pen = QPen(QColor(255, 255, 255, 220))  # default brush outline
        pen.setWidth(10)
        self._cursor_item.setPen(pen)
        self._cursor_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._cursor_item.setVisible(False)
        self._eraser = False
        
        # Ensure scene exists before adding items
        scene = self.scene()
        if scene is None:
            scene = QGraphicsScene(self)
            self.setScene(scene)
            scene.addItem(self._cursor_item)

        self._pix = None
        self._pix_rgb = None   # Store original RGB pixmap
        self._pix_hsv_value = None  # Cache HSV value channel pixmap
        self._show_v = False  # Toggle state for RGB vs HSV Value display
        self._show_h = False  # Toggle state for RGB vs HSV Hue display
        self._show_s = False  # Toggle state for RGB vs HSV Saturation display
        self._mask = None  # uint8 HxW (0..9, 255 empty)
        self._overlay_pm = None
        self._brush_radius = brush_radius
        self._active_group = -1
        self._painting = False
        # Undo/redo state (only for paint/erase actions)
        self._undo_stack = []              # list of change dicts
        self._redo_stack = []              # list of change dicts
        self._stroke_record = None         # dict: lin_idx -> [old, new]
        self._max_history = MAX_HISTORY

        # Shortcuts: Ctrl+Z (undo), Ctrl+Y (redo)
        self._sc_undo = QShortcut(QKeySequence('Ctrl+Z'), self)
        self._sc_undo.activated.connect(self.undo)
        self._sc_redo = QShortcut(QKeySequence('Ctrl+Y'), self)
        self._sc_redo.activated.connect(self.redo)

        # Pulsing animation for mask overlay
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_overlay)
        self._pulse_phase = 0.0  # Current phase in the pulse cycle (0.0 to 1.0)
        self._base_alpha = 110   # Base alpha value for overlay

        # Surrounding tiles for context (8 neighbors in 3x3 grid)
        self._surrounding_items = []  # List of (base_item, overlay_item) for 8 neighbors
        self._tile_width = 0
        self._tile_height = 0


    # ---- public API ----
    def set_eraser(self, active: bool):
        self._eraser = bool(active)
        # Show brush cursor if eraser or a group is active
        self._cursor_item.setVisible(self._eraser or self._active_group != -1)
        # Update cursor ring color (eraser takes precedence)
        self._refresh_cursor_pen()


    def set_active_group(self, gid: int):
        """-1 to deactivate."""
        self._active_group = gid
        # cursor visible if eraser or group active
        self._cursor_item.setVisible(self._eraser or gid != -1)
        # Update cursor color to match active group when not erasing
        self._refresh_cursor_pen()


    def _refresh_cursor_pen(self):
        """Set cursor ring color based on eraser/group state."""
        if self._eraser:
            color = QColor(255, 170, 0, 240)  # orange for eraser
        elif self._active_group != -1:
            # color of the active group
            hexc = GROUP_COLORS.get(self._active_group, "#FFFFFF")
            color = QColor(hexc)
            color.setAlpha(240)
        else:
            color = QColor(255, 255, 255, 220)  # default white

        pen = QPen(color)
        pen.setWidth(1)
        self._cursor_item.setPen(pen)


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

        # Determine target value and track changed pixels for undo/redo
        target_val: np.uint8 = np.uint8(255) if self._eraser else np.uint8(self._active_group)
        # Check shape match (ensure painting within image bounds)
        if sub.shape != circle.shape:
            # safety check
            return
        change_mask = circle & (sub != target_val)
    
        # Record old/new values for this stroke (only once per pixel)
        if self._painting and self._stroke_record is not None and np.any(change_mask):
            cy, cx = np.where(change_mask)
            ys = (ymin + cy).astype(np.int64)
            xs = (xmin + cx).astype(np.int64)
            old_vals = sub[cy, cx].astype(np.uint8)
            w_full = self._mask.shape[1]
            lin = (ys * w_full + xs).astype(np.int64)
            # Store first-seen old value; always update final new value
            for i in range(lin.size):
                key = int(lin[i])
                prev = self._stroke_record.get(key)
                if prev is None:
                    # [old, new]
                    self._stroke_record[key] = [int(old_vals[i]), int(target_val)]
                else:
                    prev[1] = int(target_val)

        # Apply paint/erase to the subregion
        sub[change_mask] = target_val

        self._mask[ymin:ymax+1, xmin:xmax+1] = sub          # <-- write back
        self._rebuild_overlay()
        self.maskChanged.emit()


    def set_base_pixmap(self, pix: QPixmap):
        scene = self.scene()
        if scene is not None:
            # Remove cursor from scene before clearing to prevent deletion
            if self._cursor_item.scene() is not None:
                scene.removeItem(self._cursor_item)
            scene.clear()
        else:
            scene = QGraphicsScene(self)
            self.setScene(scene)
        
        # Store tile dimensions
        self._tile_width = pix.width()
        self._tile_height = pix.height()
        
        # Store original RGB pixmap and reset display state
        self._pix_rgb = pix
        self._pix = pix
        self._pix_hsv_value = None  # Clear cached HSV
        self._show_h = False  # Always start with RGB view
        self._show_s = False  # Always start with RGB view
        self._show_v = False  # Always start with RGB view
        # Position center tile at (tile_width, tile_height) to leave room for neighbors
        self._base_item = scene.addPixmap(pix)
        if self._base_item is not None:
            self._base_item.setPos(self._tile_width, self._tile_height)

        # overlay
        self._overlay_pm = QPixmap(pix.size())
        self._overlay_pm.fill(Qt.GlobalColor.transparent)
        self._overlay_item = scene.addPixmap(self._overlay_pm)
        if self._overlay_item is not None:
            self._overlay_item.setZValue(10)
            self._overlay_item.setPos(self._tile_width, self._tile_height)

        # cursor back on top
        scene.addItem(self._cursor_item)

        # Clear any previous surrounding tiles
        self._surrounding_items.clear()

        if self._base_item is not None:
            # Scene rect encompasses all 9 tiles (3x3 grid)
            scene.setSceneRect(0, 0, self._tile_width * 3, self._tile_height * 3)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

        # Reset history for new base pixmap
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._stroke_record = None


    def set_surrounding_tiles(self, neighbors: list[tuple[QPixmap | None, np.ndarray | None]]):
        """
        Set the 8 surrounding tiles for context visualization.
        neighbors: list of 8 tuples (pixmap, mask) in order: [top-left, top, top-right, left, right, bottom-left, bottom, bottom-right]
        None entries mean no neighbor exists (edge of grid)
        """
        scene = self.scene()
        if scene is None or len(neighbors) != 8:
            return
        
        # Clear previous surrounding items
        for base_item, overlay_item in self._surrounding_items:
            if base_item is not None:
                scene.removeItem(base_item)
            if overlay_item is not None:
                scene.removeItem(overlay_item)
        self._surrounding_items.clear()
        
        # Positions for 8 neighbors: [TL, T, TR, L, R, BL, B, BR]
        positions = [
            (0, 0),                                    # top-left
            (self._tile_width, 0),                     # top
            (self._tile_width * 2, 0),                 # top-right
            (0, self._tile_height),                    # left
            (self._tile_width * 2, self._tile_height), # right
            (0, self._tile_height * 2),                # bottom-left
            (self._tile_width, self._tile_height * 2), # bottom
            (self._tile_width * 2, self._tile_height * 2) # bottom-right
        ]
        
        for i, (pix, mask) in enumerate(neighbors):
            if pix is None:
                self._surrounding_items.append((None, None))
                continue
            
            # Create dimmed/greyed version of the tile
            dimmed_pix = self._create_dimmed_pixmap(pix)
            base_item = scene.addPixmap(dimmed_pix)
            if base_item is not None:
                base_item.setPos(*positions[i])
                base_item.setZValue(-2)  # Behind center tile
                base_item.setOpacity(0.5)  # Additional dimming
            
            # Create overlay for the mask if it exists
            overlay_item = None
            if mask is not None:
                overlay_pix = self._create_overlay_pixmap(mask, pix.width(), pix.height(), dim=True)
                overlay_item = scene.addPixmap(overlay_pix)
                if overlay_item is not None:
                    overlay_item.setPos(*positions[i])
                    overlay_item.setZValue(-1)  # Behind center tile but above neighbor base
                    overlay_item.setOpacity(0.4)  # Dimmed overlay
            
            self._surrounding_items.append((base_item, overlay_item))
    
    
    def _create_dimmed_pixmap(self, pix: QPixmap) -> QPixmap:
        """Create a greyed-out/dimmed version of a pixmap."""
        img = pix.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                color = img.pixelColor(x, y)
                # Convert to grayscale and reduce brightness
                gray = int(0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue())
                dimmed = int(gray * 0.6)  # Reduce brightness
                img.setPixelColor(x, y, QColor(dimmed, dimmed, dimmed, color.alpha()))
        return QPixmap.fromImage(img)
    
    
    def _create_overlay_pixmap(self, mask: np.ndarray, width: int, height: int, dim: bool = False) -> QPixmap:
        """Create an overlay pixmap from a mask array."""
        overlay = np.zeros((height, width, 4), dtype=np.uint8)
        alpha = 60 if dim else 110  # Dimmed alpha for surrounding tiles
        
        for gid, hexc in GROUP_COLORS.items():
            sel = (mask == gid)
            if not np.any(sel):
                continue
            c = QColor(hexc)
            overlay[sel, 0] = c.red()
            overlay[sel, 1] = c.green()
            overlay[sel, 2] = c.blue()
            overlay[sel, 3] = alpha
        
        qimg = QImage(overlay.data, width, height, 4 * width, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())  # Copy to avoid data lifetime issues


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
        # Reset history when mask is set/switched
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._stroke_record = None


    def get_mask(self):
        return None if self._mask is None else self._mask.copy()


    def _pixmap_to_hsv_value(self, pixmap: QPixmap, channel: str) -> QPixmap:
        """Convert a QPixmap to HSV and extract the specified channel as grayscale."""
        assert channel in ('value', 'hue', 'saturation')

        # Convert QPixmap to QImage in RGB888 format
        qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        
        # Convert to numpy array
        width = qimg.width()
        height = qimg.height()
        bytes_per_line = qimg.bytesPerLine()
        ptr = qimg.constBits()
        
        # Create numpy array from image data
        try:
            arr = np.array(ptr, copy=True).reshape((height, bytes_per_line))
        except Exception as e:
            # Fallback method if direct array conversion fails
            if ptr is not None:
                try:
                    data_string = ptr.asstring(qimg.sizeInBytes())
                    arr = np.frombuffer(data_string,dtype=np.uint8).reshape((height,bytes_per_line))
                except Exception as e2:
                    # raise RuntimeError("Failed to convert QPixmap to numpy array") from e2
                    return pixmap  # Fallback: return original pixmap
            else:
                return pixmap  # Fallback: return original pixmap
        
        # Extract only the RGB data (3 bytes per pixel)
        rgb = arr[:, :width*3].reshape((height, width, 3)).copy()
        
        # Convert RGB to HSV using OpenCV
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        
        # Extract Value channel
        if channel == 'hue':
            value = hsv[:, :, 0]
        elif channel == 'saturation':
            value = hsv[:, :, 1]
        else:  # channel == 'value'
            value = hsv[:, :, 2]

        # Convert to RGB grayscale (all channels same)
        viridis_rgb = self.viridis_colormap(value)
        
        # Convert back to QPixmap
        return np_to_qpixmap(viridis_rgb)


    @staticmethod
    def viridis_colormap(grey: np.ndarray) -> np.ndarray:
        # Apply viridis colormap to the channel
        # Normalize to 0-1 range first
        normalized = grey.astype(np.float32) / 255.0
        
        # Apply viridis colormap (matplotlib-style)
        # Viridis color points: dark purple -> blue -> green -> yellow
        viridis_colors = np.array([
            [0.267004, 0.004874, 0.329415],  # dark purple
            [0.253935, 0.265254, 0.529983],  # blue
            [0.163625, 0.471133, 0.558148],  # teal
            [0.134692, 0.658636, 0.517649],  # green
            [0.477504, 0.821444, 0.318465],  # light green
            [0.993248, 0.906157, 0.143936]   # yellow
        ])
        
        # Interpolate colors based on normalized values
        n_colors = len(viridis_colors)
        indices = normalized * (n_colors - 1)
        indices_int = np.floor(indices).astype(np.int32)
        indices_frac = indices - indices_int
        indices_int = np.clip(indices_int, 0, n_colors - 2)
        
        # Linear interpolation between adjacent colors
        color1 = viridis_colors[indices_int]
        color2 = viridis_colors[indices_int + 1]
        interpolated = color1 + indices_frac[..., np.newaxis] * (color2 - color1)
        
        # Convert to uint8 RGB
        viridis_rgb = (interpolated * 255).astype(np.uint8)
        return viridis_rgb


    def toggle_hsv_display(self, channel: str):
        """Toggle between RGB and HSV Value channel display."""
        assert channel in ('value', 'hue', 'saturation')

        if self._pix_rgb is None or self._base_item is None:
            return
        
        if channel == 'value':
            self._show_v = not self._show_v
            self._show_h = False
            self._show_s = False
        elif channel == 'hue':
            self._show_h = not self._show_h
            self._show_v = False
            self._show_s = False
        elif channel == 'saturation':
            self._show_s = not self._show_s
            self._show_h = False
            self._show_v = False
        else:
            return  # invalid channel
        
        if self._show_v or self._show_h or self._show_s:
            if self._show_v:
                # Switch to HSV Value display
                self._pix_hsv_value = self._pixmap_to_hsv_value(self._pix_rgb, 'value')
            elif self._show_h:
                # Switch to HSV Hue display
                self._pix_hsv_value = self._pixmap_to_hsv_value(self._pix_rgb, 'hue')
            else:  # self._show_s:
                # Switch to HSV Saturation display
                self._pix_hsv_value = self._pixmap_to_hsv_value(self._pix_rgb, 'saturation')
            self._base_item.setPixmap(self._pix_hsv_value)
        else:
            # Switch back to RGB
            self._pix_hsv_value = None
            self._base_item.setPixmap(self._pix_rgb)


    # ---- overlay composition ----
    def _rebuild_overlay(self, alpha: int | None = None):
        """Rebuild overlay pixmap from mask array (fast path)."""
        if self._mask is None or self._pix is None or self._overlay_item is None:
            return
        h, w = self._mask.shape
        # RGBA overlay
        overlay = np.zeros((h, w, 4), dtype=np.uint8)
        # draw each group color with alpha
        if alpha is None:
            # Calculate alpha from current pulse phase
            alpha_range = MAX_ALPHA - MIN_ALPHA
            alpha = int(MIN_ALPHA + alpha_range * (0.5 + 0.5 * np.sin(2 * np.pi * self._pulse_phase)))
        for gid, hexc in GROUP_COLORS.items():
            sel = (self._mask == gid)
            if not np.any(sel):
                continue
            c = QColor(hexc)
            overlay[sel, 0] = c.red()
            overlay[sel, 1] = c.green()
            overlay[sel, 2] = c.blue()
            overlay[sel, 3] = alpha
        # convert to QImage -> QPixmap
        qimg = QImage(overlay.data, w, h, 4*w, QImage.Format.Format_RGBA8888)
        self._overlay_pm = QPixmap.fromImage(qimg)
        self._overlay_item.setPixmap(self._overlay_pm)


    def _pulse_overlay(self):
        """Update overlay opacity in a pulsing pattern (fade in/out ~1 time per second)."""
        # Increment phase (0.0 to 1.0 over 1 second)
        self._pulse_phase += 0.05  # 50ms * 0.05 = 1 second per cycle
        if self._pulse_phase >= 1.0:
            self._pulse_phase = 0.0
        
        # Calculate alpha using a sine wave for smooth pulsing
        # sin goes from -1 to 1, we map to alpha range (e.g., 60 to 160)
        alpha_range = MAX_ALPHA - MIN_ALPHA
        alpha = int(MIN_ALPHA + alpha_range * (0.5 + 0.5 * np.sin(2 * np.pi * self._pulse_phase)))
        
        # Rebuild overlay with current alpha
        self._rebuild_overlay(alpha=alpha)


    # ---- painting ----
    def _img_pos_from_view(self, ev: QMouseEvent | QHoverEvent):
        sp = self.mapToScene(ev.position().toPoint())
        # Adjust for center tile offset
        return sp.x() - self._tile_width, sp.y() - self._tile_height


    # ---- events ----
    def mousePressEvent(self, e: QMouseEvent):
        # Left-click starts a paint stroke if a tool is active
        if e.button() == Qt.MouseButton.LeftButton and (self._eraser or self._active_group != -1):
            # ensure we receive keyboard events (0–9, E, +/-)
            self.setFocus()

            # where in the image (scene) did we click?
            x, y = self._img_pos_from_view(e)

            # show/update brush cursor at press location (in scene coordinates)
            r = int(self._brush_radius)
            self._cursor_item.setRect(x + self._tile_width - r, y + self._tile_height - r, 2*r, 2*r)
            self._cursor_item.setVisible(True)

            # begin stroke + lay down initial dab
            self._painting = True
            # Stop pulsing animation while painting
            self._pulse_timer.stop()
            # Begin new stroke record and clear redo chain
            self._stroke_record = {}
            self._redo_stack.clear()
            # Emit firstPaintStroke for auto-marking as working
            self.firstPaintStroke.emit()
            self._paint_at(x, y)   # uses cv2.circle(...) inside
            e.accept()
            return

        # Right-click to pan
        if e.button() == Qt.MouseButton.RightButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # Create a fake left-click event to start panning
            fake_event = QMouseEvent(
                e.type(), e.position(), e.globalPosition(),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                e.modifiers()
            )
            super().mousePressEvent(fake_event)
            e.accept()
            return

        # otherwise, pass to default handler (e.g., for selection, focus, etc.)
        super().mousePressEvent(e)


    def mouseMoveEvent(self, e: QMouseEvent):
        # move brush cursor (in scene coordinates)
        x, y = self._img_pos_from_view(e)
        r = self._brush_radius
        self._cursor_item.setRect(x + self._tile_width - r, y + self._tile_height - r, 2*r, 2*r)

        if self._painting and (self._eraser or self._active_group != -1):
            self._paint_at(x, y)
            e.accept()
            return
        super().mouseMoveEvent(e)


    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton and self._painting:
            self._painting = False
            # Finalize stroke: push to undo stack if any changes
            if self._stroke_record is not None and len(self._stroke_record) > 0:
                w_full = self._mask.shape[1] if self._mask is not None else 0
                keys = list(self._stroke_record.keys())
                ys = np.array([k // w_full for k in keys], dtype=np.int32)
                xs = np.array([k % w_full for k in keys], dtype=np.int32)
                olds = np.array([self._stroke_record[k][0] for k in keys], dtype=np.uint8)
                news = np.array([self._stroke_record[k][1] for k in keys], dtype=np.uint8)
                change = {"ys": ys, "xs": xs, "old": olds, "new": news}
                self._undo_stack.append(change)
                # cap history
                if len(self._undo_stack) > self._max_history:
                    self._undo_stack.pop(0)
                # Start pulsing animation after completing paint stroke
                # self._pulse_phase = 0.0
                self._pulse_timer.start(50)  # Update every 50ms (~20 FPS)
            # clear current stroke record
            self._stroke_record = None
            e.accept()
            return
        
        # Right-click release to stop panning
        if e.button() == Qt.MouseButton.RightButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            e.accept()
            return
        
        super().mouseReleaseEvent(e)


    def keyPressEvent(self, e: QKeyEvent):
        # Undo/Redo shortcuts (in addition to explicit QShortcuts)
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_Z:
                self.undo(); e.accept(); return
            if e.key() == Qt.Key.Key_Y:
                self.redo(); e.accept(); return
        # Toggle HSV Value display with 'V' key
        if e.key() == Qt.Key.Key_V:
            self.toggle_hsv_display("value")
            e.accept(); return
        # Toggle HSV Hue display with 'H' key
        if e.key() == Qt.Key.Key_H:
            self.toggle_hsv_display("hue")
            e.accept(); return
        # Toggle HSV Saturation display with 'S' key
        if e.key() == Qt.Key.Key_S:
            self.toggle_hsv_display("saturation")
            e.accept(); return
        # Clear mask with 'C' key
        if e.key() == Qt.Key.Key_C:
            self.set_mask(None)
            e.accept(); return
        if e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._brush_radius = min(128, self._brush_radius + 1)
            # Update cursor size immediately
            if self._cursor_item.isVisible():
                x, y = self._cursor_item.rect().center().x(), self._cursor_item.rect().center().y()
                r = self._brush_radius
                self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)
                e.accept(); return
        if e.key() == Qt.Key.Key_Minus:
            self._brush_radius = max(1, self._brush_radius - 1)
            # Update cursor size immediately
            if self._cursor_item.isVisible():
                x, y = self._cursor_item.rect().center().x(), self._cursor_item.rect().center().y()
                r = self._brush_radius
                self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)
                e.accept(); return
        super().keyPressEvent(e)


    def wheelEvent(self, event: QWheelEvent):
        # If Ctrl is held, use wheel to change brush size instead of zooming
        try:
            modifiers = event.modifiers()
        except Exception:
            modifiers = Qt.KeyboardModifier.NoModifier

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if self._eraser or self._active_group >= 0:
                # angleDelta().y() is positive for wheel-up, negative for wheel-down
                delta = event.angleDelta().y()
                if delta == 0:
                    event.ignore()
                    return
                # Prefer whole-notch steps if available (120 units per notch typical)
                steps = int(delta / 120)
                sign = 1 if delta > 0 else -1
                if steps == 0:
                    steps = sign

                # Adjust brush radius, clamp between 1 and 128
                self._brush_radius = max(1, min(128, int(self._brush_radius) + steps))

                # Update cursor size immediately if visible
                if self._cursor_item.isVisible():
                    rect = self._cursor_item.rect()
                    x, y = rect.center().x(), rect.center().y()
                    r = self._brush_radius
                    self._cursor_item.setRect(x - r, y - r, 2*r, 2*r)

                event.accept()
                return

        # Default: zoom view
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


    # ---- undo/redo API ----
    def undo(self):
        if self._painting:
            return  # don't undo mid-stroke
        if self._mask is None or len(self._undo_stack) == 0:
            return
        change = self._undo_stack.pop()
        ys = change["ys"]; xs = change["xs"]; old = change["old"]
        self._mask[ys, xs] = old
        self._rebuild_overlay()
        self.maskChanged.emit()
        # push to redo
        self._redo_stack.append(change)


    def redo(self):
        if self._painting:
            return  # don't redo mid-stroke
        if self._mask is None or len(self._redo_stack) == 0:
            return
        change = self._redo_stack.pop()
        ys = change["ys"]; xs = change["xs"]; newv = change["new"]
        self._mask[ys, xs] = newv
        self._rebuild_overlay()
        self.maskChanged.emit()
        # push back to undo
        self._undo_stack.append(change)
