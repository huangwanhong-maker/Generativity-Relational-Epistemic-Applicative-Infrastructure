"""Whole-project transaction and retained-material checks against real Git."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import shutil
import subprocess
import threading
from uuid import uuid4

import pytest

from gsp_git_store import store as storage
from gsp_git_store import Conflict, GitStore, LimitExceeded, NotFound, StoreError


@pytest.fixture
def workspace(tmp_path):
    actor = {"id": str(uuid4()), "display_name": "Transaction recorder"}
    project = {"id": str(uuid4()), "name": "Relational inquiry", "schema_version": "gsp-workspace/0.2"}
    store = GitStore(tmp_path / "data")
    head = store.create_project(project, actor)
    return store, project, actor, head


def record(title="An account", **extra):
    return {"id": str(uuid4()), "title": title, "modules": {}, **extra}


def receipt(head, actor, reason="Preserve this coordinated change", **extra):
    return {"transaction_id": str(uuid4()), "expected_head": head,
            "reason": reason, "actor": actor, "request_digest": "a" * 64, **extra}


def material(tmp_path, body=b"An attributed source\n", file_id=None):
    digest = hashlib.sha256(body).hexdigest()
    path = tmp_path / (digest + ".upload")
    path.write_bytes(body)
    descriptor = {"file_id": file_id or str(uuid4()), "filename": "source.txt",
                  "media_type": "text/plain", "sha256": digest, "byte_length": len(body)}
    return descriptor, {digest: path}


def with_files(item, *descriptors):
    return {**item, "modules": {**item.get("modules", {}), "gsp.files": {
        "version": "1", "required": False, "data": {"items": list(descriptors)}}}}


def candidate(project, *records):
    return {"project": project, "records": list(records)}


def test_modern_project_initializes_binding_without_changing_manifest(workspace):
    store, project, _actor, head = workspace
    assert store.snapshot(project["id"]) == {**candidate(project), "head": head}
    root = store._tree_entries(store._repo(project["id"]), head)
    assert set(root) == {".gsp", "assets", "project.json", "records"}
    assert store._read_json(store._repo(project["id"]), head, ".gsp/protocol.json")["protocol_version"] == "gsp-record-protocol/0.2"


def test_nodes_relation_material_and_receipt_publish_as_one_snapshot(workspace, tmp_path):
    store, project, actor, initial = workspace
    first, second = record("First participant"), record("Second participant")
    relation = record("Their changing relationship", modules={"gsp.relation": {
        "version": "1", "required": False, "data": {"predicate": "corresponded with",
        "participants": [{"record_id": first["id"]}, {"record_id": second["id"]}]}}})
    descriptor, assets = material(tmp_path)
    relation = with_files(relation, descriptor)
    accepted = receipt(initial, actor)
    head = store.commit_transaction(project["id"], candidate(project, first, second, relation),
                                    accepted, actor, initial, assets)
    assert store.head(project["id"]) == head
    snapshot = store.snapshot(project["id"], head)
    assert {r["id"] for r in snapshot["records"]} == {first["id"], second["id"], relation["id"]}
    assert store.snapshot(project["id"], initial)["records"] == []
    assert store.transaction_receipt(project["id"], accepted["transaction_id"]) == {
        "receipt": accepted, "head": head, "current_head": head}
    assert len(store.project_history(project["id"])) == 2
    with store.asset_file(project["id"], descriptor["sha256"], head) as stream:
        assert stream.tell() == 0
        assert stream.read() == b"An attributed source\n"
    with pytest.raises(NotFound):
        store.asset_file(project["id"], descriptor["sha256"], initial)


def test_failed_publication_exposes_neither_graph_receipt_nor_file(workspace, tmp_path, monkeypatch):
    store, project, actor, initial = workspace
    descriptor, assets = material(tmp_path)
    item = with_files(record(), descriptor)
    accepted = receipt(initial, actor)
    prepared = []

    def fail(repo, commit, expected):
        prepared.append(commit)
        raise StoreError("Simulated publication failure")

    monkeypatch.setattr(store, "_publish", fail)
    with pytest.raises(StoreError, match="Simulated"):
        store.commit_transaction(project["id"], candidate(project, item), accepted, actor, initial, assets)
    assert store.head(project["id"]) == initial
    assert store.snapshot(project["id"])["records"] == []
    assert store.transaction_receipt(project["id"], accepted["transaction_id"]) is None
    with pytest.raises(NotFound):
        store.asset_file(project["id"], descriptor["sha256"])
    with pytest.raises(NotFound, match="not part"):
        store.snapshot(project["id"], prepared[0])


def test_concurrent_transactions_publish_one_complete_winner(workspace, tmp_path, monkeypatch):
    store, project, actor, initial = workspace
    barrier = threading.Barrier(2)
    original_commit = store._commit
    drafts = []
    for index in range(2):
        descriptor, assets = material(tmp_path, f"Source {index}".encode())
        drafts.append((candidate(project, record(f"Node {index}"), with_files(record(f"Relation {index}"), descriptor)),
                       receipt(initial, actor), assets))

    def together(*args, **kwargs):
        commit = original_commit(*args, **kwargs)
        barrier.wait(timeout=30)
        return commit

    monkeypatch.setattr(store, "_commit", together)

    def publish(draft):
        snapshot, accepted, assets = draft
        try:
            return store.commit_transaction(project["id"], snapshot, accepted, actor, initial, assets)
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, drafts))
    assert sum(result is not None for result in results) == 1
    winner = next(index for index, result in enumerate(results) if result is not None)
    final = store.snapshot(project["id"])
    assert final["head"] == results[winner]
    assert {r["id"] for r in final["records"]} == {r["id"] for r in drafts[winner][0]["records"]}
    assert store.transaction_receipt(project["id"], drafts[1-winner][1]["transaction_id"]) is None
    assert len(store.project_history(project["id"])) == 2


def test_receipt_lookup_survives_restart_advancing_head_and_stale_retry(workspace):
    store, project, actor, initial = workspace
    item = record("Original")
    first = receipt(initial, actor)
    one = store.commit_transaction(project["id"], candidate(project, item), first, actor, initial)
    changed = {**item, "title": "Later"}
    two = store.commit_transaction(project["id"], candidate(project, changed), receipt(one, actor), actor, one)
    restarted = GitStore(store.root)
    assert restarted.transaction_receipt(project["id"], first["transaction_id"]) == {
        "receipt": first, "head": one, "current_head": two}
    with pytest.raises(Conflict):
        restarted.commit_transaction(project["id"], candidate(project, item), first, actor, initial)
    with pytest.raises(Conflict, match="identifier"):
        restarted.commit_transaction(project["id"], candidate(project, changed),
                                       {**first, "expected_head": two}, actor, two)
    assert restarted.head(project["id"]) == two


def test_historical_labels_files_and_history_remain_pinned(workspace, tmp_path):
    store, project, actor, initial = workspace
    old, assets = material(tmp_path, b"First bytes")
    item = with_files(record("Earlier label"), old)
    first = store.commit_transaction(project["id"], candidate(project, item), receipt(initial, actor), actor, initial, assets)
    new, assets = material(tmp_path, b"Reconsidered bytes", old["file_id"])
    item = with_files({**item, "title": "Current label"}, new)
    second = store.commit_transaction(project["id"], candidate(project, item), receipt(first, actor), actor, first, assets)
    detached = with_files(item)
    third = store.commit_transaction(project["id"], candidate(project, detached), receipt(second, actor), actor, second)
    assert store.snapshot(project["id"], first)["records"][0]["title"] == "Earlier label"
    assert store.snapshot(project["id"], second)["records"][0]["title"] == "Current label"
    assert store.snapshot(project["id"])["records"][0]["modules"]["gsp.files"]["data"]["items"] == []
    for digest, revision, expected in [(old["sha256"], first, b"First bytes"), (new["sha256"], second, b"Reconsidered bytes")]:
        with store.asset_file(project["id"], digest, revision) as stream:
            assert stream.read() == expected
    with pytest.raises(NotFound):
        store.asset_file(project["id"], new["sha256"], first)
    assert [r["commit"] for r in store.history(project["id"], item["id"], first)] == [first]
    assert [r["commit"] for r in store.history(project["id"], item["id"])] == [third, second, first]
    # The store retains detached assets. HTTP permission still requires a file
    # descriptor in the authorized requested record at the selected revision.
    assets_tree = store._tree_entries(store._repo(project["id"]), f"{third}:assets")
    assert set(assets_tree) == {old["sha256"], new["sha256"]}


@pytest.mark.parametrize("failure", ["wrong_digest", "wrong_length", "missing_blob", "unused_blob"])
def test_descriptor_and_material_failures_do_not_publish(workspace, tmp_path, failure):
    store, project, actor, initial = workspace
    descriptor, assets = material(tmp_path)
    if failure == "wrong_digest":
        descriptor["sha256"] = "0" * 64
        assets = {descriptor["sha256"]: next(iter(assets.values()))}
    if failure == "wrong_length":
        descriptor["byte_length"] += 1
    if failure == "missing_blob":
        assets = {}
    item = record() if failure == "unused_blob" else with_files(record(), descriptor)
    with pytest.raises(StoreError):
        store.commit_transaction(project["id"], candidate(project, item), receipt(initial, actor), actor, initial, assets)
    assert store.head(project["id"]) == initial
    assert store.snapshot(project["id"])["records"] == []


def test_storage_budgets_count_retained_bytes_and_accept_deduplication(workspace, tmp_path, monkeypatch):
    store, project, actor, initial = workspace
    monkeypatch.setattr(storage, "_MAX_FILE_BYTES", 5)
    monkeypatch.setattr(storage, "_MAX_ASSET_BYTES", 9)
    descriptor, assets = material(tmp_path, b"12345")
    item = with_files(record(), descriptor)
    first = store.commit_transaction(project["id"], candidate(project, item), receipt(initial, actor), actor, initial, assets)
    # A second acquisition of identical bytes uses a separate descriptor and no
    # additional retained blob budget.
    repeated = {**descriptor, "file_id": str(uuid4())}
    item = with_files(item, descriptor, repeated)
    second = store.commit_transaction(project["id"], candidate(project, item), receipt(first, actor), actor, first, assets)
    replacement, replacement_assets = material(tmp_path, b"67890", descriptor["file_id"])
    with pytest.raises(LimitExceeded, match="retained"):
        store.commit_transaction(project["id"], candidate(project, with_files(item, replacement)),
                                  receipt(second, actor), actor, second, replacement_assets)
    too_large, large_assets = material(tmp_path, b"123456")
    with pytest.raises(LimitExceeded, match="file"):
        store.commit_transaction(project["id"], candidate(project, with_files(item, too_large)),
                                  receipt(second, actor), actor, second, large_assets)
    assert store.head(project["id"]) == second


def test_snapshot_uses_one_bounded_batch_for_many_records(workspace, monkeypatch):
    store, project, actor, initial = workspace
    items = [record(f"Account {index}") for index in range(120)]
    head = store.commit_transaction(project["id"], candidate(project, *items), receipt(initial, actor), actor, initial)
    original_git, calls = store._git, []

    def track(repo, *args, **kwargs):
        calls.append(args)
        return original_git(repo, *args, **kwargs)

    monkeypatch.setattr(store, "_git", track)
    assert len(store.snapshot(project["id"])["records"]) == 120
    assert sum(args[:2] == ("cat-file", "--batch") for args in calls) == 1
    assert len(calls) <= 6
    calls.clear()
    monkeypatch.setattr(storage, "_MAX_SNAPSHOT_JSON_BYTES", 50)
    with pytest.raises(LimitExceeded):
        store.snapshot(project["id"], head)
    assert not any(args[:2] == ("cat-file", "--batch") for args in calls)


def test_bundle_restores_transactions_and_old_file_versions(workspace, tmp_path, tmp_path_factory):
    store, project, actor, initial = workspace
    descriptor, assets = material(tmp_path, b"Historical material")
    item = with_files(record("Earlier"), descriptor)
    accepted = receipt(initial, actor)
    first = store.commit_transaction(project["id"], candidate(project, item), accepted, actor, initial, assets)
    second = store.commit_transaction(project["id"], candidate(project, with_files({**item, "title": "Later"})),
                                      receipt(first, actor), actor, first)
    bundle = tmp_path / "retained.bundle"
    with store.bundle_file(project["id"]) as source, bundle.open("wb") as destination:
        assert source.tell() == 0
        shutil.copyfileobj(source, destination)
    # Git for Windows' clone/index-pack has a stricter internal path bound than
    # repository-local plumbing. Keep this independent restore destination short;
    # a separate test exercises long paths through the actual storage adapter.
    restored_store = GitStore(tmp_path_factory.mktemp("restore"))
    restored = restored_store.repositories / (project["id"] + ".git")
    result = subprocess.run([store.git, "-c", "core.longpaths=true", "clone", "--bare",
                             str(bundle), restored.name], cwd=restored.parent,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert restored_store.head(project["id"]) == second
    assert restored_store.transaction_receipt(project["id"], accepted["transaction_id"])["head"] == first
    with restored_store.asset_file(project["id"], descriptor["sha256"], first) as source:
        assert source.read() == b"Historical material"
    assert restored_store.snapshot(project["id"], first)["records"][0]["title"] == "Earlier"


def test_modified_receipt_is_detected_instead_of_reporting_false_introduction(workspace):
    store, project, actor, initial = workspace
    accepted = receipt(initial, actor)
    head = store.commit_transaction(project["id"], candidate(project), accepted, actor, initial)
    repo = store._repo(project["id"])
    root = store._tree_entries(repo, head)
    gsp = store._subtree_entries(repo, root, ".gsp")
    entries = store._subtree_entries(repo, gsp, "transactions")
    entries[accepted["transaction_id"] + ".json"] = ("100644", "blob", store._json_blob(repo, {**accepted, "reason": "Tampered"}))
    gsp["transactions"] = ("040000", "tree", store._tree(repo, entries))
    root[".gsp"] = ("040000", "tree", store._tree(repo, gsp))
    changed = store._commit(repo, store._tree(repo, root), actor, "External alteration", head)
    store._publish(repo, changed, head)
    with pytest.raises(StoreError, match="modified"):
        store.transaction_receipt(project["id"], accepted["transaction_id"])


def test_explicit_migration_preserves_legacy_commit_and_untyped_references(tmp_path):
    actor = {"id": str(uuid4()), "display_name": "Migration recorder"}
    store = GitStore(tmp_path / "legacy")
    project = {"id": str(uuid4()), "name": "Legacy", "schema_version": "gsp-workspace/0.1"}
    initial = store.create_project(project, actor)
    one = {"id": str(uuid4()), "title": "An unstructured relation", "record_type": "Relation", "related_records": []}
    old = store.write_record(project["id"], one, actor, initial, "Original account")
    before = deepcopy(store.snapshot(project["id"], old))
    modern = {**project, "schema_version": "gsp-workspace/0.2"}
    adapted = {**one, "schema_version": "gsp-workspace/0.2", "record_roles": ["Relation"], "modules": {}}
    new = store.commit_transaction(project["id"], candidate(modern, adapted), receipt(old, actor, "Explicit migration"), actor, old)
    assert store.snapshot(project["id"], old) == before
    assert "gsp.relation" not in store.snapshot(project["id"], new)["records"][0]["modules"]
    assert store.history(project["id"], one["id"], old)[0]["commit"] == old


def test_unknown_optional_file_module_is_preserved_without_interpretation(workspace):
    store, project, actor, initial = workspace
    opaque = {"version": "future-version", "required": False,
              "data": {"unfamiliar_material_model": {"untouched": [0, False, None]}}}
    item = record(modules={"gsp.files": opaque, "example.future": {
        "version": "7", "required": False, "data": {"meaning": "uninterpreted"}}})
    one = store.commit_transaction(project["id"], candidate(project, item), receipt(initial, actor), actor, initial)
    two = store.commit_transaction(project["id"], candidate(project, {**item, "title": "A later description"}),
                                    receipt(one, actor), actor, one)
    assert store.snapshot(project["id"], two)["records"][0]["modules"] == item["modules"]


def test_zero_byte_file_is_distinct_from_absent_material(workspace, tmp_path):
    store, project, actor, initial = workspace
    descriptor, assets = material(tmp_path, b"")
    item = with_files(record(), descriptor)
    head = store.commit_transaction(project["id"], candidate(project, item), receipt(initial, actor), actor, initial, assets)
    with store.asset_file(project["id"], descriptor["sha256"], head) as output:
        assert output.read() == b""
    assert store.snapshot(project["id"], head)["records"][0]["modules"]["gsp.files"]["data"]["items"][0]["byte_length"] == 0


def test_total_incoming_material_limit_is_checked_before_publication(workspace, tmp_path, monkeypatch):
    store, project, actor, initial = workspace
    monkeypatch.setattr(storage, "_MAX_TRANSACTION_FILE_BYTES", 7)
    first, one = material(tmp_path, b"1234")
    second, two = material(tmp_path, b"5678")
    with pytest.raises(LimitExceeded, match="transaction"):
        store.commit_transaction(project["id"], candidate(project, with_files(record(), first, second)),
                                  receipt(initial, actor), actor, initial, {**one, **two})
    assert store.head(project["id"]) == initial


@pytest.mark.parametrize("change", [
    {"protocol_version": "gsp-record-protocol/9"},
    {"profile": "example.other/1"},
    {"binding": "example.storage/1"},
    {"object_format": "sha256"},
    {"record_schema": "gsp-workspace/9"},
    {"required_future_capability": "preserve-me"},
])
def test_unrecognized_binding_manifest_is_readable_but_never_overwritten(workspace, change):
    store, project, actor, initial = workspace
    repo = store._repo(project["id"])
    root = store._tree_entries(repo, initial)
    gsp = store._subtree_entries(repo, root, ".gsp")
    manifest = {**storage._PROTOCOL, **change}
    gsp["protocol.json"] = ("100644", "blob", store._json_blob(repo, manifest))
    root[".gsp"] = ("040000", "tree", store._tree(repo, gsp))
    foreign = store._commit(repo, store._tree(repo, root), actor, "Fixture: another binding declaration", initial)
    store._publish(repo, foreign, initial)
    before = store.snapshot(project["id"])
    with pytest.raises(StoreError, match="unsupported protocol manifest"):
        store.commit_transaction(project["id"], candidate(project, record()), receipt(foreign, actor), actor, foreign)
    assert store.snapshot(project["id"]) == before
    assert store._read_json(repo, foreign, ".gsp/protocol.json") == manifest
