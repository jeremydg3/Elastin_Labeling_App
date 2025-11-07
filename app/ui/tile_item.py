from PyQt6 import QtWidgets, QtGui, QtCore
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class TileItem(QtWidgets.QGraphicsObject):
    tileClicked = QtCore.pyqtSignal(int)
    contextRequested = QtCore.pyqtSignal(int, QtCore.QPoint)  # (index, global point)
    _badge_icon: QtGui.QPixmap | None = None  # lazy-loaded checkmark icon

    @staticmethod
    def _load_badge_icon() -> QtGui.QPixmap | None:
        if TileItem._badge_icon is not None:
            return TileItem._badge_icon
        try:
            # icon_path = Path(__file__).resolve().parent.parent / "assets" / "complete_icon.png"
            icon_path = os.path.join(basedir, "assets", "complete_icon.png")
            pm = QtGui.QPixmap(icon_path)
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