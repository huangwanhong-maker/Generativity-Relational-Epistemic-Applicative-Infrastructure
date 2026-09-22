"""Git-backed, project-isolated JSON records without a shared worktree or index.

Only the main ref publishes a change. Objects are prepared first and update-ref
compares the expected parent atomically; a failed write never publishes a partial
record. Git history establishes the application's revision history, not truth or
independent authentication of the statements recorded in it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any, BinaryIO
from uuid import UUID


class StoreError(Exception):
    """Storage failed; the message is safe to show without filesystem details."""


class NotFound(StoreError):
    """A requested project, record or reachable revision does not exist."""


class Conflict(StoreError):
    """The caller's project head no longer matches the published head."""


class LimitExceeded(StoreError):
    """The proposed content exceeds an explicit storage-binding limit."""


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_CONTENT_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAIN = "refs/heads/main"
_ZERO = "0" * 40
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_SNAPSHOT_JSON_BYTES = 32 * 1024 * 1024
_MAX_RECORDS = 1000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_TRANSACTION_FILE_BYTES = 20 * 1024 * 1024
_MAX_ASSET_BYTES = 128 * 1024 * 1024
_PROTOCOL = {
    "protocol_version": "gsp-record-protocol/0.2",
    "profile": "gsp.general/0.2",
    "binding": "gsp.git/0.2",
    "object_format": "sha1",
    "record_schema": "gsp-workspace/0.2",
}


def _uuid(value: Any) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise NotFound("The requested identifier is invalid.") from None
    return value


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise NotFound("The requested revision is invalid.")
    return value


