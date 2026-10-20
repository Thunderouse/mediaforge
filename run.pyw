#!/usr/bin/env python3
"""Запуск из исходников без консольного окна (Windows: двойной клик по run.pyw)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mediaforge.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
