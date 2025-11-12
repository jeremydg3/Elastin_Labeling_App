"""
Dark theme stylesheet for Elastin Labeling App.

This module provides a comprehensive dark color scheme for all UI components
including buttons, labels, dialogs, menus, graphics views, and custom widgets.
"""

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

# ============================================================================
# Color Palette
# ============================================================================

class DarkPalette:
    """Dark theme color definitions"""
    # Background colors
    BG_PRIMARY = "#1e1e1e"          # Main background
    BG_SECONDARY = "#2d2d2d"        # Secondary panels, cards
    BG_TERTIARY = "#3e3e3e"         # Hover states, elevated surfaces
    BG_INPUT = "#252525"            # Input fields, text areas
    
    # Text colors
    TEXT_PRIMARY = "#e0e0e0"        # Primary text
    TEXT_SECONDARY = "#b0b0b0"      # Secondary text, labels
    TEXT_DISABLED = "#6e6e6e"       # Disabled text
    TEXT_INVERSE = "#1e1e1e"        # Text on light backgrounds
    
    # Border colors
    BORDER_DEFAULT = "#4a4a4a"      # Default borders
    BORDER_FOCUS = "#4d9eff"        # Focused elements
    BORDER_HOVER = "#5a5a5a"        # Hover state borders
    BORDER_LIGHT = "#3a3a3a"        # Subtle dividers
    
    # Accent colors
    ACCENT_PRIMARY = "#4d9eff"      # Primary actions, links
    ACCENT_SUCCESS = "#4CAF50"      # Success states, complete button
    ACCENT_WARNING = "#ff9800"      # Warnings, eraser mode
    ACCENT_ERROR = "#f44336"        # Errors, destructive actions
    ACCENT_INFO = "#2196f3"         # Information, highlights
    
    # Interactive states
    HOVER_OVERLAY = "rgba(255, 255, 255, 0.05)"
    PRESSED_OVERLAY = "rgba(0, 0, 0, 0.1)"
    SELECTED_BG = "#3d5a80"
    
    # Graphics view
    GRAPHICS_BG = "#2a2a2a"         # Graphics scene background
    TILE_GRID_BG = "#252525"        # Tile grid background
    
    # Scrollbar
    SCROLLBAR_BG = "#2d2d2d"
    SCROLLBAR_HANDLE = "#5a5a5a"
    SCROLLBAR_HANDLE_HOVER = "#6a6a6a"


# ============================================================================
# Main Application Stylesheet
# ============================================================================

