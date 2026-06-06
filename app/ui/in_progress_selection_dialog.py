"""
In-progress image selection dialog.

Shows locally cached in-progress images with preview, filename,
and completion/working percentages.
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class StackedProgressBar(QWidget):
    """Simple stacked bar for complete/working/remaining percentages."""

    def __init__(self, complete_pct: float, working_pct: float, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.complete_pct = max(0.0, min(100.0, float(complete_pct)))
        self.working_pct = max(0.0, min(100.0, float(working_pct)))
        if self.complete_pct + self.working_pct > 100.0:
            self.working_pct = max(0.0, 100.0 - self.complete_pct)
        self.setMinimumHeight(26)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect().adjusted(0, 0, -1, -1)
        width = max(1, rect.width())

        complete_w = int(round(width * (self.complete_pct / 100.0)))
        working_w = int(round(width * (self.working_pct / 100.0)))
        remaining_w = max(0, width - complete_w - working_w)

        x = rect.x()

        painter.fillRect(x, rect.y(), complete_w, rect.height(), QColor("#06b253"))
        x += complete_w
        painter.fillRect(x, rect.y(), working_w, rect.height(), QColor("#e87433"))
        x += working_w
        painter.fillRect(x, rect.y(), remaining_w, rect.height(), QColor("#b9b9b9"))

        border_pen = QPen(QColor("#0c3142"))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.drawRect(rect)


class InProgressRowWidget(QFrame):
    """Single selectable row in the in-progress selection dialog."""

    selected = pyqtSignal(dict)

    def __init__(self, item: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(14)

        thumb_label = QLabel()
        thumb_label.setFixedSize(180, 180)
        thumb_label.setStyleSheet("QLabel { background-color: #c7c7c7; border: none; }")

        pix: Optional[QPixmap] = item.get("preview")
        if pix and not pix.isNull():
            scaled = pix.scaled(
                thumb_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            thumb_label.setPixmap(scaled)
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            thumb_label.setText("No preview")
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setStyleSheet(
                "QLabel { background-color: #6b6b6b; color: #e0e0e0; border: none; font-size: 11pt; }"
            )

        right = QVBoxLayout()
        right.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)

        title = QLabel(item.get("file_name", "(unnamed)"))
        title.setStyleSheet("QLabel { font-size: 24px; font-weight: 700; color: #ececec; }")

        tiles = QLabel(f"{item.get('total_tiles', 0)} tiles")
        tiles.setStyleSheet("QLabel { font-size: 22px; color: #ececec; }")

        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(tiles)

        complete_pct = item.get("complete_pct", 0)
        working_pct = item.get("working_pct", 0)
        complete_count = item.get("complete_count", 0)
        working_count = item.get("working_count", 0)

        bar = StackedProgressBar(complete_pct, working_pct)
        bar.setMinimumWidth(560)
        bar.setMaximumHeight(38)

        lbl_complete = QLabel(f"{complete_pct}% complete ({complete_count})")
        lbl_complete.setStyleSheet("QLabel { color: #06d778; font-size: 20px; }")

        lbl_working = QLabel(f"{working_pct}% working ({working_count})")
        lbl_working.setStyleSheet("QLabel { color: #ff8a3d; font-size: 20px; }")

        right.addLayout(top)
        right.addWidget(bar)
        right.addWidget(lbl_complete)
        right.addWidget(lbl_working)
        right.addStretch(1)

        root.addWidget(thumb_label)
        root.addLayout(right, 1)

        # Treat the whole row as one interactive target so hover/click
        # highlighting applies uniformly instead of per-child widgets.
        self._make_children_mouse_transparent()

    def _make_children_mouse_transparent(self):
        for child in self.findChildren(QWidget):
            if child is self:
                continue
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _set_hovered(self, hovered: bool):
        if self._hovered != hovered:
            self._hovered = hovered
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._hovered:
            painter.fillRect(rect, QColor(255, 255, 255, 22))
            pen = QPen(QColor("#4d9eff"))
            pen.setWidth(1)
        else:
            pen = QPen(QColor(0, 0, 0, 0))
            pen.setWidth(1)

        painter.setPen(pen)
        painter.drawRoundedRect(rect, 6, 6)
        super().paintEvent(event)

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.item)
        super().mousePressEvent(event)


class InProgressSelectionDialog(QDialog):
    """Scrollable dialog to select one local in-progress image to resume."""

    def __init__(self, items: List[Dict[str, Any]], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._selected_item: Optional[Dict[str, Any]] = None
        self.setWindowTitle("Resume Progress")
        self.setModal(True)
        self.resize(980, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel("Select a locally cached in-progress image to continue:")
        header.setStyleSheet("QLabel { font-size: 12pt; font-weight: 600; color: #e6e6e6; }")
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        for idx, item in enumerate(items):
            row = InProgressRowWidget(item)
            row.selected.connect(self._on_selected)
            content_layout.addWidget(row)

            if idx < len(items) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("QFrame { color: #111111; background-color: #111111; min-height: 2px; max-height: 2px; }")
                content_layout.addWidget(sep)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)
        root.addLayout(bottom)

    def _on_selected(self, item: Dict[str, Any]):
        self._selected_item = item
        self.accept()

    def selected_item(self) -> Optional[Dict[str, Any]]:
        return self._selected_item


def show_in_progress_selection_dialog(
    items: List[Dict[str, Any]], parent: Optional[QWidget] = None
) -> Optional[Dict[str, Any]]:
    """Show in-progress selection dialog and return selected item or None."""
    dlg = InProgressSelectionDialog(items, parent)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.selected_item()
    return None
