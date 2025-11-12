import sys, os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QScrollArea, QFrame
)
from PyQt6.QtGui import QPixmap, QMovie
from PyQt6.QtCore import Qt, QSize

basedir = os.path.dirname(__file__)

class HelpPopup(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Help Panel")
        self.setMinimumSize(800, 400)
        self.selected_button = None

        self.media_dir = os.path.join(basedir, "help_assets")
        layout = QHBoxLayout(self)

        # Option panel (left)
        self.option_panel = QVBoxLayout()
        self.option_panel.setSpacing(10)
        self.option_buttons = {}

        # Button labels
        button_labels = [
            "General use", "Tile painting", "Completing tiles",
        ]
        for label in button_labels:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(self.get_button_style())
            btn.clicked.connect(lambda checked, l=label, b=btn: self.load_help_content(l, b))
            self.option_panel.addWidget(btn)
            self.option_buttons[label] = btn

        left_widget = QWidget()
        left_widget.setLayout(self.option_panel)
        layout.addWidget(left_widget, 1)

        # Display panel (right)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.display_content = QVBoxLayout()
        self.display_widget = QWidget()
        self.display_widget.setLayout(self.display_content)
        self.scroll_area.setWidget(self.display_widget)

        layout.addWidget(self.scroll_area, 3)

    def get_button_style(self):
        # base_color = "#A9A9A9"
        selected_color = "#666666"
        return f"""
            QPushButton {{
                border: none;
                padding: 10px;
                text-align: left;
                font-size: 14px;
            }}
            QPushButton:checked {{
                background-color: {selected_color};
            }}
        """

    def clear_display(self):
        # Remove all widgets in display panel
        while self.display_content.count():
            child = self.display_content.takeAt(0)
            if child:
                childwidget = child.widget()
                if isinstance(childwidget,QWidget):
                    childwidget.deleteLater()

    def load_help_content(self, selected: str, button: QPushButton):
        # Deselect previous button
        if self.selected_button:
            self.selected_button.setChecked(False)
            self.selected_button.setStyleSheet(self.get_button_style())

        # Select new button
        self.selected_button = button
        self.selected_button.setChecked(True)
        self.selected_button.setStyleSheet(self.get_button_style())

        # Update display
        self.clear_display()

        # Example content for each section
        if selected =="General use":
            self.display_content.addWidget(QLabel("Click and drag on the canvas to navigate around. Zoom using the scroll wheel."))
            gif = QLabel()
            movie = QMovie(os.path.join(self.media_dir,"general_moveclear.gif"))
            movie.setScaledSize(QSize(400, 200))
            gif.setMovie(movie)
            movie.start()
            self.display_content.addWidget(gif)


        elif selected == "Tile painting":
            self.display_content.addWidget(QLabel("There are 4 types of tiles you can use in the canvas."))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"tiletypes.png"))
            label.setPixmap(pixmap.scaled(200,90))
            self.display_content.addWidget(label)


            self.display_content.addWidget(QLabel(""))
            self.display_content.addWidget(QLabel("Tiles use input/output logic to pass data. Each tile has its own rules"))
            self.display_content.addWidget(QLabel("regarding the number and types of inputs and outputs it can have."))
            self.display_content.addWidget(QLabel("Self connections are NOT allowed for 'Variable' or 'Equation' tiles."))


            self.display_content.addWidget(QLabel(""))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"equationtile.png"))
            label.setPixmap(pixmap.scaled(100,40))
            self.display_content.addWidget(label)
            self.display_content.addWidget(QLabel("  Attributes:"))
            self.display_content.addWidget(QLabel("    - Name: Changes to the name will be reflected in the tile's label. This does"))
            self.display_content.addWidget(QLabel("       NOT impact where the equation is used, i.e., multiple 'Equation' tiles CAN"))
            self.display_content.addWidget(QLabel("       have the same name. An unique identifier is used to create the CAFe rule."))
            self.display_content.addWidget(QLabel("    - Type: Select the dropdown menu to change the equation type. The equation display"))
            self.display_content.addWidget(QLabel("       and coefficients are updated accordingly. There are four types to choose from:"))
            text0 = [
                "         a) Sigmoidal",
                "         b) Polynomial",
                "         c) Linear",
                "         d) Exponential"
            ]
            for t in text0:
                self.display_content.addWidget(QLabel(t))
            gif = QLabel()
            movie = QMovie(os.path.join(self.media_dir,"equationtile.gif"))
            movie.setScaledSize(QSize(400, 290))
            gif.setMovie(movie)
            movie.start()
            self.display_content.addWidget(gif)
            self.display_content.addWidget(QLabel("    - Coeff(s): Define the value of the coefficient."))
            self.display_content.addWidget(QLabel("  Input:"))
            self.display_content.addWidget(QLabel("    - Only accepts a single 'Variable' or 'CAFe Agent' tile as input."))
            self.display_content.addWidget(QLabel("    - This input corresponds to the 'x' variable in the display."))
            self.display_content.addWidget(QLabel("  Output:"))
            self.display_content.addWidget(QLabel("    - Only accepts output to a 'Variable' or 'CAFe Agent' tile."))
            self.display_content.addWidget(QLabel("    - Can have multiple outputs but they must be one of the types above."))
            self.display_content.addWidget(QLabel("    - The output essentially sets the value of the 'Variable' or 'CAFe Agent'"))
            self.display_content.addWidget(QLabel("       tile, i.e., Var1 = output of Eq1."))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"setvariable.png"))
            label.setPixmap(pixmap.scaled(350,80))
            self.display_content.addWidget(label)

            self.display_content.addWidget(QLabel(""))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"variabletile.png"))
            label.setPixmap(pixmap.scaled(100,40))
            self.display_content.addWidget(label)
            self.display_content.addWidget(QLabel("  Attributes:"))
            self.display_content.addWidget(QLabel("    - Name: Changes to the name will be reflected in the tile's label. This does"))
            self.display_content.addWidget(QLabel("       NOT impact how the variable is used, i.e., multiple 'Variable' tiles CAN"))
            self.display_content.addWidget(QLabel("       have the same name since each variable has its own unique identifier."))
            self.display_content.addWidget(QLabel("    - Value: Defines the value of the variable. If an equation or 'CAFe Agent' tile"))
            self.display_content.addWidget(QLabel("       is an input, the value will be set to the input and cannot be changed."))
            self.display_content.addWidget(QLabel("  Input:"))
            self.display_content.addWidget(QLabel("    - Only accepts a single tile as input."))
            self.display_content.addWidget(QLabel("    - If the input is an 'Equation', 'CAFe Agent', or another 'Variable' tile, the value"))
            self.display_content.addWidget(QLabel("       of the variable cannot be modified."))
            self.display_content.addWidget(QLabel("    - If no input is attached, OR if the input is a 'Condition' tile, the value of the"))
            self.display_content.addWidget(QLabel("       variable can be modified. In this case, the variable will be considered a temporary"))
            self.display_content.addWidget(QLabel("       variable in CAFe, that will be cleared once it used"))
            self.display_content.addWidget(QLabel("  Output:"))
            self.display_content.addWidget(QLabel("    - Allows output to any tile type except 'Variable' tiles."))
            self.display_content.addWidget(QLabel("    - Can have multiple outputs but they must be one of the types above."))
            self.display_content.addWidget(QLabel("    - BE CAREFUL when connecting to a 'CAFe Agent' tile. This will override its value"))

            self.display_content.addWidget(QLabel(""))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"cafeagenttile.png"))
            label.setPixmap(pixmap.scaled(100,40))
            self.display_content.addWidget(label)
            self.display_content.addWidget(QLabel("  Attributes:"))
            self.display_content.addWidget(QLabel("    - Agent: Changes to the agent type will be reflected in the tile's label."))
            self.display_content.addWidget(QLabel("  Input:"))
            self.display_content.addWidget(QLabel("    - Only accepts a single tile as input."))
            self.display_content.addWidget(QLabel("    - BE CAREFUL when adding inputs. Adding a 'Variable' or 'Equation' tile will set its value"))
            self.display_content.addWidget(QLabel("       in the CAFe rule module."))
            self.display_content.addWidget(QLabel("  Output:"))
            self.display_content.addWidget(QLabel("    - Allows output to any tile type except 'Variable' tiles."))
            self.display_content.addWidget(QLabel("    - Can have multiple outputs but they must be one of the types above."))
            self.display_content.addWidget(QLabel("    - BE CAREFUL when connecting to another 'CAFe Agent' tile. This will override its value"))

            self.display_content.addWidget(QLabel(""))
            label = QLabel()
            pixmap = QPixmap(os.path.join(self.media_dir,"conditiontile.png"))
            label.setPixmap(pixmap.scaled(100,40))
            self.display_content.addWidget(label)
            self.display_content.addWidget(QLabel("  Attributes:"))
            self.display_content.addWidget(QLabel("    - Condition: Modify the condition using the dropdown menu."))
            self.display_content.addWidget(QLabel("  Input:"))
            self.display_content.addWidget(QLabel("    - Only accepts a two tiles as inputs."))
            self.display_content.addWidget(QLabel("    - Input tiles are shown when the tile's editor is opened."))
            self.display_content.addWidget(QLabel("  Output:"))
            self.display_content.addWidget(QLabel("    - True (green circle)"))
            self.display_content.addWidget(QLabel("    - False (red circle)"))


        elif selected == "Completing tiles":
            self.display_content.addWidget(QLabel("Drag and drop tiles onto the canvas to add them to the canvas."))
            gif = QLabel()
            movie = QMovie(os.path.join(self.media_dir,"general_dragdrop.gif"))
            movie.setScaledSize(QSize(400, 200))
            gif.setMovie(movie)
            movie.start()
            self.display_content.addWidget(gif)

            self.display_content.addWidget(QLabel(""))
            self.display_content.addWidget(QLabel("If you try to drop a new tile on a pre-existing one, the canvas will place"))
            self.display_content.addWidget(QLabel("the new tile at the top of the canvas."))
            gif = QLabel()
            movie = QMovie(os.path.join(self.media_dir,"general_dragdrop2.gif"))
            movie.setScaledSize(QSize(400, 200))
            gif.setMovie(movie)
            movie.start()
            self.display_content.addWidget(gif)

        self.display_content.addStretch()  # Push content to top
