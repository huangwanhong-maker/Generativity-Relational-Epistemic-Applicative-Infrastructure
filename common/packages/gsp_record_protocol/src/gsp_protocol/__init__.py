"""Application-independent experimental record graphs and transaction preparation.

This package validates representations, not factual truth, institutional authority,
complete GR conformance, actual file bytes or a storage implementation's atomicity.
"""

from .core import (
    CHANGE_CATEGORIES, PROFILE, PROTOCOL_VERSION, RECORD_ROLES, SCHEMA_VERSION,
    ProtocolError, capabilities, normalize_snapshot, prepare_transaction,
    project_graph, request_digest, validate_snapshot, validate_transaction,
)

__all__ = [
    "PROTOCOL_VERSION", "SCHEMA_VERSION", "PROFILE", "RECORD_ROLES",
    "CHANGE_CATEGORIES", "ProtocolError", "capabilities", "normalize_snapshot",
    "validate_snapshot", "validate_transaction", "project_graph",
    "request_digest", "prepare_transaction",
]
