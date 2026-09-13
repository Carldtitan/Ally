"""Ally: the four seams.

config   - seam 4, where things live; nothing else resolves a path
db       - seam 1, the only module that imports a database driver
storage  - seam 2, the only module that touches image bytes
tokens   - seam 3, the only module that resolves a GitHub credential

Import the modules, not their internals. Each one is the single place its
concern changes when the local deployment becomes the web deployment.
"""

from . import config, db, storage, tokens  # noqa: F401

__all__ = ["config", "db", "storage", "tokens"]
