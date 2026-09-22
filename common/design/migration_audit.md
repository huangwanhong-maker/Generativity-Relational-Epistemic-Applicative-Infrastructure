# Independent migration audit

**Document class:** Informative implementation verification report  
**Date:** 2026-09-22  
**Status:** Bounded migration checks passed; identified provenance discrepancy corrected and rechecked  
**Scope:** Relocation into `applicative_infrastructure`, without semantic conversion of retained records

This audit independently read the original and relocated data, inspected source provenance, resolved installed packages, evaluated launcher configuration, and checked the two live entry points. It did not create accounts, edit records, change keys, run a reindex, or alter retained user data. Account rows were compared internally; credentials, account identities, record text and key bytes were not included in the report or tool output.

## 1. Retained runtime

The generalized source was the earlier local `webapp/.data`. The academia source was the original application's ignored `web/packages/server/data`, which contains both records and an account database. The destinations were `.runtime/generalized` and `.runtime/academia`. Source copies remained present when the comparisons were performed. The earlier local web application and packages were subsequently retired into ignored `build/` storage after the programme's separate source-hash guard; this audit's comparisons preceded that retirement.

For each retained record tree, the audit compared relative file inventory, byte length and SHA-256. It then compared Git reference identifiers and reachable commit counts independently of the filesystem comparison. Databases were opened read-only; `PRAGMA quick_check`, table counts and complete `users` rows were compared without printing row contents.

| Check | Generalized | Academia |
|---|---|---|
| Retained record-tree files | 11 source; 11 destination | 299 source; 299 destination |
| File inventory and every compared byte digest | Equal | Equal |
| Missing, additional or changed record-tree files | 0 / 0 / 0 | 0 / 0 / 0 |
| Retained project repositories | 1 | 2 |
| Git reference sets | Equal | Equal for both projects |
| Reachable commits | 2 at both locations | 26 and 8, unchanged at both locations |
| Source and destination database quick check | `ok` | `ok` |
| Complete account-row comparison | Equal; 1 account | Equal; 3 accounts |
| Project-row counts | 1, unchanged | 2, unchanged |

The academia index also contained five trajectories and 29 search rows at both locations when inspected. These derived counts are a consistency observation, not a substitute for preserving the three account rows. Starting that application can rebuild derived index material; the audit therefore compared account content separately.

The generalized project still declares `gsp-workspace/0.1`, contains its one retained record, and has no fabricated transaction receipts or material assets. Its source main reference is unchanged. Filesystem relocation did not perform the separate `project.migrate` operation or retrospectively assign structured relation semantics.

The academia record-tree comparison includes the original Git directories, native GRRP material, project metadata, key-related files and mutable project workspaces. This demonstrates byte preservation for those files at the comparison time. It does not independently validate every historical signature, claim, permission or private-key custody arrangement.

## 2. Installed packages and application boundaries

The generalized Python environment imports `gsp_protocol` and `gsp_git_store` from the relocated `common/packages` trees. The observed protocol identifier is `gsp-record-protocol/0.2`. The academia environment imports `grrp` from `gr_academia_application/domain_packages/grrp`; the generalized protocol package is not installed in that environment. No observed editable import resolves to the retired local package locations or the external academia source repository.

These results support separation of the application environments and retention of academia's native protocol. They do not demonstrate that academia implements the generalized transaction model or that the two native record formats are interchangeable.

The common launcher's default command and path configuration was evaluated from the programme directory and its parent. The resulting configurations were identical. Default data, database, client-build and Python paths were absolute; relative `GSP_DATA_DIR` and `GRA_DB` overrides were rejected. Default ports are 8000 for generalized and 8001 for academia.

After the launcher update, an absolute `GRA_RUNTIME` override routed both records and the database beneath that selected root, while a relative override was rejected. The academia native runtime resolver was also evaluated from two working directories and returned identical default paths. A Python executable path containing spaces remained one command argument. These checks evaluated configuration only and created no alternate runtime.

The academia server and account CLI use the same runtime-path resolver. `GRA_PYTHON` identifies one executable argument, avoiding the old ambiguity of splitting an executable path containing spaces. The legacy `GRA_GRRP` fallback remains a separate documented compatibility behavior.

The source declares distinct cookie names, `gsp_session` and `gra_session`, and independent session implementations. This prevents accidental name collision. Different localhost ports do not themselves establish browser-cookie isolation or a security boundary between applications on the same host.

## 3. Live, read-only observations

Both `http://127.0.0.1:8000/` and `http://127.0.0.1:8001/` returned HTTP 200 with HTML. Those requests set no cookie. The generalized public capability endpoint returned `gsp-record-protocol/0.2` and `gsp.general/0.2`. Both listeners were bound to `127.0.0.1` when inspected.

These checks establish that both entry points respond and that the generalized endpoint identifies the expected protocol. This audit did not log into the retained accounts or submit mutations to user data. Browser workflows, domain tests and temporary-data mutation tests are separate verification evidence.

## 4. Source provenance

All 35 entries in the common relocation manifest match the archived pre-relocation source bytes held in the private source backup. Their source-path inventory contains no runtime, account database, environment or private-key paths under the checked path patterns.

For academia, the source repository remains at the recorded commit with a clean working tree. The preserved history bundle matches its recorded SHA-256, and an independent `git bundle verify` reports a complete history. The all-reference history contains 131 distinct tracked paths. The broad key-path check identified a historical `.grrp/keys/self.pub` public-key path; it found no runtime database, environment file or private-key path under the bounded path rules. This is not a comprehensive content or secret scan.

**AUDIT-01 — Corrected and closed.** The initial import manifest labeled archive-export bytes as committed Git blob bytes. Independent `git cat-file blob` comparisons found 56 of 121 entries different from that claim. The history bundle and runtime preservation comparisons were unaffected. The corrected [import manifest](../../gr_academia_application/provenance/import_manifest.json) distinguishes raw Git blob bytes, archive-export bytes, pre-edit imported bytes, source checkout bytes and final relocated bytes. The [initial manifest](../../gr_academia_application/provenance/import_manifest.initial.json) remains as explicitly superseded evidence.

The audit independently re-read all 121 raw blobs, generated a fresh archive in memory, compared exported entries against the retained import baseline, and checked final destination hashes. Raw hashes and byte lengths, corrected committed-byte aliases, fresh archive hashes/lengths, retained initial baseline and final destination hashes all matched. All 56 raw-to-export differences were explained by LF-to-CRLF conversion. This closes the inaccurate provenance label while preserving the observed import history rather than rewriting it as an earlier exact-blob copy.

Public source provenance is separate from private runtime migration evidence. Private backups and inventories remain under ignored `build/`; application state and recreated environments remain under ignored `.runtime/`. Neither belongs in the public source import or its history bundle. Git checks confirmed that both runtime database paths and the private-backup pointer are ignored and untracked.

## 5. Limits

The comparisons describe a specific migration and observation time. They are not a continuing backup service, a full disaster-recovery exercise, a deployment-security assessment, an independent signature audit, or a whole-GR conformance determination. Subsequent legitimate use can change the destination database and repositories while leaving this recorded migration result valid for its stated scope.
