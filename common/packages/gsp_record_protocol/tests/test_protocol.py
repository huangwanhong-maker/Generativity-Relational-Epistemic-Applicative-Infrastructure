from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from gsp_protocol import (
    PROFILE, PROTOCOL_VERSION, SCHEMA_VERSION, ProtocolError, capabilities,
    normalize_snapshot, prepare_transaction, project_graph, request_digest,
    validate_snapshot, validate_transaction,
)


def ident(number):
    return str(UUID(int=number))


ACTOR = {"id": ident(900), "display_name": "Recorder"}
TIME = "2026-09-22T08:00:00Z"
HEAD = "a" * 40
FIXTURES = Path(__file__).parent / "fixtures"


def snapshot():
    return {"project": {"id": ident(1), "name": "Bounded inquiry", "schema_version": SCHEMA_VERSION},
            "records": [], "head": HEAD}


def record(number, role="Entity", **extra):
    return {"id": ident(number), "title": f"Account {number}", "content": "Attributed account with an explicitly bounded purpose.",
            "record_type": role, "epistemic_mode": "reported", **extra}


def create(number, role="Entity", **extra):
    return {"op": "record.create", "record": record(number, role, **extra)}


def tx(operations, number=800, **extra):
    return {"protocol_version": PROTOCOL_VERSION, "transaction_id": ident(number), "expected_head": HEAD,
            "reason": "Retain the account and its stated relationships.", "change_categories": ["description"],
            "operations": operations, **extra}


def prepare(operations, source=None, parts=None):
    return prepare_transaction(source or snapshot(), tx(operations), ACTOR, TIME, parts)


def relation(*numbers, complete=True):
    return {"version": "1", "required": False,
            "data": {"predicate": "agreement participation", "participants_complete": complete,
                     "participant_limitations": "Other participant is not identified." if not complete else "",
                     "participants": [{"id": ident(1000 + i), "record_id": ident(number),
                                       "role": f"party {i + 1}", "reference_scope": "represented_target",
                                       "orientation": "undirected"} for i, number in enumerate(numbers)]}}


def change_module(number, name, data):
    return {"op": "module.set", "record_id": ident(number), "module_id": name, "module": data}


def file_operation(kind="file.attach", number=2, file_number=200, part="material", data=b"retained bytes"):
    return {"op": kind, "record_id": ident(number), "file_id": ident(file_number), "part": part,
            "filename": "source.txt", "media_type": "text/plain", "sha256": hashlib.sha256(data).hexdigest(),
            "byte_length": len(data)}


def parts(*operations):
    return {operation["part"]: {key: operation[key] for key in ["sha256", "byte_length"]} for operation in operations}


def by_id(value, number):
    return next(item for item in value["records"] if item["id"] == ident(number))


def assert_error(code, callback):
    with pytest.raises(ProtocolError) as found:
        callback()
    assert found.value.code == code


def test_atomic_same_batch_forward_higher_order_and_cyclic_incidence():
    source = snapshot()
    original = deepcopy(source)
    result = prepare([
        create(4, "Relation", modules={"gsp.relation": relation(3, 2)}),
        create(3, "Relation", record_roles=["Relation", "Entity"], modules={"gsp.relation": relation(4, 2)}),
        create(2),
    ], source)
    assert source == original
    assert result["snapshot"]["head"] == HEAD
    graph = project_graph(result["snapshot"])
    assert len(graph["nodes"]) == 3 and len(graph["edges"]) == 4
    assert {edge["target"] for edge in graph["edges"]} == {ident(2), ident(3), ident(4)}
    assert by_id(result["snapshot"], 3)["record_roles"] == ["Relation", "Entity"]
    assert result["changed_record_ids"] == [ident(2), ident(3), ident(4)]
    assert "factual truth" in result["receipt"]["validation"]["limitations"][0]


def test_nary_parallel_unary_self_relations_keep_their_tokens_and_scopes():
    unary = relation(5)
    unary["data"]["participants"][0]["reference_scope"] = "record"
    source = prepare([create(2), create(3), create(4),
                      create(5, "Relation", modules={"gsp.relation": unary}),
                      create(6, "Relation", modules={"gsp.relation": relation(2, 3, 4)}),
                      create(7, "Relation", modules={"gsp.relation": relation(2, 3, 4)})])["snapshot"]
    graph = project_graph(source)
    assert len(graph["edges"]) == 7
    self_edge = next(item for item in graph["edges"] if item["relation_id"] == ident(5))
    assert self_edge["source"] == self_edge["target"] == ident(5)
    assert self_edge["reference_scope"] == "record"
    assert sum(node["structured_relation"] for node in graph["nodes"]) == 3


