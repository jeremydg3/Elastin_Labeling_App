import PyInstaller.__main__
import sys
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).resolve().parent.parent

# Define paths
assets_dir = project_root / "assets"
ui_dir = project_root / "ui"
viewer_script = ui_dir / "viewer.py"
icon_path = assets_dir / "logo.png"

# Build list of assets to include
asset_files = [
    (str(assets_dir / "logo.png"), "assets"),
    (str(assets_dir / "complete_icon.png"), "assets"),
    (str(assets_dir / "calculating-alan.gif"), "assets"),
    (str(assets_dir / "orange-cat-loading.gif"), "assets"),
    (str(assets_dir / "wip_icon.png"), "assets"),
]

# Build PyInstaller arguments
args = [
    str(viewer_script),
    "--name=ElastinQueueViewer",
    "--onefile",
    "--windowed",  # No console window (same as --noconsole)
    f"--icon={icon_path}",
]

# Add all asset files
for src, dest in asset_files:
    args.extend(["--add-data", f"{src};{dest}"])

# Add hidden imports
hidden_imports = [
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtGui",
    "PyQt6.QtCore",
    "numpy",
    "cv2",
    "tifffile",
    "requests",
    "base64",
    "csv",
]

for module in hidden_imports:
    args.extend(["--hidden-import", module])

# Additional options for better compatibility
args.extend([
    "--noconfirm",  # Overwrite output directory without asking
    "--clean",      # Clean PyInstaller cache before building
])

print("Building standalone executable...")
print(f"Script: {viewer_script}")
print(f"Assets directory: {assets_dir}")
print(f"Icon: {icon_path}")
print("\nPyInstaller arguments:")
for arg in args:
    print(f"  {arg}")
print("\n" + "="*50)

PyInstaller.__main__.run(args)
