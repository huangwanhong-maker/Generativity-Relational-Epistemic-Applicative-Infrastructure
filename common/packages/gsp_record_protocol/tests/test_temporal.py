"""Temporal accounts remain distinct from write order and ordinary incidence."""

from copy import deepcopy

import pytest

from gsp_protocol import ProtocolError, capabilities, prepare_transaction, project_graph, project_spacetime, validate_snapshot
from gsp_protocol import core
from test_protocol import ACTOR, HEAD, TIME, by_id, change_module, create, ident, prepare, relation, snapshot, tx


def bound(number=None, kind="event"):
    return {"kind": kind, **({"event_id": ident(number)} if kind == "event" else {})}


def extent(start=None, end=None, subject=None):
    return {"version": "1", "required": True, "data": {
        "start": start or bound(kind="unbounded"), "end": end or bound(kind="unbounded"),
        "basis": "Boundaries stipulated for this attributed account.",
        **({"subject_record_id": ident(subject)} if subject is not None else {}),
    }}


def event(number, **kwargs):
    return create(number, "Event", modality="realized", **kwargs)


def order(number, before, after, **kwargs):
    incidence = relation(before, after)
    incidence["data"]["predicate"] = "precedes"
    incidence["data"]["participants"][0]["orientation"] = "in"
    incidence["data"]["participants"][1]["orientation"] = "out"
    return create(number, "Relation", modality="realized", modules={
        "gsp.relation": incidence,
        "gsp.event_order": {"version": "1", "required": True,
                            "data": {"before": ident(before), "after": ident(after)}},
    }, **kwargs)


def diamond():
    return prepare([event(2), event(3), event(4), event(5),
                    order(6, 2, 3), order(7, 2, 4), order(8, 3, 5), order(9, 4, 5),
                    create(10, "State", modules={"gsp.temporal_extent": extent(bound(2), bound(5), 11)}),
                    create(11)])["snapshot"]


def presence(value, number):
    return next(item["presence"] for item in value["presence"] if item["record_id"] == ident(number))


def error_code(callback):
    with pytest.raises(ProtocolError) as found:
        callback()
    return found.value.code


def test_earlier_event_can_be_written_later_without_temporal_inference():
    source = prepare([event(2, occurred_at="2035-04-05")])["snapshot"]
    original = deepcopy(source)
    result = prepare_transaction(source, tx([event(8, occurred_at="2035-01-01"), order(9, 8, 2)]),
                                 ACTOR, "2026-09-23T09:00:00Z")["snapshot"]
    assert source == original
    assert by_id(result, 8)["created_at"] > by_id(result, 2)["created_at"]
    projected = project_spacetime(result, [ident(8)])
    ranks = {item["id"]: item["rank"] for item in projected["events"]}
    assert ranks == {ident(2): 1, ident(8): 0}
    assert projected["cut"]["included"] == [ident(8)]
    # Contradicting free text and identifiers never override the explicit account.
    by_id(result, 8)["occurred_at"] = "later date, uncertain"
    by_id(result, 2)["occurred_at"] = "earlier date, uncertain"
    assert {item["id"]: item["rank"] for item in project_spacetime(result)["events"]} == ranks


def test_diamond_cut_is_ancestor_closed_without_collapsing_incomparable_events():
    value = project_spacetime(diamond(), [ident(3)])
    assert value["consistent"]
    assert value["cut"] == {"requested": [ident(3)], "included": [ident(2), ident(3)],
                            "frontier": [ident(3)], "derived": [ident(2)]}
    events = {item["id"]: item for item in value["events"]}
    assert events[ident(3)]["rank"] == events[ident(4)]["rank"] == 1
    assert ident(4) not in value["cut"]["included"]
    assert events[ident(5)]["predecessors"] == [ident(3), ident(4)]
    assert presence(value, 10) == "active"
    assert value["trajectories"] == [{"subject_record_id": ident(11), "record_ids": [ident(10)]}]
    assert presence(value, 11) == "unscoped"
    assert [node["id"] for node in value["topology"]["nodes"]] == [ident(10)]


def test_empty_all_and_explicit_frontier_cuts_preserve_boundary_semantics():
    source = diamond()
    empty = project_spacetime(source, [])
    assert empty["cut"] == {"requested": [], "included": [], "frontier": [], "derived": []}
    assert presence(empty, 10) == "not_started"
    at_start = project_spacetime(source, [ident(2)])
    assert presence(at_start, 10) == "active"
    joined = project_spacetime(source, [ident(3), ident(4)])
    assert joined["cut"]["frontier"] == [ident(3), ident(4)]
    at_end = project_spacetime(source, [ident(5)])
    assert presence(at_end, 10) == "ended"
    all_events = project_spacetime(source)
    assert all_events["cut"]["requested"] is None
    assert all_events["cut"]["included"] == [ident(2), ident(3), ident(4), ident(5)]
    assert all_events["cut"]["derived"] == []
    assert presence(all_events, 10) == "ended"