def test_repeated_participant_record_is_allowed_but_incidence_id_is_unique():
    value = relation(2, 2)
    assert validate_snapshot(prepare([create(2), create(3, "Relation", modules={"gsp.relation": value})])["snapshot"])["valid"]
    value["data"]["participants"][1]["id"] = value["data"]["participants"][0]["id"]
    assert_error("duplicate_incidence", lambda: prepare([create(2), create(3, "Relation", modules={"gsp.relation": value})]))


def test_incidence_orientation_and_neutral_references_stay_distinct():
    value = relation(2, 3)
    value["data"]["participants"][0]["orientation"] = "in"
    value["data"]["participants"][1]["orientation"] = "out"
    graph = project_graph(prepare([create(2, related_records=[ident(3)]), create(3),
                                  create(4, "Relation", modules={"gsp.relation": value})])["snapshot"])
    edges = graph["edges"]
    assert any(e["kind"] == "reference" and e["relation_id"] is None for e in edges)
    assert any(e["source"] == ident(2) and e["target"] == ident(4) and e["orientation"] == "in" for e in edges)
    assert any(e["source"] == ident(4) and e["target"] == ident(3) and e["orientation"] == "out" for e in edges)


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r["data"].update(participants=[]), "validation"),
    (lambda r: r["data"].update(participants_complete=False, participant_limitations=""), "participant_limitations"),
    (lambda r: r["data"]["participants"][0].update(record_id=ident(999)), "missing_reference"),
    (lambda r: r["data"]["participants"][0].update(reference_scope="real"), "validation"),
])
def test_invalid_relation_does_not_mutate_original(mutation, code):
    source = snapshot()
    original = deepcopy(source)
    value = relation(2)
    mutation(value)
    assert_error(code, lambda: prepare([create(2), create(3, "Relation", modules={"gsp.relation": value})], source))
    assert source == original


def test_incomplete_incidence_is_supported_without_invented_participant():
    source = prepare([create(2), create(3, "Relation", modules={"gsp.relation": relation(2, complete=False)})])["snapshot"]
    assert len(project_graph(source)["nodes"]) == 2
    assert not by_id(source, 3)["modules"]["gsp.relation"]["data"]["participants_complete"]


def test_primary_role_and_relation_role_are_independently_checked():
    assert_error("primary_role", lambda: prepare([create(2, record_roles=["Process"])]))
    assert_error("relation_role", lambda: prepare([create(2, modules={"gsp.relation": relation(2)})]))


def test_modality_epistemic_basis_and_dispute_can_coexist():
    result = prepare([create(2, "Event", epistemic_mode="retrospective", modality="realized", status="contested")])
    value = by_id(result["snapshot"], 2)
    assert (value["epistemic_mode"], value["modality"], value["status"]) == ("retrospective", "realized", "contested")


def test_unknown_optional_module_survives_unrelated_edit_exactly():
    source = prepare([create(2)])["snapshot"]
    opaque = {"version": "2030", "data": {"claims": [{"domain": "academia", "x": 4}], "literal": " a "}}
    source["records"][0]["modules"]["academia.future"] = opaque
    result = prepare([{"op": "record.update", "record_id": ident(2), "changes": {"title": "Revised title"}}], source)
    assert result["snapshot"]["records"][0]["modules"]["academia.future"] == opaque
    assert result["receipt"]["validation"]["warnings"][0]["code"] == "unsupported_module"
    for operation in [change_module(2, "academia.future", opaque), {"op": "module.remove", "record_id": ident(2), "module_id": "academia.future"}]:
        assert_error("unsupported_module", lambda: prepare([operation], source))


def test_unknown_required_module_blocks_mutation_project_wide_but_reads_work():
    source = prepare([create(2), create(3)])["snapshot"]
    source["records"][0]["modules"]["academia.required"] = {"version": "1", "required": True, "data": {}}
    assert validate_snapshot(source)["valid"]
    assert len(project_graph(source)["nodes"]) == 2
    assert_error("unsupported_required_module", lambda: prepare([{"op": "record.update", "record_id": ident(3), "changes": {"title": "Other record"}}], source))


