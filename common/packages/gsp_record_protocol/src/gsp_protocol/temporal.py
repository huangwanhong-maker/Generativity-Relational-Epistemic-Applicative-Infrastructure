"""Event-order projections of retained accounts, independent of recording order.

This module treats Event-role records as operational boundary markers. It does
not infer physical simultaneity, durations, causality, coordinates or target
identity. A cut is an ancestor-closed selection in an explicitly asserted order.
"""

from __future__ import annotations

from copy import deepcopy
import heapq

from .core import MAX_RECORDS, PROTOCOL_VERSION, ProtocolError, _module_known


PROJECTION = "gsp.spacetime/1"
LIMITATIONS = [
    "Event order expresses retained accounts, not independently established reality or causality.",
    "Recording timestamps, Git order, identifiers and free-text occurred_at do not determine event order.",
    "Ranks are layout aids only. Incomparable events are not thereby simultaneous; no total timeline is inferred.",
    "Cuts are ancestor-closed event selections, not physical instants or measured durations.",
    "Event records serve as operational boundaries; spatial coordinates and event duration are not modeled by this extension.",
    "Extent starts are inclusive and ends exclusive. Unbounded means within the stated account scope, not perpetual existence.",
    "Unknown bounds and missing extents do not establish presence. Subject grouping does not establish represented-target identity.",
    "Contested and non-realized accounts remain visible in the selected interpretation; withdrawal is not deletion from history.",
]


def _data(record: dict, name: str) -> dict | None:
    module = record["modules"].get(name, {})
    return module["data"] if _module_known(name, module) else None


def _walk(seeds, adjacency: dict[str, set[str]]) -> set[str]:
    reached, pending = set(seeds), list(seeds)
    while pending:
        for other in adjacency[pending.pop()]:
            if other not in reached:
                reached.add(other)
                pending.append(other)
    return reached


def _cycles(successors: dict, predecessors: dict, orders: list) -> list[dict]:
    """Iterative strongly connected components avoid recursion on long orders."""
    visited, finished = set(), []
    for seed in sorted(successors):
        pending = [(seed, False)]
        while pending:
            current, finish = pending.pop()
            if finish:
                finished.append(current)
            elif current not in visited:
                visited.add(current)
                pending.append((current, True))
                pending.extend((other, False) for other in sorted(successors[current], reverse=True)
                               if other not in visited)
    visited, result = set(), []
    for seed in reversed(finished):
        if seed in visited:
            continue
        component, pending = set(), [seed]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            pending.extend(predecessors[current] - visited)
        if len(component) > 1 or seed in successors[seed]:
            result.append({
                "code": "event_order_cycle",
                "message": "These asserted event orders form a cycle; a consistent cut cannot be projected until the account is revised.",
                "event_ids": sorted(component),
                "relation_ids": sorted(order["id"] for order in orders if order["active"]
                                       and order["before"] in component and order["after"] in component),
            })
    return sorted(result, key=lambda item: item["event_ids"])


def _order_model(records: list[dict]) -> dict:
    events = {record["id"]: record for record in records if "Event" in record["record_roles"]}
    predecessors = {identifier: set() for identifier in events}
    successors = {identifier: set() for identifier in events}
    orders = []
    for record in sorted(records, key=lambda item: item["id"]):
        data = _data(record, "gsp.event_order")
        if data is None:
            continue
        order = {"id": record["id"], "before": data["before"], "after": data["after"],
                 "status": record["status"], "active": record["status"] != "withdrawn"}
        orders.append(order)
        if order["active"]:
            successors[order["before"]].add(order["after"])
            predecessors[order["after"]].add(order["before"])
    cycles = _cycles(successors, predecessors, orders)
    ranks = {identifier: None for identifier in events}
    if not cycles:
        incoming = {identifier: len(previous) for identifier, previous in predecessors.items()}
        ready = [identifier for identifier, count in incoming.items() if count == 0]
        heapq.heapify(ready)
        while ready:
            current = heapq.heappop(ready)
            ranks[current] = max((ranks[previous] + 1 for previous in predecessors[current]), default=0)
            for following in successors[current]:
                incoming[following] -= 1
                if incoming[following] == 0:
                    heapq.heappush(ready, following)
    return {"events": events, "orders": orders, "predecessors": predecessors,
            "successors": successors, "ranks": ranks, "cycles": cycles}


