"""Plugin loader: every module in this package that defines `register(app)` is loaded automatically.

To add a feature, drop a new file in this folder — nothing else to edit.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)


def load_plugins(app) -> None:
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(app)
            log.info("Loaded plugin: %s", info.name)
