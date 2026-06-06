import PyInstaller.__main__
import sys
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).resolve().parent.parent

# Define paths
assets_dir = project_root / "ui" / "assets"
ui_dir = project_root / "ui"
viewer_script = ui_dir / "viewer.py"
icon_path = assets_dir / "logo.png"

# One-file executables are more likely to be quarantined by AV heuristics.
# Keep default build in one-dir mode for reliability on Windows.
USE_ONEFILE = False

# Build list of assets to include
asset_files = [
    (str(assets_dir / "logo.png"), "assets"),
    (str(assets_dir / "complete_icon.png"), "assets"),
    (str(assets_dir / "calculating-alan.gif"), "assets"),
    (str(assets_dir / "orange-cat-loading.gif"), "assets")
]

# Build PyInstaller arguments
args = [
    str(viewer_script),
    "--name=ElastinQueueViewer",
    "--windowed",  # No console window (same as --noconsole)
    f"--icon={icon_path}",
]

if USE_ONEFILE:
    args.append("--onefile")
else:
    args.append("--onedir")

# Add all asset files
for src, dest in asset_files:
    args.extend(["--add-data", f"{src};{dest}"])
# TODO: Add support for Mac
# for src, dest in asset_files:
#     args.extend(["--add-data", f"{src};{dest}"])

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
    "imagecodecs"
]

for module in hidden_imports:
    args.extend(["--hidden-import", module])

# Additional options for better compatibility
args.extend([
    "--noconfirm",  # Overwrite output directory without asking
    "--clean",      # Clean PyInstaller cache before building
    "--noupx",      # Reduces AV false positives on Windows
])

# Ensure imagecodecs compiled extensions and data are collected (needed for lzw_decode, etc.)
args.extend([
    "--collect-binaries", "imagecodecs",
    "--collect-data", "imagecodecs",
    "--collect-submodules", "imagecodecs",
    # tifffile sometimes lazy-loads plugins; collect them as well
    "--collect-submodules", "tifffile",
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
