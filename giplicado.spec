# -*- mode: python ; coding: utf-8 -*-
# Compilar con:  python -m PyInstaller giplicado.spec --noconfirm
# Resultado:     dist\Giplicado\Giplicado.exe

a = Analysis(
    ["main.py"],
    datas=[
        ("tools/fpcalc.exe", "tools"),
        ("assets/giplicado.png", "assets"),
    ],
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest", "scipy", "imagehash", "pywt",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtCharts",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Giplicado",
    icon="assets/giplicado.ico",
    console=False,          # app de ventana, sin consola negra
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Giplicado", upx=False)