def test_unknown_declared_profile_is_preserved_for_read_and_blocks_mutation():
    source = prepare([create(2)])["snapshot"]
    source["project"]["profile"] = "academia.required-review/7"
    original = deepcopy(source)
    report = validate_snapshot(source)
    assert report["valid"] and report["declared_profile"] == "academia.required-review/7"
    assert any(warning["code"] == "unsupported_profile" for warning in report["warnings"])
    assert any(warning["code"] == "unsupported_profile" for warning in project_graph(source)["warnings"])
    assert normalize_snapshot(source)["project"]["profile"] == "academia.required-review/7"
    assert_error("unsupported_profile", lambda: prepare([{"op": "record.update", "record_id": ident(2), "changes": {"title": "Changed"}}], source))
    assert source == original


def test_legacy_unknown_declared_profile_is_not_silently_migrated():
    source = json.loads((FIXTURES / "legacy_snapshot.json").read_text())
    source["project"]["profile"] = "academia.legacy/1"
    assert_error("unsupported_profile", lambda: prepare_transaction(source, tx([{"op": "project.migrate"}], change_categories=["migration"]), ACTOR, TIME))


def test_unsupported_builtin_version_is_preserved_as_opaque():
    source = prepare([create(2)])["snapshot"]
    module = {"version": "2", "required": False, "data": {"future": "notes"}}
    source["records"][0]["modules"]["gsp.notes"] = module
    result = prepare([{"op": "record.update", "record_id": ident(2), "changes": {"status": "contested"}}], source)
    assert result["snapshot"]["records"][0]["modules"]["gsp.notes"] == module


def test_legacy_read_and_explicit_migration_preserve_old_meaning_and_input():
    source = json.loads((FIXTURES / "legacy_snapshot.json").read_text())
    original = deepcopy(source)
    adapted = normalize_snapshot(source)
    assert adapted["legacy"] and adapted["read_adaptation"]["applied"]
    assert adapted["project"]["schema_version"] == "gsp-workspace/0.1"
    assert "record_roles" not in source["records"][0]
    assert_error("migration_required", lambda: prepare([{"op": "record.update", "record_id": ident(2), "changes": {"title": "Changed"}}], source))
    migrated = prepare_transaction(source, tx([{"op": "project.migrate"}], change_categories=["migration"]), ACTOR, TIME)
    assert source == original
    graph = project_graph(migrated["snapshot"])
    assert len(graph["edges"]) == 1 and graph["edges"][0]["kind"] == "reference"
    assert all(not n["structured_relation"] for n in graph["nodes"])
    assert by_id(migrated["snapshot"], 3)["record_type"] == "Relation"
    assert by_id(migrated["snapshot"], 3)["updated_at"] == by_id(source, 3)["updated_at"]
    assert migrated["snapshot"]["project"]["migration"]["source_head"] == HEAD
    assert any(w["code"] == "unstructured_relation" for w in graph["warnings"])


@pytest.mark.parametrize("operations,categories", [
    ([{"op": "project.migrate"}, create(2)], ["migration"]),
    ([{"op": "project.migrate"}], ["description"]),
    ([create(2)], ["migration"]),
])
def test_migration_must_be_sole_explicit_operation(operations, categories):
    assert_error("migration_scope", lambda: validate_transaction(tx(operations, change_categories=categories)))


def test_mutation_ambiguity_is_rejected_instead_of_last_write_wins():
    notes = {"version": "1", "data": {"text": "Notes"}}
    for operations in [
        [create(2), create(2)],
        [create(2), {"op": "record.update", "record_id": ident(2), "changes": {"title": "Changed"}}],
        [create(2), change_module(2, "gsp.notes", notes), change_module(2, "gsp.notes", notes)],
        [change_module(2, "gsp.notes", notes), create(2, modules={"gsp.notes": notes})],
    ]:
        assert_error("duplicate_mutation", lambda: prepare(operations))


