# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all

fastembed_datas, fastembed_binaries, fastembed_hidden = collect_all('fastembed')
onnx_datas, onnx_binaries, onnx_hidden = collect_all('onnxruntime')

datas = fastembed_datas + onnx_datas
binaries = fastembed_binaries + onnx_binaries
hiddenimports = ['rapidfuzz', 'folder_scout'] + fastembed_hidden + onnx_hidden

# 打包项目根目录的 models/，运行时以 local_files_only 方式离线加载。
# 只收 fastembed 实际要用的 ONNX 快照：safetensors / pytorch_model.bin 等
# 原版权重在 ONNX 推理路径上用不到，排除它们可省下约 190MB。
model_dir = os.path.join(os.getcwd(), 'models')
if os.path.isdir(model_dir):
    for dirpath, _dirnames, filenames in os.walk(model_dir):
        rel = os.path.relpath(dirpath, model_dir)
        dest = 'models' if rel == os.curdir else os.path.join('models', rel)
        for fn in filenames:
            # refs/main 没有扩展名，但它是 huggingface_hub 把 "main" 解析成快照目录的关键，
            # 必须一起打包，否则 local_files_only 加载会失败。
            if not (fn.endswith(('.onnx', '.txt', '.json')) or fn == 'main'):
                continue
            datas.append((os.path.join(dirpath, fn), dest))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'pandas',
        # PySide6 为满足依赖被拉入的无关模块，本程序只用 QtWidgets/QtCore
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql',
        'PySide6.QtTest', 'PySide6.QtBluetooth', 'PySide6.QtDesigner',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FolderScout',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='FolderScout',
)
