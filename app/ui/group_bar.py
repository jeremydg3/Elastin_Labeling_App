# group_bar.py
from PyQt6 import QtWidgets, QtGui, QtCore

GROUP_COLORS = {
    0: "#167288", 1: "#8cdaec", 2: "#b45248", 3: "#d48c84", 4: "#a89a49",
    5: "#d6cfa2", 6: "#3cb464", 7: "#9bddb1", 8: "#643c6a", 9: "#836394",
}

class GroupChip(QtWidgets.QFrame):
    clicked = QtCore.pyqtSignal(int)
    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        self.setFixedHeight(28)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._active = False

        self.lblNum = QtWidgets.QLabel(str(gid))
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(28, 16)
        self._update_swatch()

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)
        lay.addWidget(self.lblNum)
        lay.addWidget(self.swatch)

        self.set_active(False)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self.gid)
        super().mousePressEvent(e)

    def _update_swatch(self, grey=False):
        c = QtGui.QColor(GROUP_COLORS[self.gid])
        if grey:
            c = QtGui.QColor(180, 180, 180)
        pm = QtGui.QPixmap(self.swatch.width(), self.swatch.height())
        pm.fill(c)
        self.swatch.setPixmap(pm)

    def set_active(self, yes: bool):
        self._active = yes
        if yes:
            self.setStyleSheet("QFrame { border: 2px solid #2b7; border-radius: 6px; }")
            self._update_swatch(grey=False)
        else:
            self.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 6px; }")

    def set_greyed(self, grey: bool):
        if not self._active:
            self._update_swatch(grey=grey)


class EraserChip(QtWidgets.QFrame):
    toggled = QtCore.pyqtSignal(bool)
    def __init__(self):
        super().__init__()
        self.setFixedHeight(28)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._active = False

        self.lbl = QtWidgets.QLabel("Eraser")
        self.badge = QtWidgets.QLabel()
        self.badge.setFixedSize(28, 16)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3); lay.setSpacing(6)
        lay.addWidget(self.lbl); lay.addWidget(self.badge)

        self.set_active(False)

    def _paint_badge(self, active: bool):
        # orange when active, grey when off
        c = QtGui.QColor(255, 170, 0) if active else QtGui.QColor(200, 200, 200)
        pm = QtGui.QPixmap(self.badge.width(), self.badge.height()); pm.fill(c)
        self.badge.setPixmap(pm)

    def set_active(self, yes: bool):
        self._active = yes
        self.setStyleSheet("QFrame { border: %dpx solid %s; border-radius: 6px; }" %
                           (2 if yes else 1, "#ffa500" if yes else "#ddd"))
        self._paint_badge(yes)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self.set_active(not self._active)
            self.toggled.emit(self._active)
        super().mousePressEvent(e)


class GroupBar(QtWidgets.QWidget):
    activeChanged = QtCore.pyqtSignal(int)   # emits -1 when none
    eraserChanged = QtCore.pyqtSignal(bool)    # True when eraser ON

    def __init__(self):
        super().__init__()
        self._active = -1
        self._chips = []
        self._eraser_on = False

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)

        for i in range(10):
            chip = GroupChip(i)
            chip.clicked.connect(self._chip_clicked)
            self._chips.append(chip)
            lay.addWidget(chip)

        self.eraser_chip = EraserChip()
        self.eraser_chip.toggled.connect(self._eraser_toggled)
        lay.addSpacing(12)
        lay.addWidget(self.eraser_chip)
        lay.addStretch(1)

        self._sync_grey()

    # --- public API ---
    def set_active(self, gid: int):
        if gid == self._active: return
        self._active = gid
        for ch in self._chips:
            ch.set_active(ch.gid == gid)
        if gid != -1 and self._eraser_on:
            self.set_eraser(False)
        self._sync_grey()
        self.activeChanged.emit(gid)

    def active(self) -> int:
        return self._active

    def set_eraser(self, on: bool):
        if self._eraser_on == on: return
        self._eraser_on = on
        self.eraser_chip.set_active(on)
        if on and self._active != -1:
            self.set_active(-1)
        self._sync_grey()
        self.eraserChanged.emit(on)

    def eraser(self) -> bool:
        return self._eraser_on

    # --- internal ---
    def _chip_clicked(self, gid: int):
        # toggle group; disable eraser if turning a group on
        if self._eraser_on:
            self.set_eraser(False)
        self.set_active(-1 if self._active == gid else gid)

    def _eraser_toggled(self, on: bool):
        self.set_eraser(on)

    def _sync_grey(self):
        grey = (self._active == -1)
        # when eraser is ON, always grey all chips
        if self._eraser_on: grey = True
        for ch in self._chips:
            ch.set_greyed(grey)