def test_create_then_distinct_module_is_valid_and_server_attribution_is_required():
    result = prepare([change_module(2, "gsp.notes", {"version": "1", "data": {"text": "A retained note"}}), create(2)])
    assert by_id(result["snapshot"], 2)["modules"]["gsp.notes"]["required"] is False
    assert by_id(result["snapshot"], 2)["recorded_by"] == ACTOR
    assert_error("validation", lambda: prepare([create(2, recorded_by={"id": ident(999), "display_name": "Injected"})]))
    assert_error("validation", lambda: prepare([{"op": "record.update", "record_id": ident(2), "changes": {"modules": {}}}], result["snapshot"]))


def test_file_attach_replace_detach_reconstructs_independent_snapshots():
    first = file_operation(data=b"first")
    source = prepare([create(2), first], parts=parts(first))["snapshot"]
    replacement = file_operation("file.replace", data=b"second version")
    revised = prepare([replacement], source, parts(replacement))["snapshot"]
    detached = prepare([{"op": "file.detach", "record_id": ident(2), "file_id": ident(200)}], revised)["snapshot"]
    descriptor = lambda value: by_id(value, 2)["modules"]["gsp.files"]["data"]["items"]
    assert descriptor(source)[0]["sha256"] == first["sha256"]
    assert descriptor(revised)[0]["sha256"] == replacement["sha256"]
    assert descriptor(source)[0]["file_id"] == descriptor(revised)[0]["file_id"]
    assert descriptor(detached) == []
    assert descriptor(source)[0]["uploaded_by"] == ACTOR
    assert_error("files_linked", lambda: prepare([{"op": "module.remove", "record_id": ident(2), "module_id": "gsp.files"}], source))
    removed = prepare([{"op": "module.remove", "record_id": ident(2), "module_id": "gsp.files"}], detached)["snapshot"]
    assert "gsp.files" not in by_id(removed, 2)["modules"]


def test_forged_file_descriptor_is_rejected_and_empty_module_can_be_enabled():
    first = file_operation()
    source = prepare([create(2), first], parts=parts(first))["snapshot"]
    descriptor = by_id(source, 2)["modules"]["gsp.files"]
    assert_error("file_operation_required", lambda: prepare([create(3, modules={"gsp.files": descriptor})]))
    assert_error("file_operation_required", lambda: prepare([change_module(2, "gsp.files", {"version": "1", "data": {"items": []}})], source))
    result = prepare([create(2), change_module(2, "gsp.files", {"version": "1", "data": {"items": []}})])
    assert by_id(result["snapshot"], 2)["modules"]["gsp.files"]["data"]["items"] == []


@pytest.mark.parametrize("change,code", [
    (lambda p: p.update(extra={"sha256": "b" * 64, "byte_length": 2}), "binary_parts"),
    (lambda p: p.clear(), "binary_parts"),
    (lambda p: p["material"].update(sha256="b" * 64), "binary_mismatch"),
    (lambda p: p["material"].update(byte_length=True), "binary_metadata"),
    (lambda p: p["material"].update(path="secret/server/path"), "binary_metadata"),
])
def test_verified_file_metadata_is_exact_and_content_bound(change, code):
    operation = file_operation()
    meta = parts(operation)
    change(meta)
    assert_error(code, lambda: prepare([create(2), operation], parts=meta))


def test_duplicate_file_mutation_and_reused_binary_part_are_refused():
    operation = file_operation()
    duplicate = {**operation, "part": "second"}
    assert_error("duplicate_mutation", lambda: prepare([create(2), operation, duplicate], parts=parts(operation, duplicate)))
    reused = {**operation, "file_id": ident(201)}
    assert_error("duplicate_part", lambda: prepare([create(2), operation, reused], parts=parts(operation)))


@pytest.mark.parametrize("filename", ["../path.txt", "C:\\path.txt", "bad\nheader.txt", ".", ".."]) 
def test_filenames_are_display_names_not_paths_or_header_injection(filename):
    operation = file_operation()
    operation["filename"] = filename
    assert_error("filename", lambda: prepare([create(2), operation], parts=parts(operation)))


def test_binary_budget_has_per_file_total_and_part_limits():
    big = file_operation()
    big["byte_length"] = 10 * 1024 * 1024 + 1
    assert_error("validation", lambda: prepare([create(2), big], parts=parts(big)))
    operations = [file_operation(file_number=200+i, part=f"material{i}") for i in range(3)]
    for operation in operations:
        operation["byte_length"] = 8 * 1024 * 1024
    assert_error("binary_limit", lambda: prepare([create(2), *operations], parts=parts(*operations)))
    operations = [file_operation(file_number=200+i, part=f"material{i}") for i in range(9)]
    assert_error("binary_limit", lambda: prepare([create(2), *operations], parts=parts(*operations)))