def test_cycle_retained_with_exact_involved_records_and_no_cut_or_topology():
    source = prepare([event(2), event(3), event(4), order(5, 2, 3), order(6, 3, 2),
                      order(7, 3, 4), create(8, modules={"gsp.temporal_extent": extent()})])["snapshot"]
    assert validate_snapshot(source)["valid"]
    value = project_spacetime(source)
    assert value["consistent"] is False
    assert value["cut"] is None and value["topology"] is None
    assert all(item["rank"] is None for item in value["events"])
    cycle = next(item for item in value["diagnostics"] if item["code"] == "event_order_cycle")
    assert cycle["event_ids"] == [ident(2), ident(3)]
    assert cycle["relation_ids"] == [ident(5), ident(6)]
    assert presence(value, 8) == "indeterminate"
    assert len(value["orders"]) == 3


def test_self_order_is_diagnosed_without_discarding_the_relation():
    source = prepare([event(2), order(3, 2, 2)])["snapshot"]
    value = project_spacetime(source, [])
    assert not value["consistent"]
    assert value["diagnostics"][-1]["event_ids"] == [ident(2)]
    assert value["diagnostics"][-1]["relation_ids"] == [ident(3)]
    assert len(project_graph(source)["edges"]) == 2


def test_withdrawing_an_order_removes_only_its_constraint_from_selected_revision():
    original = prepare([event(2), event(3), order(4, 2, 3), order(5, 3, 2)])["snapshot"]
    current = prepare([{"op": "record.update", "record_id": ident(5), "changes": {"status": "withdrawn"}}], original)["snapshot"]
    current["head"] = "b" * 40
    before_copy, current_copy = deepcopy(original), deepcopy(current)
    assert project_spacetime(original)["head"] == HEAD
    assert not project_spacetime(original)["consistent"]
    value = project_spacetime(current)
    assert value["head"] == "b" * 40 and value["consistent"]
    assert next(item for item in value["orders"] if item["id"] == ident(5))["active"] is False
    assert presence(value, 5) == "withdrawn"
    assert original == before_copy and current == current_copy


@pytest.mark.parametrize("start,end,code", [
    (bound(3), bound(4), "extent_incomparable_bounds"),
    (bound(5), bound(2), "extent_reversed_bounds"),
    (bound(2), bound(2), "extent_same_boundary"),
])
def test_ambiguous_or_reversed_extent_is_preserved_as_indeterminate(start, end, code):
    source = diamond()
    by_id(source, 10)["modules"]["gsp.temporal_extent"] = extent(start, end)
    assert validate_snapshot(source)["valid"]
    value = project_spacetime(source)
    assert presence(value, 10) == "indeterminate"
    assert any(item["code"] == code and item["record_id"] == ident(10) for item in value["diagnostics"])


@pytest.mark.parametrize("start,end", [
    (bound(kind="unknown"), bound(kind="unbounded")),
    (bound(2), bound(kind="unknown")),
    (bound(kind="unknown"), bound(5)),
])
def test_unknown_boundary_never_implies_presence(start, end):
    source = diamond()
    by_id(source, 10)["modules"]["gsp.temporal_extent"] = extent(start, end)
    assert presence(project_spacetime(source, []), 10) == "indeterminate"
    assert presence(project_spacetime(source), 10) == "indeterminate"


def test_explicit_unbounded_scope_and_withdrawal_are_separate_from_unknown():
    source = prepare([create(2, modules={"gsp.temporal_extent": extent()}),
                      create(3, status="withdrawn", modules={"gsp.temporal_extent": extent()})])["snapshot"]
    value = project_spacetime(source, [])
    assert presence(value, 2) == "active"
    assert presence(value, 3) == "withdrawn"
    assert value["trajectories"] == []


