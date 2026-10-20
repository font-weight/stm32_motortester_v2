# Build with the dedicated V2 recipe on CPython 3.14 x64 / Windows.
from pathlib import Path
import os
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
    excludes=["PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy"],
    noarchive=False, optimize=0,
)
cli = Analysis(
    [str(packaging / "inspect_launcher.py")],
    pathex=[str(host)], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PySide6", "shiboken6", "pyqtgraph", "numpy", "serial"],
    noarchive=False, optimize=0,
)
# Fail before sealing if dependency discovery borrowed a binary from another
# application. Our only binary providers are the pinned venv, CPython and Windows.
allowed_binary_roots = tuple(Path(root).resolve() for root in
                             (sys.prefix, sys.base_prefix, os.environ["SystemRoot"]))
for destination, source, kind in [*gui.binaries, *cli.binaries]:
    if not any(Path(source).resolve().is_relative_to(root) for root in allowed_binary_roots):
        raise RuntimeError(f"Unapproved binary source: {source}")
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
