"""
Loading animation dialog with a spinning icon.
"""
from PyQt6 import QtWidgets, QtGui, QtCore
from pathlib import Path
import os

basedir = os.path.dirname(__file__)

class LoadingDialog(QtWidgets.QDialog):
    """
    A modal loading dialog with an animated spinning icon.
    Provides a clean way to show background work is in progress.
    """
    
    def __init__(self, parent=None, title: str = "Loading...", message: str = "Processing..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | 
            QtCore.Qt.WindowType.CustomizeWindowHint |
            QtCore.Qt.WindowType.WindowTitleHint
        )
        
        # Animation state
        self._rotation_angle = 0
        self._using_alan = False
        self._using_cat = False
        
        # Create loading animation (spinning icon)
        self._loading_label = QtWidgets.QLabel()
        self._loading_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # Message label
        self._message_label = QtWidgets.QLabel(message)
        self._message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # Add rotation animation timer
        self._rotation_timer = QtCore.QTimer()
        self._rotation_timer.timeout.connect(self._rotate_icon)
        
        # Layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._message_label)
        layout.addWidget(self._loading_label)
        self.setLayout(layout)
        self.resize(200, 100)
        
        # Draw initial frame
        self._rotate_icon()
    
    def set_message(self, message: str):
        """Update the message text displayed above the spinner."""
        self._message_label.setText(message)
    
    def start(self):
        """Start the spinning animation."""
        if not self._using_alan:
            self._rotation_timer.start(50)  # Update every 50ms
    
    def stop(self):
        """Stop the spinning animation."""
        self._rotation_timer.stop()
    
    def _switch_to_alan(self):
        """Switch from spinner to Alan gif animation."""
        if self._using_alan:
            # Switch back to basic loading animation
            self._using_alan = False
            self._loading_label.setMovie(None)  # Clear the movie
            self._rotation_timer.start(50)
            return
        
        self._using_alan = True
        self._rotation_timer.stop()
        
        # Load and display the Alan gif
        try:
            alan_path = os.path.join(basedir, "assets", "calculating-alan.gif")
            movie = QtGui.QMovie(str(alan_path))
            if not movie.isValid():
                # Fallback to spinner if gif not found
                self._using_alan = False
                self._rotation_timer.start(50)
                return
            
            self._loading_label.setMovie(movie)
            movie.start()
        except Exception:
            # Fallback to spinner if anything goes wrong
            self._using_alan = False
            self._rotation_timer.start(50)

    def _switch_to_cat(self):
        """Switch from spinner to Alan gif animation."""
        if self._using_cat:
            # Switch back to basic loading animation
            self._using_cat = False
            self._loading_label.setMovie(None)  # Clear the movie
            self._rotation_timer.start(50)
            return
        
        self._using_cat = True
        self._rotation_timer.stop()
        
        # Load and display the Alan gif
        try:
            cat_path = os.path.join(basedir, "assets", "orange-cat-loading.gif")
            movie = QtGui.QMovie(cat_path)
            if not movie.isValid():
                # Fallback to spinner if gif not found
                self._using_cat = False
                self._rotation_timer.start(50)
                return
            
            self._loading_label.setMovie(movie)
            movie.start()
        except Exception:
            # Fallback to spinner if anything goes wrong
            self._using_cat = False
            self._rotation_timer.start(50)
    
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        """Handle keyboard events - switch to Alan gif when 'a' is pressed."""
        if event.key() == QtCore.Qt.Key.Key_A:
            self._switch_to_alan()
            event.accept()
        elif event.key() == QtCore.Qt.Key.Key_C:
            self._switch_to_cat()
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def showEvent(self, event: QtGui.QShowEvent):
        """Auto-start animation when dialog is shown."""
        super().showEvent(event)
        # Center on parent if available
        parent = self.parent()
        if parent and isinstance(parent, QtWidgets.QWidget):
            parent_geo = parent.geometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
            self.move(x, y)
        self.start()
    
    def closeEvent(self, event: QtGui.QCloseEvent):
        """Auto-stop animation when dialog is closed."""
        self.stop()
        super().closeEvent(event)
    
    def _rotate_icon(self):
        """Draw the rotating spinner icon."""
        self._rotation_angle = (self._rotation_angle + 15) % 360
        
        # Create rotated pixmap
        pixmap = QtGui.QPixmap(50, 50)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(25, 25)
        painter.rotate(self._rotation_angle)
        painter.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.blue))
        painter.drawEllipse(-5, -20, 10, 10)
        painter.drawEllipse(-5, 10, 10, 10)
        painter.end()
        
        self._loading_label.setPixmap(pixmap)