DARK_STYLESHEET = f"""
/* ========================================================================
   Global Defaults
   ======================================================================== */

QWidget {{
    background-color: {DarkPalette.BG_PRIMARY};
    color: {DarkPalette.TEXT_PRIMARY};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
}}

QWidget:disabled {{
    color: {DarkPalette.TEXT_DISABLED};
}}

/* ========================================================================
   Main Window
   ======================================================================== */

QMainWindow {{
    background-color: {DarkPalette.BG_PRIMARY};
}}

QMainWindow::separator {{
    background-color: {DarkPalette.BORDER_DEFAULT};
    width: 1px;
    height: 1px;
}}

/* ========================================================================
   Labels
   ======================================================================== */

QLabel {{
    background-color: transparent;
    color: {DarkPalette.TEXT_PRIMARY};
    border: none;
}}

QLabel[heading="true"] {{
    font-size: 11pt;
    font-weight: 600;
    color: {DarkPalette.TEXT_PRIMARY};
}}

/* ========================================================================
   Buttons
   ======================================================================== */

QPushButton {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 6px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {DarkPalette.BG_TERTIARY};
    border-color: {DarkPalette.BORDER_HOVER};
}}

QPushButton:pressed {{
    background-color: {DarkPalette.BG_INPUT};
}}

QPushButton:disabled {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_DISABLED};
    border-color: {DarkPalette.BORDER_LIGHT};
}}

QPushButton:focus {{
    border: 2px solid {DarkPalette.BORDER_FOCUS};
    outline: none;
}}

/* Primary buttons (e.g., Next, Done) */
QPushButton[primary="true"] {{
    background-color: {DarkPalette.ACCENT_PRIMARY};
    color: white;
    border: none;
    font-weight: 600;
}}

QPushButton[primary="true"]:hover {{
    background-color: #5da5ff;
}}

QPushButton[primary="true"]:pressed {{
    background-color: #3d85df;
}}

/* Success buttons (e.g., Mark Complete) */
QPushButton[success="true"] {{
    background-color: {DarkPalette.ACCENT_SUCCESS};
    color: white;
    border: none;
    font-weight: 600;
}}

QPushButton[success="true"]:hover {{
    background-color: #5cb860;
}}

QPushButton[success="true"]:pressed {{
    background-color: #3c9840;
}}

/* Danger buttons */
QPushButton[danger="true"] {{
    background-color: {DarkPalette.ACCENT_ERROR};
    color: white;
    border: none;
    font-weight: 600;
}}

QPushButton[danger="true"]:hover {{
    background-color: #f55a4e;
}}

QPushButton[danger="true"]:pressed {{
    background-color: #d43226;
}}

/* ========================================================================
   Input Fields
   ======================================================================== */

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: {DarkPalette.SELECTED_BG};
    selection-color: white;
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: {DarkPalette.BORDER_HOVER};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {DarkPalette.BORDER_FOCUS};
    outline: none;
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {DarkPalette.BG_PRIMARY};
    color: {DarkPalette.TEXT_DISABLED};
    border-color: {DarkPalette.BORDER_LIGHT};
}}

/* ========================================================================
   Combo Box
   ======================================================================== */

QComboBox {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 6px 8px;
    padding-right: 24px;
}}

QComboBox:hover {{
    border-color: {DarkPalette.BORDER_HOVER};
}}

QComboBox:focus {{
    border: 2px solid {DarkPalette.BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {DarkPalette.TEXT_SECONDARY};
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    selection-background-color: {DarkPalette.SELECTED_BG};
    selection-color: white;
    outline: none;
}}

/* ========================================================================
   List Widget
   ======================================================================== */

QListWidget {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 8px;
    border-radius: 3px;
}}

QListWidget::item:hover {{
    background-color: {DarkPalette.BG_TERTIARY};
}}

QListWidget::item:selected {{
    background-color: {DarkPalette.SELECTED_BG};
    color: white;
}}

/* ========================================================================
   Tree Widget
   ======================================================================== */

QTreeWidget {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    outline: none;
}}

QTreeWidget::item {{
    padding: 4px;
}}

QTreeWidget::item:hover {{
    background-color: {DarkPalette.BG_TERTIARY};
}}

QTreeWidget::item:selected {{
    background-color: {DarkPalette.SELECTED_BG};
    color: white;
}}

/* ========================================================================
   Scroll Bars
   ======================================================================== */

QScrollBar:vertical {{
    background-color: {DarkPalette.SCROLLBAR_BG};
    width: 12px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background-color: {DarkPalette.SCROLLBAR_HANDLE};
    min-height: 20px;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {DarkPalette.SCROLLBAR_HANDLE_HOVER};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {DarkPalette.SCROLLBAR_BG};
    height: 12px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background-color: {DarkPalette.SCROLLBAR_HANDLE};
    min-width: 20px;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {DarkPalette.SCROLLBAR_HANDLE_HOVER};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none;
    background: none;
    width: 0px;
}}

/* ========================================================================
   Menus
   ======================================================================== */

QMenuBar {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border-bottom: 1px solid {DarkPalette.BORDER_DEFAULT};
    padding: 2px;
}}

QMenuBar::item {{
    background-color: transparent;
    padding: 6px 12px;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: {DarkPalette.BG_TERTIARY};
}}

QMenuBar::item:pressed {{
    background-color: {DarkPalette.BG_INPUT};
}}

QMenu {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 4px;
}}

QMenu::item {{
    padding: 8px 24px 8px 12px;
    border-radius: 3px;
}}

QMenu::item:selected {{
    background-color: {DarkPalette.SELECTED_BG};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background-color: {DarkPalette.BORDER_LIGHT};
    margin: 4px 8px;
}}

/* ========================================================================
   Tool Tips
   ======================================================================== */

QToolTip {{
    background-color: {DarkPalette.BG_TERTIARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 6px 8px;
}}

/* ========================================================================
   Dialogs
   ======================================================================== */

QDialog {{
    background-color: {DarkPalette.BG_PRIMARY};
}}

QMessageBox {{
    background-color: {DarkPalette.BG_PRIMARY};
}}

QMessageBox QLabel {{
    color: {DarkPalette.TEXT_PRIMARY};
}}

/* ========================================================================
   Progress Bar
   ======================================================================== */

QProgressBar {{
    background-color: {DarkPalette.BG_INPUT};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    text-align: center;
    color: {DarkPalette.TEXT_PRIMARY};
    height: 20px;
}}

QProgressBar::chunk {{
    background-color: {DarkPalette.ACCENT_PRIMARY};
    border-radius: 3px;
}}

/* ========================================================================
   Tab Widget
   ======================================================================== */

QTabWidget::pane {{
    background-color: {DarkPalette.BG_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
}}

QTabBar::tab {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_SECONDARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    padding: 8px 16px;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background-color: {DarkPalette.BG_PRIMARY};
    color: {DarkPalette.TEXT_PRIMARY};
    border-bottom-color: {DarkPalette.BG_PRIMARY};
}}

QTabBar::tab:hover:!selected {{
    background-color: {DarkPalette.BG_TERTIARY};
}}

/* ========================================================================
   Check Box and Radio Button
   ======================================================================== */

QCheckBox, QRadioButton {{
    color: {DarkPalette.TEXT_PRIMARY};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    background-color: {DarkPalette.BG_INPUT};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {DarkPalette.BORDER_HOVER};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {DarkPalette.ACCENT_PRIMARY};
    border-color: {DarkPalette.ACCENT_PRIMARY};
}}

QCheckBox::indicator:checked {{
    image: none;
}}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {DarkPalette.BG_PRIMARY};
    border-color: {DarkPalette.BORDER_LIGHT};
}}

/* ========================================================================
   Slider
   ======================================================================== */

QSlider::groove:horizontal {{
    background-color: {DarkPalette.BG_INPUT};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    height: 6px;
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background-color: {DarkPalette.ACCENT_PRIMARY};
    border: 2px solid {DarkPalette.BG_PRIMARY};
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background-color: #5da5ff;
}}

QSlider::sub-page:horizontal {{
    background-color: {DarkPalette.ACCENT_PRIMARY};
    border-radius: 3px;
}}

/* ========================================================================
   Spin Box
   ======================================================================== */

QSpinBox, QDoubleSpinBox {{
    background-color: {DarkPalette.BG_INPUT};
    color: {DarkPalette.TEXT_PRIMARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
    padding: 4px 8px;
}}

QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {DarkPalette.BORDER_HOVER};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {DarkPalette.BORDER_FOCUS};
}}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    background-color: {DarkPalette.BG_SECONDARY};
    border-left: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-top-right-radius: 4px;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {DarkPalette.BG_SECONDARY};
    border-left: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-bottom-right-radius: 4px;
}}

/* ========================================================================
   Graphics View (for tile displays)
   ======================================================================== */

QGraphicsView {{
    background-color: {DarkPalette.GRAPHICS_BG};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 4px;
}}

/* ========================================================================
   Group Bar and Custom Widgets
   ======================================================================== */

/* Group chips and eraser chip styling */
QFrame[chip="true"] {{
    background-color: {DarkPalette.BG_SECONDARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 6px;
}}

QFrame[chip="true"]:hover {{
    background-color: {DarkPalette.BG_TERTIARY};
}}

/* Active state for group chips */
QFrame[chip_active="true"] {{
    border: 2px solid {DarkPalette.ACCENT_SUCCESS};
}}

/* ========================================================================
   Status Bar
   ======================================================================== */

QStatusBar {{
    background-color: {DarkPalette.BG_SECONDARY};
    color: {DarkPalette.TEXT_SECONDARY};
    border-top: 1px solid {DarkPalette.BORDER_DEFAULT};
}}

QStatusBar::item {{
    border: none;
}}

/* ========================================================================
   Splitter
   ======================================================================== */

QSplitter::handle {{
    background-color: {DarkPalette.BORDER_DEFAULT};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

QSplitter::handle:hover {{
    background-color: {DarkPalette.BORDER_HOVER};
}}

/* ========================================================================
   Group Box
   ======================================================================== */

QGroupBox {{
    background-color: {DarkPalette.BG_SECONDARY};
    border: 1px solid {DarkPalette.BORDER_DEFAULT};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {DarkPalette.TEXT_PRIMARY};
    background-color: {DarkPalette.BG_SECONDARY};
}}
"""


# ============================================================================
# Helper Functions
# ============================================================================

def apply_dark_theme(app: QApplication):
    """
    Apply the dark theme to the entire application.
    
    Args:
        app: QApplication instance
        
    Example:
        from PyQt6.QtWidgets import QApplication
        from styles import apply_dark_theme
        
        app = QApplication(sys.argv)
        apply_dark_theme(app)
    """
    app.setStyleSheet(DARK_STYLESHEET)


def get_color(color_name: str) -> QColor:
    """
    Get a QColor object from the dark palette.
    
    Args:
        color_name: Attribute name from DarkPalette (e.g., 'BG_PRIMARY')
        
    Returns:
        QColor object
        
    Example:
        bg_color = get_color('BG_PRIMARY')
    """
    if hasattr(DarkPalette, color_name):
        return QColor(getattr(DarkPalette, color_name))
    raise ValueError(f"Color '{color_name}' not found in DarkPalette")


def get_tile_grid_background() -> str:
    """Get the background color for tile grid views."""
    return DarkPalette.TILE_GRID_BG


def get_graphics_view_background() -> str:
    """Get the background color for graphics views."""
    return DarkPalette.GRAPHICS_BG
