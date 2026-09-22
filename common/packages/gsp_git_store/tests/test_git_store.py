"""Integration checks against real Git, including concurrent publication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import subprocess
import threading
from uuid import uuid4

import pytest

from gsp_git_store import Conflict, GitStore, NotFound, StoreError


@pytest.fixture
def actor():
    return {"id": str(uuid4()), "display_name": "Renée Mori"}


@pytest.fixture
def stored_project(tmp_path, actor):
    store = GitStore(tmp_path / "data")
    project = {"id": str(uuid4()), "name": "Uncertain observations"}
    head = store.create_project(project, actor)
    return store, project, head


def test_revisions_survive_restart_with_reasons_and_pseudonymous_author(stored_project, actor):
    store, project, initial = stored_project
    record = {"id": str(uuid4()), "claim": "The light appeared blue", "uncertainty": "Limited view"}
    first = store.write_record(project["id"], record, actor, initial, "Record the observation")
    revised = {**record, "claim": "The light may have appeared blue", "uncertainty": "Camera bias"}
    second = store.write_record(project["id"], revised, actor, first, "Reconsider the evidence\nCamera bias remains unresolved.")

    restarted = GitStore(store.root)
    assert restarted.snapshot(project["id"]) == {
        "project": project, "records": [revised], "head": second,
    }
    assert restarted.get_record(project["id"], record["id"], first) == {
        "record": record, "head": first,
    }
    with pytest.raises(NotFound):
        restarted.get_record(project["id"], record["id"], initial)
    history = restarted.history(project["id"], record["id"])
    assert [item["commit"] for item in history] == [second, first]
    assert history[0]["reason"] == "Reconsider the evidence\nCamera bias remains unresolved."
    assert history[0]["author"] == actor["display_name"]
    assert datetime.fromisoformat(history[0]["created_at"]).utcoffset() == timedelta(0)
    raw_commit = store._git(store._repo(project["id"]), "cat-file", "-p", second).stdout
    assert f"<{actor['id']}@users.generativity.local>".encode() in raw_commit


def test_stale_save_does_not_overwrite_another_record(stored_project, actor):
    store, project, initial = stored_project
    first_record = {"id": str(uuid4()), "claim": "One"}
    second_record = {"id": str(uuid4()), "claim": "Two"}
    head = store.write_record(project["id"], first_record, actor, initial, "Initial claim")
    with pytest.raises(Conflict):
        store.write_record(project["id"], second_record, actor, initial, "Stale save")
    assert store.snapshot(project["id"])["head"] == head
    assert store.snapshot(project["id"])["records"] == [first_record]


def test_simultaneous_writers_have_one_complete_winner(stored_project, actor, monkeypatch):
    store, project, initial = stored_project
    barrier = threading.Barrier(2)
    original_commit = store._commit

    def prepare_together(*args, **kwargs):
        commit = original_commit(*args, **kwargs)
        barrier.wait(timeout=15)
        return commit

    monkeypatch.setattr(store, "_commit", prepare_together)
    records = [{"id": str(uuid4()), "claim": "Concurrent one"},
               {"id": str(uuid4()), "claim": "Concurrent two"}]

    def write(record):
        try:
            return store.write_record(project["id"], record, actor, initial, record["claim"])
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, records))
    assert sum(value is not None for value in results) == 1
    winner = next(index for index, value in enumerate(results) if value is not None)
    snapshot = store.snapshot(project["id"])
    assert snapshot["head"] == results[winner]
    assert snapshot["records"] == [records[winner]]
    log = store._git(store._repo(project["id"]), "rev-list", "--count", "main").stdout
    assert log.strip() == b"2"


def test_failed_publication_retains_head_and_dangling_revision_is_inaccessible(stored_project, actor, monkeypatch):
    store, project, initial = stored_project
    record = {"id": str(uuid4()), "claim": "Never published"}
    prepared = []

    def fail_publication(repo, commit, expected):
        prepared.append(commit)
        raise StoreError("Simulated disk failure.")

    monkeypatch.setattr(store, "_publish", fail_publication)
    with pytest.raises(StoreError, match="Simulated disk failure"):
        store.write_record(project["id"], record, actor, initial, "Attempted save")
    assert store.snapshot(project["id"]) == {"project": project, "records": [], "head": initial}
    with pytest.raises(NotFound, match="not part"):
        store.get_record(project["id"], record["id"], prepared[0])


@pytest.mark.parametrize("identifier", ["../other", "..\\other", "--help", "", "/tmp/repo", "a" * 36])
def test_project_and_record_identifiers_cannot_be_paths(stored_project, identifier):
    store, project, _ = stored_project
    with pytest.raises(NotFound):
        store.snapshot(identifier)
    with pytest.raises(NotFound):
        store.get_record(project["id"], identifier)


@pytest.mark.parametrize("revision", ["main", "HEAD", "HEAD~1", "--help", "a" * 7,
                                       "0" * 40, "main:project.json"])
def test_revision_requires_a_reachable_full_commit(stored_project, actor, revision):
    store, project, initial = stored_project
    record = {"id": str(uuid4()), "claim": "Observation"}
    store.write_record(project["id"], record, actor, initial, "Observe")
    with pytest.raises(NotFound):
        store.get_record(project["id"], record["id"], revision)


def test_revision_from_another_project_cannot_be_read(stored_project, actor):
    store, project, initial = stored_project
    record = {"id": str(uuid4()), "claim": "Private first project"}
    first_head = store.write_record(project["id"], record, actor, initial, "Observe")
    other = {"id": str(uuid4()), "name": "Another project"}
    other_head = store.create_project(other, actor)
    store.write_record(other["id"], {**record, "claim": "Other project"}, actor, other_head, "Observe")
    with pytest.raises(NotFound):
        store.get_record(other["id"], record["id"], first_head)


def test_host_git_environment_cannot_redirect_storage(tmp_path, actor, monkeypatch):
    for key, value in {
        "GIT_DIR": str(tmp_path / "wrong-repository"),
        "GIT_WORK_TREE": str(tmp_path / "wrong-worktree"),
        "GIT_INDEX_FILE": str(tmp_path / "wrong-index"),
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.bare", "GIT_CONFIG_VALUE_0": "false",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(tmp_path / "wrong-objects"),
        "GIT_TEMPLATE_DIR": str(tmp_path / "wrong-template"),
        "GIT_AUTHOR_EMAIL": "personal@example.test", "GIT_COMMITTER_EMAIL": "personal@example.test",
    }.items():
        monkeypatch.setenv(key, value)
    store = GitStore(tmp_path / "data")
    project = {"id": str(uuid4()), "name": "Isolated"}
    head = store.create_project(project, actor)
    assert store.snapshot(project["id"])["head"] == head
    assert not (tmp_path / "wrong-index").exists()
    commit = store._git(store._repo(project["id"]), "cat-file", "-p", head).stdout
    assert b"personal@example.test" not in commit
    assert not (store._repo(project["id"]) / "hooks").exists()


def test_bundle_restores_complete_project_history(stored_project, actor, tmp_path):
    store, project, initial = stored_project
    record = {"id": str(uuid4()), "claim": "An observation"}
    first = store.write_record(project["id"], record, actor, initial, "Observe")
    second = store.write_record(project["id"], {**record, "claim": "A revision"}, actor, first, "Revise")
    bundle = tmp_path / "project.bundle"
    bundle.write_bytes(store.bundle(project["id"]))
    restored = tmp_path / "restored.git"
    result = subprocess.run([store.git, "clone", "--bare", str(bundle), str(restored)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert store._head(restored) == second
    assert store._read_json(restored, first, f"records/{record['id']}.json") == record
    assert store._git(restored, "rev-list", "--count", "main").stdout.strip() == b"3"


def test_long_windows_data_path_supports_records_and_history(tmp_path, actor):
    # Absolute --git-dir paths of this length fail in Git for Windows' object
    # writer even when core.longpaths=true. Exercise the actual commands, not
    # just command construction, so creation, reads, history and export agree.
    padding = "x" * max(1, 180 - len(str(tmp_path)) - 8)
    store = GitStore(tmp_path / ("nested-" + padding))
    project = {"id": str(uuid4()), "name": "Deeply nested workspace"}
    assert len(str(store.repositories / (project["id"] + ".git"))) >= 222
    initial = store.create_project(project, actor)
    record = {"id": str(uuid4()), "claim": "A recorded encounter"}
    head = store.write_record(project["id"], record, actor, initial, "Preserve the account")
    assert store.snapshot(project["id"])["records"] == [record]
    assert store.history(project["id"], record["id"])[0]["commit"] == head
    assert store.bundle(project["id"]).startswith(b"# v2 git bundle")


def test_subprocess_timeout_and_failure_have_safe_messages(stored_project, monkeypatch):
    store, project, _ = stored_project

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret/path/git", 30, stderr=b"private details")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(StoreError, match="timed out") as error:
        store.snapshot(project["id"])
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)