def validate_temporal_semantics(records: list[dict], warnings: list[dict]) -> None:
    """Check cross-record references after the generic module schemas pass.

    Contradictory asserted order is retained and diagnosed, rather than erased or
    rejected as an invalid archival record. Structural ambiguity is rejected.
    """
    by_id = {record["id"]: record for record in records}

    def event_reference(identifier: str, record_id: str):
        if identifier not in by_id:
            raise ProtocolError("missing_reference", "A temporal boundary refers to a record absent from this snapshot.", {record_id: identifier})
        if "Event" not in by_id[identifier]["record_roles"]:
            raise ProtocolError("event_role", "Temporal order and event boundaries require records with the Event role.", {record_id: identifier})

    for record in records:
        order, extent = _data(record, "gsp.event_order"), _data(record, "gsp.temporal_extent")
        if order is not None:
            event_reference(order["before"], record["id"])
            event_reference(order["after"], record["id"])
            relation = _data(record, "gsp.relation")
            if "Relation" not in record["record_roles"] or relation is None:
                raise ProtocolError("event_order_relation", "An event-order account requires the Relation role and gsp.relation version 1.")
            expected = sorted([(order["before"], "in", "represented_target"),
                               (order["after"], "out", "represented_target")])
            actual = sorted((item["record_id"], item["orientation"], item["reference_scope"])
                            for item in relation["participants"])
            if actual != expected:
                raise ProtocolError("event_order_incidence", "An event-order account requires exactly two matching represented-target incidences: before/in and after/out.")
        if extent is not None:
            if not extent["basis"].strip():
                raise ProtocolError("temporal_basis", "A temporal extent requires a stated basis.")
            for bound in (extent["start"], extent["end"]):
                if bound["kind"] == "event":
                    event_reference(bound["event_id"], record["id"])
            if "subject_record_id" in extent and extent["subject_record_id"] not in by_id:
                raise ProtocolError("missing_reference", "The claimed trajectory subject is absent from this snapshot.")
        if order is not None or extent is not None or "Event" in record["record_roles"]:
            if record["status"] == "contested":
                warnings.append({"code": "contested_temporal_account", "record_id": record["id"],
                                 "message": "This temporal account is contested and remains visible in the selected interpretation."})
            if record["modality"] != "realized":
                warnings.append({"code": "non_realized_temporal_account", "record_id": record["id"],
                                 "message": "This temporal account is not marked realized; its projection is not evidence of actual occurrence."})
    model = _order_model(records)
    warnings.extend(model["cycles"])
    for identifier, record in model["events"].items():
        if record["status"] == "withdrawn" and (model["predecessors"][identifier] or model["successors"][identifier]):
            warnings.append({"code": "withdrawn_event_in_order", "record_id": identifier,
                             "message": "An active order still refers to this withdrawn Event account; the explicit order is retained for review."})


def _bound_diagnostic(record_id: str, extent: dict, model: dict) -> dict | None:
    start, end = extent["start"], extent["end"]
    if start["kind"] != "event" or end["kind"] != "event" or model["cycles"]:
        return None
    before, after = start["event_id"], end["event_id"]
    code = None
    if before == after:
        code = "extent_same_boundary"
    elif after not in _walk([before], model["successors"]):
        code = "extent_reversed_bounds" if before in _walk([after], model["successors"]) else "extent_incomparable_bounds"
    if code:
        return {"code": code, "record_id": record_id, "event_ids": [before, after],
                "message": "The start is not established to strictly precede the end; this account's temporal presence is indeterminate."}
    return None


def _presence(record: dict, extent: dict | None, included: set[str] | None, invalid: bool) -> str:
    if record["status"] == "withdrawn":
        return "withdrawn"
    if extent is None:
        return "unscoped"
    if included is None or invalid:
        return "indeterminate"
    start, end = extent["start"], extent["end"]
    # A single unknown boundary prevents a complete presence determination.
    if "unknown" in {start["kind"], end["kind"]}:
        return "indeterminate"
    if start["kind"] == "event" and start["event_id"] not in included:
        return "not_started"
    if end["kind"] == "event" and end["event_id"] in included:
        return "ended"
    return "active"


