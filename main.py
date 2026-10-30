#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS Switcher - Unified Entrypoint.
Usage:
  python3 main.py init
  python3 main.py list
  python3 main.py probe
  python3 main.py gui          # Launches desktop tray application
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        from ui.tray.app import main as run_gui
        run_gui()
    else:
        from core.cli import main
        main()
