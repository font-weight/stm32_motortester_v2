# Build with the dedicated V2 recipe on CPython 3.14 x64 / Windows.
from pathlib import Path
import sys

if sys.platform != "win32":
    raise RuntimeError("Build this Windows package on Windows")

packaging = Path(SPECPATH).resolve()
host = packaging.parents[1]
gui = Analysis(
    [str(packaging / "launcher.py")],
    pathex=[str(host), str(packaging)],
    binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "serial"],
    noarchive=False, optimize=0,
)
cli = Analysis(
    [str(packaging / "inspect_launcher.py")],
    pathex=[str(host)], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PySide6", "shiboken6", "pyqtgraph", "numpy", "serial"],
    noarchive=False, optimize=0,
)
gui_exe = EXE(
    PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
    name="MotortesterV2", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    contents_directory="_internal",
)
cli_exe = EXE(
    PYZ(cli.pure), cli.scripts, [], exclude_binaries=True,
    name="MotortesterV2Inspect", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, contents_directory="_internal",
)
COLLECT(
    gui_exe, cli_exe, gui.binaries, gui.datas, cli.binaries, cli.datas,
    strip=False, upx=False, name="MotortesterV2",
)