def test_integral_float_file_length_is_not_an_integer_wire_value():
    operation = file_operation()
    operation["byte_length"] = float(operation["byte_length"])
    meta = {operation["part"]: {"sha256": operation["sha256"], "byte_length": int(operation["byte_length"])}}
    assert_error("binary_metadata", lambda: prepare([create(2), operation], parts=meta))


def test_jcs_digest_is_stable_over_member_order_and_changes_with_payload():
    request = tx([create(2)])
    reordered = dict(reversed(list(request.items())))
    reordered["operations"] = [{"record": dict(reversed(list(request["operations"][0]["record"].items()))), "op": "record.create"}]
    assert request_digest(request) == request_digest(reordered)
    changed = deepcopy(request)
    changed["reason"] += " Changed."
    assert request_digest(request) != request_digest(changed)
    assert len(request_digest(request)) == 64


def test_receipt_digest_and_actor_are_separate_from_jcs_input():
    request = tx([create(2)])
    result = prepare_transaction(snapshot(), request, ACTOR, TIME)
    later = prepare_transaction(snapshot(), request, {"id": ident(901), "display_name": "Other recorder"}, "2026-09-23T09:00:00Z")
    assert result["receipt"]["request_digest"] == later["receipt"]["request_digest"]
    assert result["receipt"]["actor"] != later["receipt"]["actor"]
    assert result["receipt"]["recorded_at"] != later["receipt"]["recorded_at"]


def test_stale_snapshot_is_conflict_and_final_invalid_reference_is_atomic():
    source = prepare([create(2)])["snapshot"]
    original = deepcopy(source)
    request = tx([create(3)], expected_head="b" * 40)
    assert_error("conflict", lambda: prepare_transaction(source, request, ACTOR, TIME))
    assert_error("missing_reference", lambda: prepare([create(3), create(4, related_records=[ident(999)])], source))
    assert source == original


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800", 2**53, {"tuple": (1, 2)}])
def test_noncanonical_json_is_refused(bad):
    request = tx([create(2)])
    request["unexpected"] = bad
    with pytest.raises(ProtocolError):
        validate_transaction(request)


@pytest.mark.parametrize("field", ["transaction_id", "expected_head", "record_id", "part", "sha256"])
def test_structural_identifiers_do_not_accept_trailing_line_breaks(field):
    operation = file_operation()
    request = tx([create(2), operation])
    if field in {"transaction_id", "expected_head"}:
        request[field] += "\n"
    elif field == "record_id":
        request["operations"][0]["record"]["id"] += "\n"
    else:
        operation[field] += "\n"
    assert_error("validation", lambda: validate_transaction(request))


def test_historical_projection_labels_come_from_that_snapshot():
    first = prepare([create(2), create(3, "Relation", modules={"gsp.relation": relation(2)})])["snapshot"]
    later = prepare([{"op": "record.update", "record_id": ident(2), "changes": {"title": "Later interpretation"}}], first)["snapshot"]
    assert next(n for n in project_graph(first)["nodes"] if n["id"] == ident(2))["label"] == "Account 2"
    assert next(n for n in project_graph(later)["nodes"] if n["id"] == ident(2))["label"] == "Later interpretation"


def test_static_fixture_and_cli_agree_and_duplicate_json_is_rejected(tmp_path):
    valid = subprocess.run([sys.executable, "-m", "gsp_protocol", "validate-snapshot", str(FIXTURES / "graph_snapshot.json")], capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["valid"]
    invalid_path = tmp_path / "duplicate.json"
    invalid_path.write_text('{"project":{},"project":{}}')
    invalid = subprocess.run([sys.executable, "-m", "gsp_protocol", "validate-snapshot", str(invalid_path)], capture_output=True, text=True)
    assert invalid.returncode == 1 and "Duplicate JSON member" in invalid.stderr


def test_schema_is_draft_2020_12_and_capability_mutation_cannot_change_registry():
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    schema = json.loads(files("gsp_protocol").joinpath("schemas/protocol.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    information = capabilities()
    information["record_roles"].clear()
    assert "Relation" in capabilities()["record_roles"]
    assert information["profile"] == PROFILE
