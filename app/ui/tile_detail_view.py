import numpy as np
from PyQt6 import QtWidgets, QtGui, QtCore
from group_bar import GROUP_COLORS
import os
import cv2
from utils import np_to_qpixmap

basedir = os.path.abspath(os.path.dirname(__file__))

MAX_HISTORY = 50

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
        self._sc_undo = QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Z'), self)
        self._sc_undo.activated.connect(self.undo)
        self._sc_redo = QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Y'), self)
        self._sc_redo.activated.connect(self.redo)

    # ---- public API ----
    def set_eraser(self, active: bool):
        self._eraser = bool(active)
        # Show brush cursor if eraser or a group is active
        self._cursor_item.setVisible(self._eraser or self._active_group != -1)
        # Update cursor ring color (eraser takes precedence)
        self._refresh_cursor_pen()

    # --- tweak existing set_active_group to play nice with eraser ---
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
            color = QtGui.QColor(255, 170, 0, 240)  # orange for eraser
        elif self._active_group != -1:
            # color of the active group
            hexc = GROUP_COLORS.get(self._active_group, "#FFFFFF")
            color = QtGui.QColor(hexc)
            color.setAlpha(240)
        else:
            color = QtGui.QColor(255, 255, 255, 220)  # default white

        pen = QtGui.QPen(color)
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
        # Pixels that will actually change with this dab
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
        
        # Store original RGB pixmap and reset display state
        self._pix_rgb = pix
        self._pix = pix
        self._pix_hsv_value = None  # Clear cached HSV
        self._show_h = False  # Always start with RGB view
        self._show_s = False  # Always start with RGB view
        self._show_v = False  # Always start with RGB view
        self._base_item = scene.addPixmap(pix)
        # self._base_item.setZValue(0)

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
        # Reset history for new base pixmap
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._stroke_record = None

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

    def _pixmap_to_hsv_value(self, pixmap: QtGui.QPixmap, channel: str) -> QtGui.QPixmap:
        """Convert a QPixmap to HSV and extract the specified channel as grayscale."""
        assert channel in ('value', 'hue', 'saturation')

        # Convert QPixmap to QImage in RGB888 format
        qimg = pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_RGB888)
        
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
            # Begin new stroke record and clear redo chain
            self._stroke_record = {}
            self._redo_stack.clear()
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
            # clear current stroke record
            self._stroke_record = None
            e.accept()
            return
        
        # Right-click release to stop panning
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            e.accept()
            return
        
        super().mouseReleaseEvent(e)


    def keyPressEvent(self, e: QtGui.QKeyEvent):
        # Undo/Redo shortcuts (in addition to explicit QShortcuts)
        if e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            if e.key() == QtCore.Qt.Key.Key_Z:
                self.undo(); e.accept(); return
            if e.key() == QtCore.Qt.Key.Key_Y:
                self.redo(); e.accept(); return
        # Toggle HSV Value display with 'V' key
        if e.key() == QtCore.Qt.Key.Key_V:
            self.toggle_hsv_display("value")
            e.accept(); return
        # Toggle HSV Hue display with 'H' key
        if e.key() == QtCore.Qt.Key.Key_H:
            self.toggle_hsv_display("hue")
            e.accept(); return
        # Toggle HSV Saturation display with 'S' key
        if e.key() == QtCore.Qt.Key.Key_S:
            self.toggle_hsv_display("saturation")
            e.accept(); return
        # Clear mask with 'C' key
        if e.key() == QtCore.Qt.Key.Key_C:
            self.set_mask(None)
            e.accept(); return
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
        # If Ctrl is held, use wheel to change brush size instead of zooming
        try:
            modifiers = event.modifiers()
        except Exception:
            modifiers = QtCore.Qt.KeyboardModifier.NoModifier

        if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
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