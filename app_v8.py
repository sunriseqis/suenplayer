"""Compatibility alias: the library backend module is app.py."""

import app as _app_module
import sys

sys.modules[__name__] = _app_module