def test_induced_topology_retains_partial_relation_node_without_invented_targets():
    source = prepare([create(2, modules={"gsp.temporal_extent": extent()}), create(3),
                      create(4, "Relation", modules={"gsp.relation": relation(2, 3),
                                                      "gsp.temporal_extent": extent()})])["snapshot"]
    value = project_spacetime(source, [])
    assert {node["id"] for node in value["topology"]["nodes"]} == {ident(2), ident(4)}
    assert len(value["topology"]["edges"]) == 1
    edge = value["topology"]["edges"][0]
    assert {edge["source"], edge["target"]} == {ident(2), ident(4)}
    diagnostic = next(item for item in value["diagnostics"] if item["code"] == "partial_relation_at_cut")
    assert diagnostic["participant_ids"] == [ident(1001)]


def test_contested_and_possible_temporal_accounts_are_visible_with_warnings():
    operation = event(2, status="contested")
    operation["record"]["modality"] = "possible"
    source = prepare([operation, event(3), order(4, 2, 3, status="contested")])["snapshot"]
    value = project_spacetime(source)
    assert value["orders"][0]["active"]
    assert value["events"][0]["modality"] == "possible"
    assert {item["code"] for item in value["diagnostics"]} >= {"contested_temporal_account", "non_realized_temporal_account"}


def test_withdrawn_event_does_not_silently_erase_an_active_order():
    source = prepare([event(2, status="withdrawn"), event(3), order(4, 2, 3)])["snapshot"]
    value = project_spacetime(source)
    assert value["orders"][0]["active"]
    assert presence(value, 2) == "withdrawn"
    assert any(item["code"] == "withdrawn_event_in_order" for item in value["diagnostics"])


def test_role_overlap_is_accepted_for_event_references():
    source = prepare([create(2, record_roles=["Entity", "Event"]), event(3), order(4, 2, 3)])["snapshot"]
    assert len(project_spacetime(source)["events"]) == 2


@pytest.mark.parametrize("mutate,code", [
    (lambda m: m["gsp.event_order"]["data"].update(before=ident(99)), "missing_reference"),
    (lambda m: m["gsp.relation"]["data"]["participants"][0].update(orientation="out"), "event_order_incidence"),
    (lambda m: m["gsp.relation"]["data"]["participants"][0].update(reference_scope="record"), "event_order_incidence"),
    (lambda m: m.pop("gsp.relation"), "event_order_relation"),
    (lambda m: m["gsp.event_order"].update(required=False), "temporal_module_required"),
    (lambda m: m["gsp.event_order"]["data"].update(before=ident(2)+"\n"), "validation"),
])
def test_order_structure_rejects_missing_or_ambiguous_references(mutate, code):
    operation = order(4, 2, 3)
    mutate(operation["record"]["modules"])
    assert error_code(lambda: prepare([event(2), event(3), operation])) == code


def test_non_event_record_cannot_be_used_as_temporal_boundary():
    assert error_code(lambda: prepare([create(2), event(3), order(4, 2, 3)])) == "event_role"
    assert error_code(lambda: prepare([create(2), create(3, modules={"gsp.temporal_extent": extent(bound(2))})])) == "event_role"


@pytest.mark.parametrize("mutate,code", [
    (lambda m: m["data"].update(subject_record_id=ident(99)), "missing_reference"),
    (lambda m: m["data"].update(start=bound(99)), "missing_reference"),
    (lambda m: m["data"].update(basis="  "), "temporal_basis"),
    (lambda m: m["data"].update(basis="x" * 2001), "validation"),
    (lambda m: m["data"].update(start={"kind": "unknown", "event_id": ident(2)}), "validation"),
    (lambda m: m["data"].update(end={"kind": "event"}), "validation"),
    (lambda m: m.update(required=False), "temporal_module_required"),
])
def test_extent_schema_and_references_are_checked(mutate, code):
    module = extent()
    mutate(module)
    assert error_code(lambda: prepare([create(2, modules={"gsp.temporal_extent": module})])) == code


def test_required_extension_envelopes_protect_older_readers(monkeypatch):
    module = extent()
    module.pop("required")
    source = prepare([create(2, modules={"gsp.temporal_extent": module})])["snapshot"]
    assert by_id(source, 2)["modules"]["gsp.temporal_extent"]["required"] is True
    assert capabilities()["modules"]["gsp.temporal_extent"]["required_default"] is True
    monkeypatch.delitem(core.BUILTINS, "gsp.temporal_extent")
    assert any(item["code"] == "unsupported_required_module" for item in validate_snapshot(source)["warnings"])
    assert error_code(lambda: prepare([create(3)], source)) == "unsupported_required_module"


def test_missing_required_flag_in_retained_snapshot_is_rejected():
    source = prepare([create(2, modules={"gsp.temporal_extent": extent()})])["snapshot"]
    by_id(source, 2)["modules"]["gsp.temporal_extent"].pop("required")
    assert error_code(lambda: validate_snapshot(source)) == "temporal_module_required"


