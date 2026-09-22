# Generativity Git store

**Document class:** Software package guide  
**Status:** EXPERIMENTAL, version 0.2.0  
**Python:** 3.11 or later; Git executable required on `PATH`

An application-independent Git storage binding for project records, complete project transactions, retained material and revision history. Each project uses a separate bare repository. The package has no Flask, SQLite, browser or protocol-validator dependency. Its Python runtime uses only the standard library and invokes the installed Git executable.

The binding implements the storage responsibilities described in [GR-SPEC-130](../../../../specifications/GR-SPEC-130-interchange/GR-SPEC-130.md). The separate [record protocol package](../gsp_record_protocol/) supplies model validation and transaction preparation. Applications supply authentication, authorization, verified upload metadata, recorder attribution, request replay matching and their own presentation.

This extraction preserves the existing workspace adapter's behavior. Moving the adapter into a shared package does not establish independent application interoperability, adoption of a Standard or factual warrant for stored statements.

## Install and import

From the standards-programme repository root, using the application's chosen Python environment:

```powershell
python -m pip install -e applicative_infrastructure/common/packages/gsp_git_store
```

```python
from pathlib import Path
from gsp_git_store import GitStore, Conflict, NotFound, StoreError, LimitExceeded

store = GitStore(Path("private-project-data"))
```

The data directory and its contents need application-administrator-controlled filesystem access. Instantiating a store creates its `repositories` directory if needed. It does not create an account, authorize a caller or choose a project owner.

## Public API

| Method | Result and responsibility |
|---|---|
| `create_project(project, actor)` | Initialize a separate bare repository and return its initial commit; modern projects receive the binding manifest |
| `head(project_id)` | Current complete project commit |
| `snapshot(project_id, revision=None)` | Project manifest and records read from one accepted revision |
| `get_record(project_id, record_id, revision=None)` | Record and its selected revision |
| `commit_transaction(project_id, snapshot, receipt, actor, expected_head, assets=None)` | Publish the prepared candidate, receipt and retained file bytes through one conditional reference update |
| `transaction_receipt(project_id, transaction_id)` | Original committed receipt/result and observed current head, or `None` |
| `history(project_id, record_id, revision=None)` | Up to 100 commits affecting the record, pinned when a revision is supplied |
| `project_history(project_id, revision=None)` | Up to 100 project commits |
| `asset_file(project_id, digest, revision=None)` | Caller-owned binary temporary file positioned at byte zero |
| `bundle_file(project_id)` | Caller-owned binary temporary file containing complete accepted reachable history |
| `limits()` | Applicable storage limits for application capability disclosure |

`write_record()` and the in-memory `bundle()` helper remain compatibility interfaces. New coordinated application writes use `commit_transaction()`; HTTP downloads use `bundle_file()`.

`snapshot` is the complete prepared `{project, records}` candidate. `receipt` identifies its `transaction_id`, `expected_head`, reason, actor, digest and change account. `assets` maps verified SHA-256 strings to temporary source `Path` objects. The adapter independently checks and freezes supplied bytes before retaining them. The protocol package evaluates semantic structure; the store evaluates storage identities, bounds, understood descriptor/material closure and publication.

## Publication and reads

The binding prepares immutable blobs, trees and a commit, then conditionally advances `refs/heads/main` from `expected_head`. The accepted project therefore contains either the previous complete snapshot or the new complete snapshot. Prepared objects can remain unreachable after a failed publication; they are not accessible as accepted project revisions.

Receipts are retained at `.gsp/transactions/<transaction-id>.json`. Their original resulting commit is resolved from the path's introduction. The application checks actor and request digest before treating a receipt as a replay and does so before rejecting an old base. The storage method itself rejects duplicate receipt paths; it does not authenticate idempotent requests.

New projects using `gsp-workspace/0.2` receive `.gsp/protocol.json`, asset and transaction trees. An unfamiliar or extended binding manifest is preserved and blocks mutation. Legacy project dictionaries and old commits remain readable. Migration is a separately prepared explicit transaction, not a side effect of reading.

Project snapshots use bounded Git batch reads instead of launching a process for each record. Requested revisions must be complete commit identifiers reachable from the selected project's accepted history. Repository-relative Git execution preserves support for long Windows data paths.

## Material, streams and limits

Assets are stored at `assets/<sha256>`. Original filenames are metadata rather than storage paths. Existing assets remain in later trees when a descriptor is detached or replaced; this custody policy preserves their historical bytes. A current-snapshot application export needs to select only its intended referenced material. A full Git bundle deliberately includes reachable historical material and receipts.

The initial limits include 10 MiB per file, 20 MiB of distinct supplied asset bytes per storage transaction, eight distinct supplied blobs, 128 MiB of unique retained asset blobs in the current tree, 1,000 records, 2 MiB per serialized JSON resource and 32 MiB for the serialized project-plus-record snapshot. The HTTP/protocol layers separately count all incoming parts, including duplicate bytes, and may impose narrower transport limits. Call `limits()` when disclosing the binding's bounds.

The retained-asset budget does not bound unreachable objects, receipt-ledger growth, Git metadata, backups or total filesystem use. Operators remain responsible for capacity and recovery arrangements.

Close every returned stream, including when response creation or delivery fails:

```python
# The application has already authorized the descriptor at this project revision.
with store.asset_file(project_id, descriptor["sha256"], revision) as content:
    while block := content.read(64 * 1024):
        consume(block)
```

Knowledge of an asset digest or commit identifier is not authorization. The caller must check project access and the requested record/file descriptor at the selected revision before delivering bytes. The store does not implement accounts, encryption at rest, selective erasure, legal holds, malware examination or independent attestation. Git content identity and recording attribution do not establish truth or immutable custody against the server operator.

## Errors

`StoreError` is the safe storage-error base class. `Conflict` reports a stale publication base or duplicate published transaction identifier; `NotFound` reports invalid or unavailable identifiers/resources; `LimitExceeded` reports a declared binding limit. All are exported from `gsp_git_store`.

The application distinguishes authentication/validation failures from these storage outcomes. After an uncertain publication response, it recovers through the transaction receipt rather than asserting that nothing committed or silently creating a new transaction identifier.

## Tests

The standalone suite uses temporary data directories and real Git repositories, including concurrent writers, failed publication, material identity/limits, historical reads, immutable receipts, bundle restoration and legacy migration. It does not require an application server or an account database.

```powershell
python -m pip install -e 'applicative_infrastructure/common/packages/gsp_git_store[test]'
python -m pytest -c applicative_infrastructure/common/packages/gsp_git_store/pyproject.toml applicative_infrastructure/common/packages/gsp_git_store/tests --basetemp build/shared-git-store-tests
```

The pytest configuration also permits source-tree testing before installation. Test results establish their tested storage behavior and environment, not broader semantic or institutional conformance.

## License and contributors

This package is available under the infrastructure repository's [MIT License](../../../LICENSE), with copyright held by the contributors recorded in [CONTRIBUTORS.md](../../../CONTRIBUTORS.md). The [license scope notes](../../../LICENSE.md) preserve third-party terms and distinguish software licensing from the rights in user-created records. Programme governance drafts remain separate from this express software grant.
