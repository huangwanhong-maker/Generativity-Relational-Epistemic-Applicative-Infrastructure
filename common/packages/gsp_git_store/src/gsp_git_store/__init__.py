"""Application-independent Git storage binding for Generativity project records."""

from .store import Conflict, GitStore, LimitExceeded, NotFound, StoreError

__version__ = "0.2.0"
__all__ = ["GitStore", "Conflict", "NotFound", "StoreError", "LimitExceeded"]
