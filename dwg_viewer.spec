# -*- mode: python ; coding: utf-8 -*-

import glob

# Bundle the ODA File Converter (Windows x64) so the application is
# self-contained. For personal use only.
oda_dirs = sorted(glob.glob(r"C:\Program Files\ODA\ODAFileConverter*"))
datas = [(oda_dirs[0], "oda")] if oda_dirs else []

hiddenimports = [
    "ezdxf.addons.drawing.pyqt",
    "ezdxf.addons.drawing.unified_text_renderer",
    "ezdxf.addons.odafc",
    "ezdxf.render.hatching",
    "ezdxf.fonts.font_manager",
    "fontTools.ttLib",
    "PIL.Image",
]

excludes = [
    "matplotlib",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "IPython",
    "pytest",
    "scipy",
    "pandas",
    "setuptools",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
]

a = Analysis(
    ["src/dwg_viewer/main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DWGViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DWGViewer",
)
