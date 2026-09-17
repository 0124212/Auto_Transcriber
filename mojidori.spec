# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller bundle for Mojidori (Windows EXE).
Built automatically by .github/workflows/build-exe.yml — never build by hand.
Single-folder bundle: everything the app needs sits next to the EXE,
so queue/ and processed/ live beside it, fully portable.
"""
from PyInstaller.utils.hooks import collect_all

whisper_datas, whisper_binaries, whisper_hidden = collect_all('whisper')

a = Analysis(
    ['start.py'],
    pathex=[],
    binaries=whisper_binaries,
    datas=whisper_datas + [
        ('templates', 'templates'),
        ('prompt_cheat_sheet.md', '.'),
        ('prompt_condensed_notes.md', '.'),
        ('prompt_descriptive_summary.md', '.'),
    ],
    hiddenimports=whisper_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'IPython', 'notebook', 'nbformat',
        'pytest', 'sphinx',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Mojidori',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trips antivirus heuristics; skip it
    console=True,  # keep the console: it shows the URL + live status
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Mojidori',
)
