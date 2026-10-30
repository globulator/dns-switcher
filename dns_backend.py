#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS Switcher - Unified CLI entrypoint.
Used by GNOME Shell extension and command-line on Linux and Windows.
"""

import os
import sys

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.cli import main

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import json
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
