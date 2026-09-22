"""Pure preparation and validation for the experimental general recording profile."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import math
import re
from typing import Any

import rfc8785

from ._schema import validator


PROTOCOL_VERSION = "gsp-record-protocol/0.2"
SCHEMA_VERSION = "gsp-workspace/0.2"
LEGACY_SCHEMA_VERSION = "gsp-workspace/0.1"
PROFILE = "gsp.general/0.2"
RECORD_ROLES = ("Entity", "State", "Event", "Process", "Relation", "Property")
CHANGE_CATEGORIES = ("description", "represented_change", "evidence_or_interpretation",
                     "classification", "maintenance", "migration")
BUILTINS = {"gsp.relation": "RelationData", "gsp.notes": "NotesData", "gsp.files": "FilesData"}
ENUMS = {
    "record_type": RECORD_ROLES,
    "epistemic_mode": ("observed", "reported", "inferred", "interpreted", "retrospective"),
    "modality": ("realized", "intended", "possible", "unrealized", "unknown"),
    "status": ("unreviewed", "contested", "revised", "withdrawn"),
}
TEXT_LIMITS = {"title": 160, "content": 20000, "attributed_to": 300, "method": 2000,
               "evidence": 5000, "uncertainty": 3000, "alternatives": 3000,
               "conditions": 3000, "consequences": 3000, "occurred_at": 100}
CORE_FIELDS = set(TEXT_LIMITS) | set(ENUMS) | {"record_roles", "related_records"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TRANSACTION_FILE_BYTES = 20 * 1024 * 1024
MAX_BINARY_PARTS = 8
MAX_OPERATIONS = 100
MAX_RECORDS = 1000
MAX_MODULE_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
LIMITATIONS = [
    "Structural and scoped semantic validation does not establish factual truth or GR conformity.",
    "The storage adapter must verify binary bytes, authorization, historical reachability and atomic publication.",
    "Record references identify representations; represented-target identity remains a separate claim.",
]


class ProtocolError(Exception):
    """A bounded, application-independent validation or preparation failure."""

    def __init__(self, code: str, message: str, fields: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


def capabilities() -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "record_roles": list(RECORD_ROLES),
        "change_categories": list(CHANGE_CATEGORIES),
        "modules": {key: {"versions": ["1"], "required_default": False} for key in BUILTINS},
        "operations": ["record.create", "record.update", "module.set", "module.remove",
                       "file.attach", "file.replace", "file.detach", "project.migrate"],
        "limits": {"operations": MAX_OPERATIONS, "records": MAX_RECORDS,
                   "participants_per_relation": 32, "binary_parts": MAX_BINARY_PARTS,
                   "file_bytes": MAX_FILE_BYTES, "transaction_file_bytes": MAX_TRANSACTION_FILE_BYTES,
                   "module_bytes": MAX_MODULE_BYTES, "transaction_json_bytes": MAX_REQUEST_BYTES},
        "graph_projection": "gsp.incidence/1",
        "canonicalization": "RFC 8785",
        "limitations": list(LIMITATIONS),
    }


def _json(value: Any, limit: int = MAX_REQUEST_BYTES) -> bytes:
    """Reject non-JSON types and pathological nesting before canonicalization."""
    def check(item: Any, depth: int = 0):
        if depth > 32:
            raise ProtocolError("json_depth", "JSON nesting exceeds the supported depth.")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item) or "\0" in item:
                raise ProtocolError("json_text", "JSON text contains an invalid Unicode value or null character.")
        elif type(item) is int:
            if not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ProtocolError("json_number", "JSON integers must be exactly representable within the canonicalization profile.")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ProtocolError("json_number", "Nonfinite JSON numbers are not supported.")
        elif isinstance(item, list):
            for member in item:
                check(member, depth + 1)
        elif isinstance(item, dict):
            for key, member in item.items():
                if not isinstance(key, str):
                    raise ProtocolError("json_member", "JSON member names must be strings.")
                check(key, depth + 1)
                check(member, depth + 1)
        else:
            raise ProtocolError("json_type", "Only JSON-compatible values are supported.")
    check(value)
    try:
        encoded = rfc8785.dumps(value)
    except (ValueError, TypeError, UnicodeError) as error:
        raise ProtocolError("canonicalization", "The request cannot be canonically represented.") from error
    if len(encoded) > limit:
        raise ProtocolError("json_size", "The JSON representation exceeds the supported size.")
    return encoded


def _validate(kind: str, value: Any, prefix: str = "") -> None:
    errors = sorted(validator(kind).iter_errors(value), key=lambda e: tuple(str(x) for x in e.absolute_path))
    if errors:
        # Bound the response and avoid echoing untrusted content or opaque modules.
        fields = {}
        for error in errors[:12]:
            path = ".".join(str(x) for x in error.absolute_path)
            locator = ".".join(x for x in [prefix, path] if x) or kind.lower()
            fields[locator] = f"Does not satisfy the {error.validator} constraint."
        raise ProtocolError("validation", "The representation does not match the experimental protocol schema.", fields)


def _timestamp(value: str, field: str) -> None:
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ProtocolError("timestamp", "Recording timestamps must identify their time offset.", {field: "Use an ISO 8601 timestamp with an offset."}) from None


def _text(value: str, field: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ProtocolError("validation", "A text field is invalid.", {field: "Use text."})
    value = value.strip()
    if len(value) > maximum or (required and not value) or "\0" in value:
        raise ProtocolError("validation", "A text field is invalid.", {field: f"Use {'1' if required else '0'} to {maximum} characters."})
    return value


def normalize_snapshot(snapshot: dict) -> dict:
    """Return a non-mutating read adaptation; schema declarations stay original."""
    _json(snapshot, MAX_SNAPSHOT_BYTES)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("project"), dict) \
            or not isinstance(snapshot.get("records"), list):
        raise ProtocolError("snapshot", "A project manifest and record list are required.")
    source_version = snapshot["project"].get("schema_version")
    if source_version not in {SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}:
        raise ProtocolError("schema_version", "This project schema version is unsupported.")
    result = deepcopy(snapshot)
    legacy = source_version == LEGACY_SCHEMA_VERSION
    if legacy:
        for record in result["records"]:
            if not isinstance(record, dict):
                raise ProtocolError("snapshot", "Every retained record must be an object.")
            # Existing values are never silently replaced by inferred values.
            record.setdefault("record_roles", [record.get("record_type")])
            record.setdefault("modules", {})
    result["legacy"] = legacy
    result["source_schema_version"] = source_version
    result["read_adaptation"] = {
        "applied": legacy,
        "limitations": (["Primary legacy roles are displayed as singleton role sets; absent modules are shown as empty.",
                         "Untyped references remain neutral and unstructured relations are not inferred.",
                         "This read adaptation is not a stored migration."] if legacy else []),
    }
    return result


def _module_known(module_id: str, module: dict) -> bool:
    return module_id in BUILTINS and module.get("version") == "1"


def _file_metadata(item: dict, prefix: str) -> None:
    if type(item["byte_length"]) is not int:
        raise ProtocolError("binary_metadata", "File byte lengths must use integer JSON values.")
    filename = item["filename"]
    if filename.strip() != filename or any(ord(c) < 32 or ord(c) == 127 for c in filename) \
            or "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ProtocolError("filename", "Use a display filename without path separators or control characters.", {prefix: "Invalid filename."})
    if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", item["media_type"]):
        raise ProtocolError("media_type", "Use a declared media type without parameters or control characters.")


def _validate_modules(record: dict, ids: set[str], warnings: list[dict]) -> None:
    for module_id, module in record["modules"].items():
        prefix = f"records.{record['id']}.modules.{module_id}"
        _json(module, MAX_MODULE_BYTES)
        if not _module_known(module_id, module):
            warnings.append({"code": "unsupported_required_module" if module.get("required", False) else "unsupported_module",
                             "record_id": record["id"], "module_id": module_id,
                             "message": "This module is preserved without interpretation; required unknown constraints block mutation."})
            continue
        _validate(BUILTINS[module_id], module["data"], prefix)
        data = module["data"]
        if module_id == "gsp.relation":
            if "Relation" not in record["record_roles"]:
                raise ProtocolError("relation_role", "A structured relation requires the Relation recording role.", {prefix: "Add the Relation role or remove this module explicitly."})
            if not data["predicate"].strip():
                raise ProtocolError("relation_predicate", "A relation predicate is required.")
            if not data["participants_complete"] and not data.get("participant_limitations", "").strip():
                raise ProtocolError("participant_limitations", "An incomplete participant account requires its limitation.")
            seen = set()
            for participant in data["participants"]:
                if participant["id"] in seen:
                    raise ProtocolError("duplicate_incidence", "Relation participant incidence identifiers must be distinct.")
                seen.add(participant["id"])
                if not participant["role"].strip():
                    raise ProtocolError("participant_role", "Each participant requires a stated role.")
                if participant["record_id"] not in ids:
                    raise ProtocolError("missing_reference", "A relation participant is not present in this project snapshot.", {prefix: participant["record_id"]})
        elif module_id == "gsp.files":
            seen = set()
            for descriptor in data["items"]:
                if descriptor["file_id"] in seen:
                    raise ProtocolError("duplicate_file", "File descriptor identifiers must be distinct within a record.")
                seen.add(descriptor["file_id"])
                _file_metadata(descriptor, prefix)
                _timestamp(descriptor["uploaded_at"], prefix)


def validate_snapshot(snapshot: dict) -> dict:
    """Validate retained representations and report unsupported optional semantics.

    Legacy read adaptation is declared; this method never migrates or writes data.
    Assets are deliberately not inspected by this pure package.
    """
    adapted = normalize_snapshot(snapshot)
    _validate("Snapshot", adapted)
    ids = {record["id"] for record in adapted["records"]}
    if len(ids) != len(adapted["records"]):
        raise ProtocolError("duplicate_record", "Record identifiers must be unique within a snapshot.")
    warnings = []
    declared_profile = adapted["project"].get("profile")
    if declared_profile is not None and declared_profile != PROFILE:
        warnings.append({"code": "unsupported_profile", "profile": declared_profile,
                         "message": "The declared project profile is preserved without interpretation; its additional constraints block mutation by this implementation."})
    for record in adapted["records"]:
        if record["schema_version"] != adapted["project"]["schema_version"]:
            raise ProtocolError("mixed_schema", "Project and retained record schema declarations must agree.")
        if record["record_type"] not in record["record_roles"]:
            raise ProtocolError("primary_role", "The primary recording role must be included in the role set.")
        if not record["title"].strip() or not record["content"].strip():
            raise ProtocolError("record_content", "A record requires a title and account.")
        _timestamp(record["created_at"], "created_at")
        _timestamp(record["updated_at"], "updated_at")
        if any(reference not in ids for reference in record["related_records"]):
            raise ProtocolError("missing_reference", "A neutral reference is not present in this project snapshot.")
        _validate_modules(record, ids, warnings)
        if "Relation" in record["record_roles"] and not _module_known("gsp.relation", record["modules"].get("gsp.relation", {})):
            warnings.append({"code": "unstructured_relation", "record_id": record["id"],
                             "message": "This Relation account has no interpreted participant module; no incidence is inferred."})
    if adapted["legacy"]:
        warnings.append({"code": "legacy_read_adaptation", "message": "The source remains a legacy project; explicit migration is required for mutation."})
    return {"valid": True, "protocol_version": PROTOCOL_VERSION, "profile": PROFILE,
            "declared_profile": declared_profile,
            "source_schema_version": adapted["source_schema_version"], "legacy": adapted["legacy"],
            "record_count": len(ids), "warnings": warnings, "limitations": list(LIMITATIONS)}


def project_graph(snapshot: dict) -> dict:
    report = validate_snapshot(snapshot)
    adapted = normalize_snapshot(snapshot)
    nodes, edges = [], []
    for record in sorted(adapted["records"], key=lambda item: item["id"]):
        relation = record["modules"].get("gsp.relation", {})
        structured = _module_known("gsp.relation", relation)
        nodes.append({"id": record["id"], "label": record["title"],
                      "record_type": record["record_type"], "record_roles": list(record["record_roles"]),
                      "status": record["status"], "structured_relation": structured,
                      "predicate": relation["data"]["predicate"] if structured else None})
        if structured:
            for participant in relation["data"]["participants"]:
                source, target = record["id"], participant["record_id"]
                if participant["orientation"] == "in":
                    source, target = target, source
                edges.append({"id": f"incidence:{record['id']}:{participant['id']}",
                              "source": source, "target": target, "kind": "incidence",
                              "relation_id": record["id"], "participant_id": participant["id"],
                              "role": participant["role"], "reference_scope": participant["reference_scope"],
                              "orientation": participant["orientation"]})
        for related in sorted(record["related_records"]):
            edges.append({"id": f"reference:{record['id']}:{related}", "source": record["id"],
                          "target": related, "kind": "reference", "relation_id": None,
                          "role": "related record", "reference_scope": "record", "orientation": "undirected"})
    return {"head": adapted["head"], "project_id": adapted["project"]["id"],
            "protocol_version": PROTOCOL_VERSION, "projection": "gsp.incidence/1",
            "nodes": nodes, "edges": edges, "warnings": report["warnings"],
            "selection": {"kind": "all_retained_records", "hidden_nodes": 0, "hidden_edges": 0},
            "legacy": adapted["legacy"], "limitations": list(LIMITATIONS)}


def validate_transaction(tx: dict) -> dict:
    """Check the request shape; snapshot-dependent checks happen in preparation."""
    _json(tx)
    _validate("Transaction", tx)
    if not tx["reason"].strip():
        raise ProtocolError("reason", "A revision reason is required.")
    migrations = [op for op in tx["operations"] if op["op"] == "project.migrate"]
    if migrations and (len(tx["operations"]) != 1 or tx["change_categories"] != ["migration"]):
        raise ProtocolError("migration_scope", "Migration is a sole operation with the migration change category.")
    if not migrations and "migration" in tx["change_categories"]:
        raise ProtocolError("migration_scope", "The migration category is reserved to project migration.")
    return {"valid": True, "protocol_version": PROTOCOL_VERSION, "operation_count": len(tx["operations"])}


def _verified_parts(tx: dict, files_meta: dict) -> dict:
    if not isinstance(files_meta, dict):
        raise ProtocolError("binary_parts", "Verified binary-part metadata must be a mapping.")
    _json(files_meta)
    operations = [op for op in tx["operations"] if op["op"] in {"file.attach", "file.replace"}]
    names = [op["part"] for op in operations]
    if len(names) != len(set(names)):
        raise ProtocolError("duplicate_part", "A binary part can be declared by only one file operation.")
    if set(names) != set(files_meta):
        raise ProtocolError("binary_parts", "Binary parts must exactly match the file operations.")
    if len(names) > MAX_BINARY_PARTS:
        raise ProtocolError("binary_limit", "The transaction contains too many binary parts.")
    total = 0
    for operation in operations:
        meta = files_meta[operation["part"]]
        if not isinstance(meta, dict) or set(meta) != {"sha256", "byte_length"} \
                or type(meta.get("byte_length")) is not int \
                or not isinstance(meta.get("sha256"), str):
            raise ProtocolError("binary_metadata", "Verified file metadata requires a SHA-256 and integer byte length only.")
        if meta["sha256"] != operation["sha256"] or meta["byte_length"] != operation["byte_length"]:
            raise ProtocolError("binary_mismatch", "Declared file identity does not match the verified binary part.")
        if not 0 <= meta["byte_length"] <= MAX_FILE_BYTES:
            raise ProtocolError("binary_limit", "The binary file exceeds the supported size.")
        _file_metadata(operation, operation["part"])
        total += meta["byte_length"]
    if total > MAX_TRANSACTION_FILE_BYTES:
        raise ProtocolError("binary_limit", "The transaction's binary material exceeds the supported total size.")
    return deepcopy(files_meta)


def request_digest(tx: dict, files_meta: dict | None = None) -> str:
    """SHA-256 of JCS({transaction, files}); callers verify actual bytes first."""
    validate_transaction(tx)
    parts = _verified_parts(tx, {} if files_meta is None else files_meta)
    return hashlib.sha256(_json({"transaction": tx, "files": parts}, MAX_REQUEST_BYTES + 65536)).hexdigest()


def _new_record(value: dict, actor: dict, now: str) -> dict:
    record = deepcopy(value)
    record.setdefault("record_roles", [record["record_type"]])
    record.setdefault("related_records", [])
    record.setdefault("modality", "unknown")
    record.setdefault("status", "unreviewed")
    record.setdefault("modules", {})
    for key in TEXT_LIMITS:
        record[key] = _text(record.get(key, ""), key, TEXT_LIMITS[key], key in {"title", "content"})
    for module_id, module in record["modules"].items():
        if not _module_known(module_id, module):
            raise ProtocolError("unsupported_module", "New records can only introduce supported module versions.")
        module.setdefault("required", False)
        if module_id == "gsp.files" and module["data"].get("items") != []:
            raise ProtocolError("file_operation_required", "Create linked files through file operations.")
        _module_defaults(module_id, module)
    record.update({"schema_version": SCHEMA_VERSION, "recorded_by": deepcopy(actor),
                   "updated_by": deepcopy(actor), "created_at": now, "updated_at": now})
    return record


def _module_defaults(module_id: str, module: dict) -> None:
    if module_id == "gsp.relation":
        for key in ["predicate_definition", "participant_limitations", "context", "identity_criterion", "temporal_scope"]:
            module["data"].setdefault(key, "")


def _mutation_keys(tx: dict) -> None:
    """Refuse ambiguous repeated writes, including module/file removal conflicts."""
    core, modules, file_keys, creates = set(), set(), set(), {}
    file_record_ids = set()
    file_module_ops = {}
    for operation in tx["operations"]:
        kind = operation["op"]
        if kind in {"record.create", "record.update"}:
            record_id = operation["record"]["id"] if kind == "record.create" else operation["record_id"]
            if record_id in core:
                raise ProtocolError("duplicate_mutation", "A record's core can be created or updated only once per transaction.")
            core.add(record_id)
            if kind == "record.create":
                creates[record_id] = operation["record"].get("modules", {})
                for module_id in creates[record_id]:
                    modules.add((record_id, module_id))
        elif kind in {"module.set", "module.remove"}:
            key = (operation["record_id"], operation["module_id"])
            if key in modules:
                raise ProtocolError("duplicate_mutation", "A module can be mutated only once per transaction.")
            modules.add(key)
            if operation["module_id"] == "gsp.files":
                file_module_ops[operation["record_id"]] = kind
        elif kind.startswith("file."):
            key = (operation["record_id"], operation["file_id"])
            if key in file_keys:
                raise ProtocolError("duplicate_mutation", "A file descriptor can be mutated only once per transaction.")
            file_keys.add(key)
            file_record_ids.add(operation["record_id"])
    # Catch module.create in record.create after a module operation in request order.
    for operation in tx["operations"]:
        if operation["op"] in {"module.set", "module.remove"} and operation["module_id"] in creates.get(operation["record_id"], {}):
            raise ProtocolError("duplicate_mutation", "A created module cannot be replaced in the same transaction.")
    for record_id in file_record_ids:
        if file_module_ops.get(record_id) == "module.remove":
            raise ProtocolError("duplicate_mutation", "Detach files before removing their module in a subsequent transaction.")


def prepare_transaction(snapshot: dict, tx: dict, actor: dict, now: str,
                        files_meta: dict | None = None) -> dict:
    """Return a complete candidate and receipt without storage or side effects.

    The caller supplies authenticated actor/time and verified binary metadata. The
    returned snapshot still identifies its parent head; the storage adapter adds
    its new commit identifier only after conditional publication succeeds.
    """
    validate_transaction(tx)
    digest = request_digest(tx, files_meta)
    _json(actor)
    _validate("Actor", actor)
    _timestamp(now, "recorded_at")
    report = validate_snapshot(snapshot)
    if tx["expected_head"] != snapshot["head"]:
        raise ProtocolError("conflict", "The project changed after this request's expected revision.")
    if any(warning["code"] == "unsupported_profile" for warning in report["warnings"]):
        raise ProtocolError("unsupported_profile", "This project's declared profile requires a supported adapter before mutation.")
    if any(warning["code"] == "unsupported_required_module" for warning in report["warnings"]):
        raise ProtocolError("unsupported_required_module", "A required module cannot be interpreted; this project cannot be mutated by this implementation.")
    migration = tx["operations"][0]["op"] == "project.migrate"
    if report["legacy"] and not migration:
        raise ProtocolError("migration_required", "Migrate this legacy project explicitly before editing it.")
    if migration and not report["legacy"]:
        raise ProtocolError("already_migrated", "This project already uses the current schema.")
    _mutation_keys(tx)
    candidate = {"project": deepcopy(snapshot["project"]), "records": [], "head": snapshot["head"]}
    changes = []
    changed = set()
    if migration:
        normalized = normalize_snapshot(snapshot)
        candidate["project"].update({"schema_version": SCHEMA_VERSION,
                                     "protocol_version": PROTOCOL_VERSION, "profile": PROFILE})
        candidate["project"]["migration"] = {
            "from_schema_version": LEGACY_SCHEMA_VERSION, "source_head": snapshot["head"],
            "transaction_id": tx["transaction_id"], "recorded_at": now, "actor": deepcopy(actor),
            "limitations": normalized["read_adaptation"]["limitations"],
        }
        for record in normalized["records"]:
            record["schema_version"] = SCHEMA_VERSION
            # Migration changes the encoding, not the account's recorded author/time.
            candidate["records"].append(record)
            changed.add(record["id"])
        changes.append({"op": "project.migrate", "project_id": candidate["project"]["id"],
                        "record_ids": sorted(changed), "from_schema_version": LEGACY_SCHEMA_VERSION,
                        "to_schema_version": SCHEMA_VERSION})
    else:
        records = {record["id"]: deepcopy(record) for record in snapshot["records"]}
        # Materialize all new records first so semantic references can be cyclic,
        # higher order, or point to a record created later in request order.
        for operation in tx["operations"]:
            if operation["op"] != "record.create":
                continue
            value = operation["record"]
            if value["id"] in records:
                raise ProtocolError("record_exists", "The requested new record identifier already exists.")
            records[value["id"]] = _new_record(value, actor, now)
            changed.add(value["id"])
        if len(records) > MAX_RECORDS:
            raise ProtocolError("record_limit", "The project exceeds this profile's record limit.")
        for operation in tx["operations"]:
            kind = operation["op"]
            record_id = operation["record"]["id"] if kind == "record.create" else operation["record_id"]
            if record_id not in records:
                raise ProtocolError("record_not_found", "A mutation refers to a record absent from the candidate project.")
            record = records[record_id]
            summary = {"op": kind, "record_id": record_id}
            if kind == "record.update":
                value = deepcopy(operation["changes"])
                for key in value:
                    if key in TEXT_LIMITS:
                        value[key] = _text(value[key], key, TEXT_LIMITS[key], key in {"title", "content"})
                record.update(value)
                summary["fields"] = sorted(value)
            elif kind == "module.set":
                module_id, module = operation["module_id"], deepcopy(operation["module"])
                previous = record["modules"].get(module_id)
                if previous is not None and not _module_known(module_id, previous):
                    raise ProtocolError("unsupported_module", "Unsupported module data is read-only and cannot be overwritten.")
                if not _module_known(module_id, module):
                    raise ProtocolError("unsupported_module", "Only supported module versions can be introduced or edited.")
                module.setdefault("required", False)
                _module_defaults(module_id, module)
                if module_id == "gsp.files":
                    if module["data"].get("items") != [] or (previous is not None and previous["data"].get("items")):
                        raise ProtocolError("file_operation_required", "Enable only an empty files module; alter file descriptors through file operations.")
                record["modules"][module_id] = module
                summary["module_id"] = module_id
            elif kind == "module.remove":
                module_id = operation["module_id"]
                if module_id not in record["modules"]:
                    raise ProtocolError("module_not_found", "The module to remove is not present.")
                previous = record["modules"][module_id]
                if not _module_known(module_id, previous):
                    raise ProtocolError("unsupported_module", "Unsupported module data is read-only and cannot be removed.")
                if module_id == "gsp.files" and previous["data"]["items"]:
                    raise ProtocolError("files_linked", "Detach linked files before removing their module.")
                del record["modules"][module_id]
                summary["module_id"] = module_id
            elif kind.startswith("file."):
                module = record["modules"].get("gsp.files")
                if module is not None and not _module_known("gsp.files", module):
                    raise ProtocolError("unsupported_module", "The existing files module version cannot be edited.")
                if module is None:
                    if kind != "file.attach":
                        raise ProtocolError("file_not_found", "No linked file descriptor was found.")
                    module = {"version": "1", "required": False, "data": {"items": []}}
                    record["modules"]["gsp.files"] = module
                descriptors = module["data"]["items"]
                index = next((index for index, item in enumerate(descriptors) if item["file_id"] == operation["file_id"]), None)
                if kind == "file.attach" and index is not None:
                    raise ProtocolError("file_exists", "A file descriptor with this identity is already linked.")
                if kind != "file.attach" and index is None:
                    raise ProtocolError("file_not_found", "The file descriptor to change is not linked to this record.")
                if kind == "file.detach":
                    del descriptors[index]
                else:
                    descriptor = {key: operation[key] for key in ["file_id", "filename", "media_type", "sha256", "byte_length"]}
                    descriptor.update({"uploaded_by": deepcopy(actor), "uploaded_at": now})
                    if kind == "file.attach":
                        descriptors.append(descriptor)
                    else:
                        descriptors[index] = descriptor
                    summary.update({"sha256": descriptor["sha256"], "byte_length": descriptor["byte_length"]})
                summary["file_id"] = operation["file_id"]
            record["updated_at"], record["updated_by"] = now, deepcopy(actor)
            changed.add(record_id)
            changes.append(summary)
        candidate["records"] = sorted(records.values(), key=lambda value: value["id"])
    validation = validate_snapshot(candidate)
    receipt = {
        "protocol_version": PROTOCOL_VERSION, "transaction_id": tx["transaction_id"],
        "expected_head": tx["expected_head"], "actor": deepcopy(actor), "recorded_at": now,
        "reason": tx["reason"].strip(), "change_categories": list(tx["change_categories"]),
        "request_digest": digest, "changes": changes,
        "validation": {"profile": PROFILE, "valid": True, "warnings": validation["warnings"],
                       "limitations": list(LIMITATIONS)},
    }
    return {"snapshot": candidate, "receipt": receipt, "changed_record_ids": sorted(changed)}
