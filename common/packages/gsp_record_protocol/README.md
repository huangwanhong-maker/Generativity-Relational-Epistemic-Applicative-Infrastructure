# GSP record protocol package

**Class:** Experimental implementation package  
**Protocol:** `gsp-record-protocol/0.2`  
**Record schema:** `gsp-workspace/0.2`  
**Profile:** `gsp.general/0.2`

This independent Python package validates bounded record graphs, prepares transactions, and produces an incidence projection. It has no Flask, database, filesystem-storage, or Git dependency. The CLI reads a supplied JSON file; the preparation library does not publish changes or inspect actual attachment bytes.

The [information-model Specification](../../../../specifications/GR-SPEC-120-information-model/GR-SPEC-120.md) defines the experimental contract and its limits. The [design](../../../../docs/planning/graph_workspace_design.md) separates semantic graphs, recording history, and views. Passing these validators is not factual verification or full GR conformance.

## Install and inspect

From the repository root, using a Python 3.11+ environment:

```powershell
python -m pip install -e ./applicative_infrastructure/common/packages/gsp_record_protocol
python -m gsp_protocol validate-snapshot applicative_infrastructure/common/packages/gsp_record_protocol/tests/fixtures/graph_snapshot.json
python -m pytest applicative_infrastructure/common/packages/gsp_record_protocol/tests
```

Restricted Windows environments can supply an existing writable parent and a fresh `--basetemp` path to pytest.

## Public API

| Function | Result and responsibility |
|---|---|
| `capabilities()` | Fresh dictionary describing protocol, profile, modules, operations, and library limits. |
| `validate_transaction(tx)` | Structural request validation. It cannot resolve references without a snapshot. |
| `normalize_snapshot(snapshot)` | Deep-copied read adaptation with `legacy`, `source_schema_version`, and `read_adaptation`. Original schema declarations remain unchanged. |
| `validate_snapshot(snapshot)` | Schema and scoped semantic report, including warnings for unsupported or unstructured material. Does not inspect actual file bytes. |
| `project_graph(snapshot)` | Snapshot-bound nodes and incidence/neutral-reference edges, warnings, selection declaration, and source `head`. |
| `request_digest(tx, files_meta={})` | SHA-256 of RFC 8785 canonical JSON `{transaction: tx, files: files_meta}`. File metadata comes from an adapter that has actually hashed received bytes. |
| `prepare_transaction(snapshot, tx, actor, now, files_meta={})` | Candidate `snapshot`, `receipt`, and `changed_record_ids`. Inputs are unchanged. The returned head still identifies the expected parent. |

`ProtocolError` carries `code`, `message`, and a `fields` mapping. HTTP status, authentication, authorization, binary acquisition, idempotent receipt lookup, storage budgets, conditional publication and recovery belong to the binding. The storage adapter records the new commit after publication; this package does not predict a self-referential commit identifier.

The actor has `id` and `display_name`. The recording timestamp is an ISO 8601 value with an offset. `files_meta` maps each declared multipart name to exactly `sha256` and integer `byte_length`; server paths are excluded. Duplicate, missing, extra and mismatched parts fail validation.

## Module and graph rules

Implemented version `1` modules are `gsp.relation`, `gsp.notes`, and `gsp.files`. Optional unknown modules or unsupported versions survive unrelated edits exactly and remain read-only. Required unsupported modules block project mutation. New unknown modules cannot be introduced through this implementation's editing interface.

An unsupported declared project profile also blocks mutation, including migration. Reads preserve its declaration and report an interpretation warning. An absent profile in a legacy workspace remains eligible for explicit migration. A structural report does not claim to assess an unfamiliar profile's additional requirements.

Every record remains a node. A structured Relation is independently selectable and contributes one edge per participant incidence. Orientation `in` points from the participant to the relation; `out` points from the relation to the participant; `undirected` has no asserted arrow direction. A neutral cross-reference is separately labeled `kind: reference`; its `source` records where the navigation reference is stored, without asserting a directional substantive relation.

Legacy snapshots retain their `gsp-workspace/0.1` declarations during reads. Only a sole `project.migrate` operation, with the `migration` change category, produces current schema content. Migration does not infer relation participants or change earlier account attribution/timestamps.

## Limits and evidence

The reusable profile permits 100 operations, 1,000 records, 32 incidences per relation, eight binary parts, 10 MiB per file and 20 MiB combined binary parts. Module JSON is bounded to 256 KiB; transaction JSON to 2 MiB; snapshot JSON to 64 MiB. These are application limits, not GR theoretical requirements. A binding can declare tighter limits; the current HTTP binding uses 1 MiB transaction JSON and its Git reader uses 32 MiB aggregate snapshot JSON.

The tests exercise semantic cycles, parallel and higher-order relations, partial incidence, repeated participant roles, independent qualification dimensions, opaque modules, migration, final-reference validation, retained material descriptors, replay-digest inputs, historical projections, invalid inputs and the CLI. Static fixtures are stipulated examples. They do not constitute an independent academia implementation or an institutional pilot.
