from PyQt6.QtGui import QColor, QPixmap, QPainter, QPen
from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QPointF, QRectF
from PyQt6.QtWidgets import QGraphicsObject, QGraphicsSceneHoverEvent, QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem

import os

basedir = os.path.abspath(os.path.dirname(__file__))

class TileItem(QGraphicsObject):
    tileClicked = pyqtSignal(int)
    contextRequested = pyqtSignal(int, QPoint)  # (index, global point)
    _badge_icon: QPixmap | None = None  # lazy-loaded checkmark icon

    @staticmethod
    def _load_badge_icon() -> QPixmap | None:
        if TileItem._badge_icon is not None:
            return TileItem._badge_icon
        try:
            # icon_path = Path(__file__).resolve().parent.parent / "assets" / "complete_icon.png"
            icon_path = os.path.join(basedir, "assets", "complete_icon.png")
            pm = QPixmap(icon_path)
            if not pm.isNull():
                TileItem._badge_icon = pm
                return pm
        except Exception:
            pass
        TileItem._badge_icon = None
        return None

    def __init__(self, index: int, pix: QPixmap, tile_size: int, enabled: bool, completed: bool = False):
        super().__init__()
        self.index = index
        self.pix = pix
        self.tile_size = tile_size
        self.enabled_flag = enabled
        self.completed = completed
        self._hover = False

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    # --- QGraphicsObject requirements ---
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.tile_size, self.tile_size)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # draw the tile pixmap scaled to the box
        painter.drawPixmap(0, 0, self.tile_size, self.tile_size, self.pix)

        # subtle outline (darker for dark theme)
        painter.setPen(QPen(QColor(70, 70, 70)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(1, 1, self.tile_size - 1, self.tile_size - 1)

        # hover highlight (enabled tiles only) - accent blue
        if self._hover and self.enabled_flag:
            pen = QPen(QColor(77, 158, 255))  # Accent primary from dark theme
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(2, 2, self.tile_size - 2, self.tile_size - 2)

        # dim overlay for disabled/partial tiles (darker for dark theme)
        if not self.enabled_flag:
            painter.fillRect(self.boundingRect(), QColor(30, 30, 30, 140))

        # completed overlay (semi-transparent green) + small badge in top-right
        if self.completed:
            painter.fillRect(self.boundingRect(), QColor(76, 175, 80, 110))

            # draw badge
            margin = max(3, self.tile_size // 40)
            badge = max(14, min(24, self.tile_size // 10))
            x = self.tile_size - margin - badge
            y = margin

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # background circle for contrast
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.drawEllipse(x, y, badge, badge)

            icon = TileItem._load_badge_icon()
            if icon is not None:
                painter.drawPixmap(x, y, badge, badge, icon)
            else:
                # Fallback: draw a green checkmark
                pen = QPen(QColor(76, 175, 80))
                pen.setWidth(max(2, badge // 8))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                # simple check path
                x0 = x + badge * 0.25
                y0 = y + badge * 0.55
                x1 = x + badge * 0.45
                y1 = y + badge * 0.75
                x2 = x + badge * 0.78
                y2 = y + badge * 0.30
                painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.restore()

    def set_completed(self, done: bool):
        if self.completed != done:
            self.completed = done
            self.update()

    # --- events ---
    def hoverEnterEvent(self, e: QGraphicsSceneHoverEvent):
        if self.enabled_flag:
            self._hover = True
            self.update()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e: QGraphicsSceneHoverEvent):
        if self._hover:
            self._hover = False
            self.update()
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e: QGraphicsSceneMouseEvent):
        if e.button() == Qt.MouseButton.RightButton:
            # request context menu at screen position
            gp = e.screenPos()
            self.contextRequested.emit(self.index, gp)
            e.accept()
            return
        if self.enabled_flag and e.button() == Qt.MouseButton.LeftButton:
            self.tileClicked.emit(self.index)
        # swallow clicks when disabled
        super().mousePressEvent(e)
