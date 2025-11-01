import PyInstaller.__main__

PyInstaller.__main__.run([
    "viewer.py",
    "--name=ElastinQueueViewer",
    "--onefile",
    "--noconsole",      # remove this if you want terminal output
    "--add-data", "C:\\Windows\\Fonts\\arial.ttf;fonts",  # optional GUI fallback font
    "--hidden-import", "PyQt6",
    "--hidden-import", "PyQt6.QtWidgets",
    "--hidden-import", "PyQt6.QtGui",
    "--hidden-import", "PyQt6.QtCore",
])