@pytest.mark.parametrize("required", [True, False])
def test_unsupported_order_version_blocks_projection_instead_of_omitting_constraint(required):
    source = prepare([event(2), event(3), order(4, 2, 3),
                      create(5, modules={"gsp.temporal_extent": extent()})])["snapshot"]
    by_id(source, 4)["modules"]["gsp.event_order"].update(version="future", required=required)
    value = project_spacetime(source, [ident(2)])
    assert value["consistent"] is False
    assert value["cut"] is None and value["topology"] is None
    assert all(item["rank"] is None for item in value["events"])
    assert presence(value, 5) == "indeterminate"
    assert any(item["code"] == "unsupported_event_order" and item["relation_ids"] == [ident(4)] for item in value["diagnostics"])


def test_unknown_extent_is_indeterminate_and_unrelated_optional_module_keeps_cut():
    source = prepare([event(2), create(3, modules={"gsp.temporal_extent": extent()})])["snapshot"]
    by_id(source, 3)["modules"]["gsp.temporal_extent"]["version"] = "future"
    by_id(source, 2)["modules"]["other.optional"] = {"version": "1", "required": False, "data": {"opaque": True}}
    original = deepcopy(source)
    value = project_spacetime(source)
    assert value["consistent"] and value["cut"]["included"] == [ident(2)]
    assert presence(value, 3) == "indeterminate"
    assert value["topology"]["nodes"] == []
    assert any(item["code"] == "unsupported_temporal_extent" for item in value["diagnostics"])
    assert source == original


@pytest.mark.parametrize("after", ["not-a-list", [ident(11)], [ident(99)], [ident(2), ident(2)], [None], [ident(2)] * 1001])
def test_cut_accepts_only_bounded_distinct_snapshot_event_ids(after):
    assert error_code(lambda: project_spacetime(diamond(), after)) == "temporal_cut"


def test_ordinary_incidence_cycles_do_not_become_temporal_cycles():
    source = prepare([create(2, "Relation", modules={"gsp.relation": relation(3)}),
                      create(3, "Relation", modules={"gsp.relation": relation(2)})])["snapshot"]
    value = project_spacetime(source)
    assert value["consistent"] and value["events"] == [] and value["orders"] == []
    assert value["cut"]["included"] == []
    assert not any(item["code"] == "event_order_cycle" for item in value["diagnostics"])


def test_removing_event_role_or_relation_incidence_requires_consistent_atomic_change():
    source = prepare([event(2), event(3), order(4, 2, 3)])["snapshot"]
    assert error_code(lambda: prepare([{"op": "record.update", "record_id": ident(2),
                                       "changes": {"record_type": "Entity", "record_roles": ["Entity"]}}], source)) == "event_role"
    assert error_code(lambda: prepare([{"op": "module.remove", "record_id": ident(4), "module_id": "gsp.relation"}], source)) == "event_order_relation"


def test_parallel_order_accounts_keep_their_identifiers_without_duplicate_indegree():
    source = prepare([event(2), event(3), order(4, 2, 3), order(5, 2, 3)])["snapshot"]
    value = project_spacetime(source)
    assert value["consistent"] and len(value["orders"]) == 2
    assert value["events"][1]["predecessors"] == [ident(2)]
    assert value["events"][1]["rank"] == 1


def test_projection_is_independent_of_record_serialization_order():
    source = diamond()
    reordered = deepcopy(source)
    reordered["records"].reverse()
    assert project_spacetime(source, [ident(3)]) == project_spacetime(reordered, [ident(3)])


def test_project_limit_chain_remains_iterative_and_cut_closure_is_complete():
    operations = [event(number) for number in range(2, 502)]
    operations += [order(number + 1000, number, number + 1) for number in range(2, 501)]
    operations += [create(2000, modules={"gsp.temporal_extent": extent(bound(2), bound(501))})]
    source = snapshot()
    for offset in range(0, len(operations), 100):
        source = prepare(operations[offset:offset + 100], source)["snapshot"]
    value = project_spacetime(source, [ident(500)])
    assert len(source["records"]) == 1000
    assert value["consistent"] and len(value["events"]) == 500
    assert len(value["cut"]["included"]) == 499
    assert len(value["cut"]["derived"]) == 498
    assert value["cut"]["frontier"] == [ident(500)]
    assert next(item["rank"] for item in value["events"] if item["id"] == ident(501)) == 499
    assert presence(value, 2000) == "active"