def project_spacetime(snapshot: dict, after: list[str] | None = None) -> dict:
    """Return a pure event-order, trajectory and induced-topology projection.

    ``None`` selects all events. ``[]`` selects the empty cut. Explicit event IDs
    request their ancestor closure, which is returned separately from the request.
    Cyclic order retains its diagnostic graph but has no cut or topology projection.
    """
    from .core import _project_graph, normalize_snapshot, validate_snapshot

    report = validate_snapshot(snapshot)
    adapted = normalize_snapshot(snapshot)
    records = sorted(adapted["records"], key=lambda item: item["id"])
    model = _order_model(records)
    if after is not None:
        if not isinstance(after, list) or len(after) > MAX_RECORDS \
                or any(not isinstance(identifier, str) or identifier not in model["events"] for identifier in after):
            raise ProtocolError("temporal_cut", "A cut requires at most 1000 Event record identifiers from the selected snapshot.")
        if len(set(after)) != len(after):
            raise ProtocolError("temporal_cut", "Cut event identifiers must be distinct.")
    diagnostics = deepcopy(report["warnings"])
    unsupported_orders = [record["id"] for record in records if "gsp.event_order" in record["modules"]
                          and _data(record, "gsp.event_order") is None]
    blocked = bool(model["cycles"] or unsupported_orders)
    if unsupported_orders:
        model["ranks"] = {identifier: None for identifier in model["events"]}
        diagnostics.append({"code": "unsupported_event_order", "relation_ids": unsupported_orders,
                            "message": "Some retained event-order modules have unsupported versions. Their constraints cannot be interpreted, so no complete order, cut or topology is projected."})
    included, cut = None, None
    if not blocked:
        requested = None if after is None else sorted(after)
        included = set(model["events"]) if after is None else _walk(after, model["predecessors"])
        cut = {"requested": requested, "included": sorted(included),
               "frontier": sorted(identifier for identifier in included if not (model["successors"][identifier] & included)),
               "derived": sorted(included - set(after)) if after is not None else []}
    extents, presence, trajectories = [], [], {}
    for record in records:
        extent = _data(record, "gsp.temporal_extent")
        diagnostic = _bound_diagnostic(record["id"], extent, model) if extent is not None and not blocked else None
        if diagnostic:
            diagnostics.append(diagnostic)
        state = _presence(record, extent, included, diagnostic is not None)
        if extent is None and "gsp.temporal_extent" in record["modules"]:
            state = "withdrawn" if record["status"] == "withdrawn" else "indeterminate"
            diagnostics.append({"code": "unsupported_temporal_extent", "record_id": record["id"],
                                "message": "This retained temporal extent has an unsupported version; its temporal presence cannot be determined."})
        presence.append({"record_id": record["id"], "presence": state})
        if extent is not None:
            subject = extent.get("subject_record_id")
            extents.append({"record_id": record["id"], "subject_record_id": subject,
                            "start": deepcopy(extent["start"]), "end": deepcopy(extent["end"]),
                            "basis": extent["basis"], "presence": state})
            if subject is not None:
                trajectories.setdefault(subject, []).append(record["id"])
    topology = None
    if included is not None:
        graph = _project_graph(adapted, report)
        active = {item["record_id"] for item in presence if item["presence"] == "active"}
        topology = {"nodes": [node for node in graph["nodes"] if node["id"] in active],
                    "edges": [edge for edge in graph["edges"] if edge["source"] in active and edge["target"] in active]}
        for record in records:
            relation = _data(record, "gsp.relation")
            if record["id"] not in active or relation is None:
                continue
            hidden = [item for item in relation["participants"] if item["record_id"] not in active]
            if hidden or not relation["participants_complete"]:
                diagnostics.append({"code": "partial_relation_at_cut", "record_id": record["id"],
                                    "participant_ids": [item["id"] for item in hidden],
                                    "message": "This active relation has participants not established active at the cut or an explicitly incomplete participant account; only active incidences are shown."})
    return {
        "head": adapted["head"], "project_id": adapted["project"]["id"],
        "protocol_version": PROTOCOL_VERSION, "projection": PROJECTION,
        "consistent": not blocked,
        "events": [{"id": identifier, "title": record["title"], "rank": model["ranks"][identifier],
                    "predecessors": sorted(model["predecessors"][identifier]),
                    "successors": sorted(model["successors"][identifier]),
                    "status": record["status"], "modality": record["modality"], "occurred_at": record["occurred_at"]}
                   for identifier, record in sorted(model["events"].items())],
        "orders": model["orders"], "cut": cut, "extents": extents,
        "trajectories": [{"subject_record_id": subject, "record_ids": identifiers}
                         for subject, identifiers in sorted(trajectories.items())],
        "presence": presence, "topology": topology, "diagnostics": diagnostics,
        "limitations": list(LIMITATIONS),
    }
