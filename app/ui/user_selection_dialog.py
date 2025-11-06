"""
User Selection Dialog
Allows users to select an existing user or create a new one on app startup.
"""
from PyQt6 import QtWidgets, QtCore
from typing import Optional, List
from webapp_interface_funcs import create_new_user

class UserSelectionDialog(QtWidgets.QDialog):
    """
    Dialog for selecting or creating a user at app startup.
    """
    
    def __init__(self, users: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select User")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.selected_user: Optional[str] = None
        
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        
        # Instructions
        instructions = QtWidgets.QLabel("Please select your username or create a new one:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # User list
        self.user_list = QtWidgets.QListWidget()
        self.user_list.addItems(users)
        self.user_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.user_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.user_list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.user_list)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.btn_create_new = QtWidgets.QPushButton("Create New User")
        self.btn_create_new.clicked.connect(self._on_create_new)
        
        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_ok.setEnabled(False)  # Disabled until user selects
        self.btn_ok.clicked.connect(self.accept)
        self.btn_ok.setDefault(True)
        
        button_layout.addWidget(self.btn_create_new)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_ok)
        
        layout.addLayout(button_layout)
        
        # Set initial focus to the list
        self.user_list.setFocus()
        
    def _on_selection_changed(self):
        """Enable OK button when a user is selected."""
        selected_items = self.user_list.selectedItems()
        self.btn_ok.setEnabled(len(selected_items) > 0)
        
        if selected_items:
            self.selected_user = selected_items[0].text()
        else:
            self.selected_user = None
    
    def _on_double_click(self, item):
        """Accept dialog on double-click."""
        self.selected_user = item.text()
        self.accept()
    
    def _on_create_new(self):
        """Prompt user to create a new username."""
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "Create New User",
            "Enter your username:",
            QtWidgets.QLineEdit.EchoMode.Normal
        )
        
        if ok and text.strip():
            username = text.strip()
            # Check if username already exists
            existing_users = []
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                if item is not None:
                    existing_users.append(item.text())
            
            if username in existing_users:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Username Exists",
                    f"The username '{username}' already exists. Please select it from the list or choose a different name."
                )
                return
            
            self.selected_user = username
            create_new_user(username)
            self.accept()
        elif ok and not text.strip():
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Username",
                "Username cannot be empty. Please try again."
            )
    
    def get_selected_user(self) -> Optional[str]:
        """Return the selected or created username."""
        return self.selected_user


def show_user_selection_dialog(users: List[str], parent=None) -> Optional[str]:
    """
    Convenience function to show user selection dialog and return selected username.
    
    Args:
        users: List of existing usernames
        parent: Parent widget (optional)
    
    Returns:
        Selected username or None if dialog was cancelled
    """
    dialog = UserSelectionDialog(users, parent)
    result = dialog.exec()
    
    if result == QtWidgets.QDialog.DialogCode.Accepted:
        return dialog.get_selected_user()
    return None
