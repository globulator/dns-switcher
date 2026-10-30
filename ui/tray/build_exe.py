#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script to compile DNS Switcher into a standalone Windows .exe using PyInstaller.
"""

import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

def build():
    print("=" * 60)
    print("  Сборка DNS-Switcher для Windows (PyInstaller)")
    print("=" * 60)

    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller не найден. Устанавливаю...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "PyQt6"])

    sep = ";" if os.name == "nt" else ":"

    presets_src = os.path.join(PROJECT_ROOT, "dns_presets.json")
    targets_src = os.path.join(PROJECT_ROOT, "targets_list.txt")

    add_data_args = []
    if os.path.exists(presets_src):
        add_data_args += ["--add-data", f"{presets_src}{sep}."]
    if os.path.exists(targets_src):
        add_data_args += ["--add-data", f"{targets_src}{sep}."]

    dist_dir = os.path.join(PROJECT_ROOT, "dist")
    build_dir = os.path.join(PROJECT_ROOT, "build")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=DNS-Switcher",
        "--onefile",
        "--windowed",
        "--clean",
        "--uac-admin",
        f"--paths={PROJECT_ROOT}",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        *add_data_args,
        os.path.join(SCRIPT_DIR, "app.py")
    ]

    print(f"Команда сборки:\n{' '.join(cmd)}\n")
    ret = subprocess.call(cmd)

    if ret == 0:
        exe_path = os.path.join(dist_dir, "DNS-Switcher.exe")
        print("\n" + "=" * 60)
        print("  Сборка успешно завершена!")
        print(f"  Исполняемый файл: {exe_path}")
        print("=" * 60)
    else:
        print("\nОшибка при сборке PyInstaller.")
        sys.exit(ret)

if __name__ == "__main__":
    build()