class GitStore:
    """One application-managed bare repository per project under a data root."""

    def __init__(self, root: Path, timeout: float = 30):
        self.root = Path(root).resolve()
        self.repositories = self.root / "repositories"
        self.timeout = timeout
        try:
            self.repositories.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise StoreError("The record storage directory is unavailable.") from None
        self.git = shutil.which("git")
        if not self.git:
            raise StoreError("Git is not installed or is unavailable.")

    def _environment(self, actor: dict | None = None) -> dict[str, str]:
        # Do not inherit another repository, index, injected config, alternate
        # object directory, transport helper or identity from the host process.
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith("GIT_")}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "LC_ALL": "C",
        })
        if actor is not None:
            actor_id = _uuid(actor.get("id"))
            name = actor.get("display_name", actor_id)
            if not isinstance(name, str):
                raise StoreError("A valid record author is required.")
            # Git identities cannot contain angle brackets or control characters.
            name = " ".join("".join(
                char for char in name if char not in "<>" and ord(char) >= 32
                and ord(char) != 127
            ).split())[:200] or actor_id
            email = f"{actor_id}@users.generativity.local"
            date = f"@{int(time.time())} +0000"
            env.update({
                "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
                "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
            })
        return env

    def _git(self, repo: Path | None, *args: str, data: bytes | None = None,
             actor: dict | None = None, check: bool = True,
             input_file: BinaryIO | None = None,
             output_file: BinaryIO | None = None,
             ) -> subprocess.CompletedProcess[bytes]:
        if data is not None and input_file is not None:
            raise StoreError("The storage input is ambiguous.")
        command = [self.git, "--no-pager", "-c", f"core.hooksPath={os.devnull}",
                   "-c", "core.useReplaceRefs=false", "-c", "gc.auto=0",
                   "-c", "maintenance.auto=false", "-c", "protocol.allow=never",
                   "-c", "core.quotePath=false", "-c", "core.longpaths=true",
                   "-c", "commit.gpgSign=false"]
        if repo is not None:
            # Git for Windows still bounds an absolute GIT_DIR in some object
            # writers even with core.longpaths enabled. A repository-local cwd
            # keeps those internal paths short, without a shared worktree/index.
            command.append("--git-dir=.")
        command.extend(args)
        try:
            result = subprocess.run(
                command, input=data, stdin=input_file,
                stdout=output_file if output_file is not None else subprocess.PIPE,
                stderr=subprocess.PIPE, check=False,
                cwd=repo if repo is not None else self.root,
                env=self._environment(actor), timeout=self.timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise StoreError("The record storage operation timed out.") from None
        except OSError:
            raise StoreError("The record storage operation could not run.") from None
        if check and result.returncode:
            raise StoreError("The record storage operation failed.")
        return result

    def _repo(self, project_id: str, *, exists: bool = True) -> Path:
        project_id = _uuid(project_id)
        repo = self.repositories / f"{project_id}.git"
        # IDs never become arbitrary paths; reject a repository symlink as well.
        if repo.is_symlink() or repo.resolve().parent != self.repositories.resolve():
            raise NotFound("The requested project was not found.")
        if exists and not repo.is_dir():
            raise NotFound("The requested project was not found.")
        return repo

    def _object_id(self, output: bytes) -> str:
        try:
            return _sha(output.decode("ascii").strip())
        except (UnicodeError, NotFound):
            raise StoreError("The record storage returned an invalid object.") from None

    def _head(self, repo: Path) -> str:
        return self._object_id(self._git(repo, "rev-parse", "--verify", _MAIN).stdout)

    def head(self, project_id: str) -> str:
        """Return the current complete project revision."""
        return self._head(self._repo(project_id))

    @staticmethod
    def limits() -> dict[str, int]:
        """Binding limits for disclosure alongside protocol-level capabilities."""
        return {"json_resource_bytes": _MAX_JSON_BYTES,
                "snapshot_json_bytes": _MAX_SNAPSHOT_JSON_BYTES,
                "file_bytes": _MAX_FILE_BYTES,
                "transaction_file_bytes": _MAX_TRANSACTION_FILE_BYTES,
                "retained_asset_bytes": _MAX_ASSET_BYTES,
                "records": _MAX_RECORDS}

    def _encode_json(self, value: dict) -> bytes:
        try:
            data = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise StoreError("The record cannot be encoded as JSON.") from None
        if len(data) > _MAX_JSON_BYTES:
            raise LimitExceeded("A JSON resource exceeds the storage size limit.")
        return data

    def _json_blob(self, repo: Path, value: dict) -> str:
        data = self._encode_json(value)
        return self._object_id(self._git(repo, "hash-object", "-w", "--stdin",
                                         data=data).stdout)

    @staticmethod
    def _blob_id(data: bytes) -> str:
        # This binding explicitly initializes SHA-1 repositories. This is the Git
        # object identity, not the independent SHA-256 digest of attached bytes.
        return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

    def _tree(self, repo: Path, entries: dict[str, tuple[str, str, str]]) -> str:
        body = b"".join(f"{mode} {kind} {oid}\t{name}".encode("utf-8") + b"\0"
                        for name, (mode, kind, oid) in sorted(entries.items()))
        return self._object_id(self._git(repo, "mktree", "-z", data=body).stdout)

    def _tree_entries(self, repo: Path, treeish: str) -> dict[str, tuple[str, str, str]]:
        output = self._git(repo, "ls-tree", "-z", treeish).stdout
        entries = {}
        try:
            for entry in output.split(b"\0"):
                if not entry:
                    continue
                metadata, name_bytes = entry.split(b"\t", 1)
                mode, kind, oid = metadata.decode("ascii").split(" ")
                name = name_bytes.decode("utf-8")
                if name in entries or kind not in {"blob", "tree"}:
                    raise ValueError
                entries[name] = (mode, kind, _sha(oid))
        except (ValueError, UnicodeError, NotFound):
            raise StoreError("The record repository has an invalid tree.") from None
        return entries

    def _subtree_entries(self, repo: Path, entries: dict, name: str) -> dict:
        entry = entries.get(name)
        if entry is None:
            return {}
        if entry[:2] != ("040000", "tree"):
            raise StoreError("The project contains an invalid resource tree.")
        return self._tree_entries(repo, entry[2])

    def _resolve_revision(self, repo: Path, revision: str | None) -> str:
        current = self._head(repo)
        if revision is None:
            return current
        head = _sha(revision)
        kind = self._git(repo, "cat-file", "-t", head, check=False)
        if kind.returncode or kind.stdout.strip() != b"commit":
            raise NotFound("The requested revision was not found in this project.")
        reachable = self._git(repo, "merge-base", "--is-ancestor", head,
                              current, check=False)
        if reachable.returncode == 1:
            raise NotFound("The requested revision is not part of this project's history.")
        if reachable.returncode:
            raise StoreError("The revision history could not be checked.")
        return head

    def _object_sizes(self, repo: Path, objects: list[str]) -> dict[str, int]:
        if not objects:
            return {}
        objects = list(dict.fromkeys(_sha(oid) for oid in objects))
        result = self._git(repo, "cat-file",
                           "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                           data=("\n".join(objects) + "\n").encode("ascii"))
        try:
            lines = result.stdout.decode("ascii").splitlines()
            if len(lines) != len(objects):
                raise ValueError
            sizes = {}
            for expected, line in zip(objects, lines):
                oid, kind, size = line.split(" ")
                if oid != expected or kind != "blob" or not size.isdecimal():
                    raise ValueError
                sizes[oid] = int(size)
            return sizes
        except (ValueError, UnicodeError):
            raise StoreError("The project contains an unavailable or invalid blob.") from None

    @staticmethod
    def _decode_json(data: bytes) -> dict:
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError
                value[key] = item
            return value

        def bad_constant(_value):
            raise ValueError

        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                               parse_constant=bad_constant)
            if not isinstance(value, dict):
                raise ValueError
            # Escaped lone surrogates are syntactically accepted by Python's JSON
            # parser, but cannot represent interoperable Unicode record text.
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            return value
        except (UnicodeError, ValueError, RecursionError):
            raise StoreError("The stored resource is not a valid JSON object.") from None

    def _read_json_objects(self, repo: Path, objects: list[str], *,
                           total_limit: int | None = None) -> list[dict]:
        """Read known blobs in two Git processes, bounded before body output."""
        if not objects:
            return []
        if total_limit is None:
            total_limit = _MAX_SNAPSHOT_JSON_BYTES
        sizes = self._object_sizes(repo, objects)
        if any(sizes[oid] > _MAX_JSON_BYTES for oid in objects) \
                or sum(sizes[oid] for oid in objects) > total_limit:
            raise LimitExceeded("The JSON snapshot exceeds the storage size limit.")
        request = ("\n".join(objects) + "\n").encode("ascii")
        try:
            with tempfile.TemporaryFile(mode="w+b") as output:
                self._git(repo, "cat-file", "--batch", data=request, output_file=output)
                output.seek(0)
                values = []
                for oid in objects:
                    expected = f"{oid} blob {sizes[oid]}\n".encode("ascii")
                    if output.readline(128) != expected:
                        raise StoreError("The snapshot object stream is invalid.")
                    body = output.read(sizes[oid])
                    if len(body) != sizes[oid] or output.read(1) != b"\n":
                        raise StoreError("The snapshot object stream is incomplete.")
                    values.append(self._decode_json(body))
                if output.read(1):
                    raise StoreError("The snapshot object stream has unexpected content.")
                return values
        except OSError:
            raise StoreError("The snapshot could not be buffered safely.") from None

    def _commit(self, repo: Path, tree: str, actor: dict, reason: str,
                parent: str | None = None) -> str:
        if not isinstance(reason, str) or not reason.strip() or "\0" in reason \
                or len(reason) > 2000:
            raise StoreError("A revision reason of 1 to 2000 characters is required.")
        args = ["commit-tree", tree]
        if parent:
            args.extend(["-p", parent])
        message = (reason.strip().replace("\r\n", "\n") + "\n").encode("utf-8")
        return self._object_id(self._git(repo, *args, data=message, actor=actor).stdout)

    def _publish(self, repo: Path, commit: str, expected: str) -> None:
        result = self._git(repo, "update-ref", _MAIN, commit, expected, check=False)
        if result.returncode:
            # A racing writer may still hold the lock without having published its
            # ref yet. Treat this as a conflict too, so the caller can reload.
            if b"cannot lock ref" in result.stderr or self._head(repo) != expected:
                raise Conflict("The project changed. Reload it before saving again.")
            raise StoreError("The revision could not be published.")

    def create_project(self, project: dict, actor: dict) -> str:
        if not isinstance(project, dict):
            raise StoreError("A project manifest is required.")
        repo = self._repo(project.get("id"), exists=False)
        try:
            repo.mkdir()
        except FileExistsError:
            raise Conflict("This project already exists.") from None
        except OSError:
            raise StoreError("The project repository could not be created.") from None
        try:
            # An empty template prevents host templates from installing hooks.
            self._git(None, "init", "--bare", "--initial-branch=main",
                      "--object-format=sha1", "--template=", str(repo))
            manifest = self._json_blob(repo, project)
            records = self._tree(repo, {})
            entries = {"project.json": ("100644", "blob", manifest),
                       "records": ("040000", "tree", records)}
            if project.get("schema_version") == "gsp-workspace/0.2":
                entries["assets"] = ("040000", "tree", self._tree(repo, {}))
                protocol = self._json_blob(repo, _PROTOCOL)
                gsp = self._tree(repo, {
                    "protocol.json": ("100644", "blob", protocol),
                    "transactions": ("040000", "tree", self._tree(repo, {})),
                })
                entries[".gsp"] = ("040000", "tree", gsp)
            tree = self._tree(repo, entries)
            commit = self._commit(repo, tree, actor, "Create project")
            self._publish(repo, commit, _ZERO)
            return commit
        except Exception:
            # Only remove the exact UUID directory this invocation just created.
            if not repo.is_symlink() and repo.resolve().parent == self.repositories.resolve():
                shutil.rmtree(repo, ignore_errors=True)
            raise

    def _read_json(self, repo: Path, head: str, path: str) -> dict:
        result = self._git(repo, "rev-parse", "--verify", f"{head}:{path}", check=False)
        if result.returncode:
            raise NotFound("The requested record was not found in this revision.")
        oid = self._object_id(result.stdout)
        return self._read_json_objects(repo, [oid])[0]

    def snapshot(self, project_id: str, revision: str | None = None) -> dict:
        repo = self._repo(project_id)
        head = self._resolve_revision(repo, revision)
        root_entries = self._tree_entries(repo, head)
        project_entry = root_entries.get("project.json")
        if not project_entry or project_entry[:2] != ("100644", "blob"):
            raise StoreError("The project manifest is unavailable.")
        record_ids, objects = [], [project_entry[2]]
        if "records" not in root_entries:
            raise StoreError("The project record tree is unavailable.")
        for name, (mode, kind, oid) in sorted(self._subtree_entries(repo, root_entries, "records").items()):
            if not name.endswith(".json") or kind != "blob" or mode != "100644":
                raise StoreError("The repository contains an invalid record entry.")
            try:
                record_id = _uuid(name[:-5])
            except NotFound:
                raise StoreError("The repository contains an invalid record identifier.") from None
            record_ids.append(record_id)
            objects.append(oid)
        if len(record_ids) > _MAX_RECORDS:
            raise LimitExceeded("The project exceeds the record count limit.")
        values = self._read_json_objects(repo, objects)
        project, records = values[0], values[1:]
        if project.get("id") != project_id:
            raise StoreError("The project manifest does not match its repository.")
        for record_id, record in zip(record_ids, records):
            if record.get("id") != record_id:
                raise StoreError("The stored record identifier does not match its path.")
        return {"project": project, "records": records, "head": head}

    def get_record(self, project_id: str, record_id: str,
                   revision: str | None = None) -> dict:
        repo = self._repo(project_id)
        record_id = _uuid(record_id)
        head = self._resolve_revision(repo, revision)
        record = self._read_json(repo, head, f"records/{record_id}.json")
        if record.get("id") != record_id:
            raise StoreError("The stored record identifier does not match its path.")
        return {"record": record, "head": head}

    def write_record(self, project_id: str, record: dict, actor: dict,
                     expected_head: str, reason: str) -> str:
        repo = self._repo(project_id)
        if not isinstance(record, dict):
            raise StoreError("A record object is required.")
        record_id = _uuid(record.get("id"))
        expected_head = _sha(expected_head)
        if self._head(repo) != expected_head:
            raise Conflict("The project changed. Reload it before saving again.")
        root_entries = self._tree_entries(repo, expected_head)
        records_entry = root_entries.get("records")
        if not records_entry or records_entry[1] != "tree":
            raise StoreError("The project record tree is unavailable.")
        records = self._tree_entries(repo, records_entry[2])
        blob = self._json_blob(repo, record)
        records[f"{record_id}.json"] = ("100644", "blob", blob)
        root_entries["records"] = ("040000", "tree", self._tree(repo, records))
        tree = self._tree(repo, root_entries)
        commit = self._commit(repo, tree, actor, reason, expected_head)
        self._publish(repo, commit, expected_head)
        return commit

    def _asset_entries(self, repo: Path, root: dict) -> tuple[dict, dict[str, int]]:
        entries = self._subtree_entries(repo, root, "assets")
        for name, (mode, kind, _oid) in entries.items():
            if not _CONTENT_SHA.fullmatch(name) or (mode, kind) != ("100644", "blob"):
                raise StoreError("The project contains an invalid retained asset.")
        sizes = self._object_sizes(repo, [entry[2] for entry in entries.values()])
        if any(size > _MAX_FILE_BYTES for size in sizes.values()) \
                or sum(sizes.values()) > _MAX_ASSET_BYTES:
            raise LimitExceeded("The project exceeds the retained asset limit.")
        return entries, sizes

    def _store_asset(self, repo: Path, digest: str, path: Path) -> tuple[str, int]:
        """Hash and freeze the same bounded byte stream that Git will retain."""
        if not isinstance(digest, str) or not _CONTENT_SHA.fullmatch(digest):
            raise StoreError("The asset digest is invalid.")
        try:
            path = Path(path)
            if path.is_symlink():
                raise StoreError("An upload must be a regular temporary file.")
            with path.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as frozen:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise StoreError("An upload must be a regular temporary file.")
                hasher, size = hashlib.sha256(), 0
                while True:
                    block = source.read(64 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > _MAX_FILE_BYTES:
                        raise LimitExceeded("A file exceeds the 10 MiB storage limit.")
                    hasher.update(block)
                    frozen.write(block)
                if hasher.hexdigest() != digest:
                    raise StoreError("The uploaded bytes do not match their SHA-256 digest.")
                frozen.seek(0)
                oid = self._object_id(self._git(repo, "hash-object", "-w", "--stdin",
                                                input_file=frozen).stdout)
                return oid, size
        except (OSError, TypeError):
            raise StoreError("The uploaded material could not be read safely.") from None

    def commit_transaction(self, project_id: str, snapshot: dict, receipt: dict,
                           actor: dict, expected_head: str,
                           assets: dict[str, Path] | None = None) -> str:
        """Publish one prepared candidate, its receipt and its material atomically.

        The protocol/API performs semantic validation and replay matching. This
        adapter additionally checks storage identities, limits and file closure.
        Earlier asset entries and transaction receipts remain in the new tree.
        """
        repo = self._repo(project_id)
        expected_head = _sha(expected_head)
        if self._head(repo) != expected_head:
            raise Conflict("The project changed. Reload it before saving again.")
        if not isinstance(snapshot, dict) or not isinstance(receipt, dict):
            raise StoreError("A complete snapshot and transaction receipt are required.")
        project, records = snapshot.get("project"), snapshot.get("records")
        if not isinstance(project, dict) or project.get("id") != project_id \
                or not isinstance(records, list):
            raise StoreError("The transaction snapshot does not match its project.")
        if len(records) > _MAX_RECORDS:
            raise LimitExceeded("The project exceeds the record count limit.")
        transaction_id = _uuid(receipt.get("transaction_id"))
        if receipt.get("expected_head") != expected_head:
            raise StoreError("The transaction receipt does not identify its base revision.")
        if any(key in receipt for key in ("result_commit", "result_head")):
            raise StoreError("The receipt cannot embed its own resulting commit.")
        root = self._tree_entries(repo, expected_head)
        current_records = self._subtree_entries(repo, root, "records")
        gsp = self._subtree_entries(repo, root, ".gsp")
        transactions = self._subtree_entries(repo, gsp, "transactions")
        receipt_name = f"{transaction_id}.json"
        if receipt_name in transactions:
            raise Conflict("This transaction identifier has already been published.")
        if "protocol.json" in gsp:
            entry = gsp["protocol.json"]
            if entry[:2] != ("100644", "blob"):
                raise StoreError("The project protocol manifest is invalid.")
            protocol = self._read_json_objects(repo, [entry[2]])[0]
            if protocol != _PROTOCOL:
                raise StoreError("The project uses an unsupported protocol manifest.")

        # Compute identities locally so unchanged JSON blobs need no process.
        # All encodings are bounded before objects are written.
        proposed_records, pending_blobs = {}, {}
        project_bytes = self._encode_json(project)
        project_oid = self._blob_id(project_bytes)
        total_json = len(project_bytes)
        if root.get("project.json") != ("100644", "blob", project_oid):
            pending_blobs[project_oid] = project_bytes
        for record in records:
            if not isinstance(record, dict):
                raise StoreError("Every retained record must be a JSON object.")
            record_id = _uuid(record.get("id"))
            filename = f"{record_id}.json"
            if filename in proposed_records:
                raise StoreError("The snapshot repeats a record identifier.")
            encoded = self._encode_json(record)
            total_json += len(encoded)
            if total_json > _MAX_SNAPSHOT_JSON_BYTES:
                raise LimitExceeded("The JSON snapshot exceeds the storage size limit.")
            oid = self._blob_id(encoded)
            proposed_records[filename] = ("100644", "blob", oid)
            if current_records.get(filename) != proposed_records[filename]:
                pending_blobs[oid] = encoded
        if set(current_records) - set(proposed_records):
            raise StoreError("This binding does not silently remove retained records.")

        asset_entries, asset_sizes = self._asset_entries(repo, root)
        if assets is None:
            assets = {}
        if not isinstance(assets, dict) or len(assets) > 8:
            raise LimitExceeded("A transaction supports at most eight distinct file blobs.")
        supplied_bytes = 0
        for digest, path in assets.items():
            oid, size = self._store_asset(repo, digest, path)
            supplied_bytes += size
            if supplied_bytes > _MAX_TRANSACTION_FILE_BYTES:
                raise LimitExceeded("The transaction exceeds the 20 MiB file limit.")
            previous = asset_entries.get(digest)
            if previous is not None and previous != ("100644", "blob", oid):
                raise StoreError("Retained bytes conflict with their asset digest.")
            asset_entries[digest] = ("100644", "blob", oid)
            asset_sizes[oid] = size
        if sum(asset_sizes.values()) > _MAX_ASSET_BYTES:
            raise LimitExceeded("The project exceeds the 128 MiB retained asset limit.")

        referenced_assets = set()
        for record in records:
            modules = record.get("modules", {})
            if not isinstance(modules, dict):
                raise StoreError("The record module mapping is invalid.")
            files = modules.get("gsp.files")
            if files is None:
                continue
            if not isinstance(files, dict):
                raise StoreError("The retained file module is invalid.")
            if files.get("version") != "1":
                # An unsupported optional module remains opaque. Protocol
                # validation handles required capabilities; retained assets are
                # never collected merely because this reader cannot interpret it.
                continue
            try:
                items = files["data"]["items"]
                if not isinstance(items, list):
                    raise ValueError
                for item in items:
                    digest, size = item["sha256"], item["byte_length"]
                    if not isinstance(digest, str) or not _CONTENT_SHA.fullmatch(digest) \
                            or not isinstance(size, int) or isinstance(size, bool):
                        raise ValueError
                    if digest not in asset_entries \
                            or asset_sizes[asset_entries[digest][2]] != size:
                        raise StoreError("A file descriptor does not match retained material.")
                    referenced_assets.add(digest)
            except (KeyError, TypeError, ValueError):
                raise StoreError("A retained file descriptor is invalid.") from None
        if set(assets) - referenced_assets:
            raise StoreError("The transaction supplies file bytes without a current descriptor.")

        for expected_oid, data in pending_blobs.items():
            actual = self._object_id(self._git(repo, "hash-object", "-w", "--stdin", data=data).stdout)
            if actual != expected_oid:
                raise StoreError("The repository object format does not match this binding.")
        root["project.json"] = ("100644", "blob", project_oid)
        root["records"] = ("040000", "tree", self._tree(repo, proposed_records))
        root["assets"] = ("040000", "tree", self._tree(repo, asset_entries))
        transactions[receipt_name] = ("100644", "blob", self._json_blob(repo, receipt))
        gsp["transactions"] = ("040000", "tree", self._tree(repo, transactions))
        gsp["protocol.json"] = ("100644", "blob", self._json_blob(repo, _PROTOCOL))
        root[".gsp"] = ("040000", "tree", self._tree(repo, gsp))
        tree = self._tree(repo, root)
        commit = self._commit(repo, tree, actor, receipt.get("reason"), expected_head)
        self._publish(repo, commit, expected_head)
        return commit

    def transaction_receipt(self, project_id: str, transaction_id: str) -> dict | None:
        """Find a receipt in one pinned head and identify its introducing commit."""
        repo = self._repo(project_id)
        transaction_id = _uuid(transaction_id)
        head = self._head(repo)
        root = self._tree_entries(repo, head)
        gsp = self._subtree_entries(repo, root, ".gsp")
        entries = self._subtree_entries(repo, gsp, "transactions")
        entry = entries.get(f"{transaction_id}.json")
        if entry is None:
            return None
        if entry[:2] != ("100644", "blob"):
            raise StoreError("The transaction receipt is invalid.")
        receipt = self._read_json_objects(repo, [entry[2]])[0]
        if receipt.get("transaction_id") != transaction_id:
            raise StoreError("The transaction receipt identifier does not match its path.")
        path = f".gsp/transactions/{transaction_id}.json"
        output = self._git(repo, "log", "--full-history", "--max-count=2",
                           "--format=%H", head, "--", path).stdout
        try:
            revisions = output.decode("ascii").splitlines()
            if len(revisions) != 1:
                raise ValueError
            introduced = _sha(revisions[0])
        except (UnicodeError, ValueError, NotFound):
            raise StoreError("The retained transaction receipt has been modified.") from None
        return {"receipt": receipt, "head": introduced, "current_head": head}

    def history(self, project_id: str, record_id: str,
                revision: str | None = None) -> list[dict]:
        repo = self._repo(project_id)
        record_id = _uuid(record_id)
        head = self._resolve_revision(repo, revision)
        self._read_json(repo, head, f"records/{record_id}.json")
        return self._history(repo, head, f"records/{record_id}.json")

    def project_history(self, project_id: str,
                        revision: str | None = None) -> list[dict]:
        repo = self._repo(project_id)
        return self._history(repo, self._resolve_revision(repo, revision))

    def _history(self, repo: Path, head: str, path: str | None = None) -> list[dict]:
        args = ["log", "-z", "--max-count=100", "--format=%H%x00%an%x00%aI%x00%B", head]
        if path is not None:
            args.extend(["--", path])
        output = self._git(repo, *args).stdout
        if not output:
            return []
        try:
            fields = output.decode("utf-8").rstrip("\0").split("\0")
            if len(fields) % 4:
                raise ValueError
            return [{"commit": _sha(fields[index]), "author": fields[index + 1],
                     "created_at": fields[index + 2], "reason": fields[index + 3].strip()}
                    for index in range(0, len(fields), 4)]
        except (ValueError, UnicodeError, NotFound):
            raise StoreError("The revision history could not be read.") from None

    def asset_file(self, project_id: str, digest: str,
                   revision: str | None = None) -> BinaryIO:
        """Return retained bytes at a pinned revision in a caller-owned tempfile.

        The HTTP layer must authorize the requested record/file descriptor first;
        digest knowledge alone does not establish application access.
        """
        repo = self._repo(project_id)
        if not isinstance(digest, str) or not _CONTENT_SHA.fullmatch(digest):
            raise NotFound("The requested asset identifier is invalid.")
        head = self._resolve_revision(repo, revision)
        root = self._tree_entries(repo, head)
        entries = self._subtree_entries(repo, root, "assets")
        entry = entries.get(digest)
        if entry is None:
            raise NotFound("The material was not retained in this project revision.")
        if entry[:2] != ("100644", "blob"):
            raise StoreError("The retained asset entry is invalid.")
        oid = entry[2]
        size = self._object_sizes(repo, [oid])[oid]
        if size > _MAX_FILE_BYTES:
            raise LimitExceeded("The retained file exceeds this binding's file limit.")
        output = None
        try:
            output = tempfile.TemporaryFile(mode="w+b")
            self._git(repo, "cat-file", "blob", oid, output_file=output)
            if output.tell() != size:
                raise StoreError("The retained file could not be read completely.")
            output.seek(0)
            hasher = hashlib.sha256()
            for block in iter(lambda: output.read(64 * 1024), b""):
                hasher.update(block)
            if hasher.hexdigest() != digest:
                raise StoreError("The retained file does not match its SHA-256 digest.")
            output.seek(0)
            return output
        except OSError:
            if output is not None:
                output.close()
            raise StoreError("The retained material could not be buffered safely.") from None
        except BaseException:
            if output is not None:
                output.close()
            raise

    def bundle_file(self, project_id: str) -> BinaryIO:
        """Return a complete reachable-history bundle without buffering it in RAM."""
        repo = self._repo(project_id)
        self._head(repo)
        output = None
        try:
            output = tempfile.TemporaryFile(mode="w+b")
            self._git(repo, "bundle", "create", "-", _MAIN, output_file=output)
            output.seek(0)
            return output
        except OSError:
            if output is not None:
                output.close()
            raise StoreError("The history bundle could not be buffered safely.") from None
        except BaseException:
            if output is not None:
                output.close()
            raise

    def bundle(self, project_id: str) -> bytes:
        """Compatibility helper. HTTP downloads use the streaming bundle_file."""
        with self.bundle_file(project_id) as output:
            return output.read()
