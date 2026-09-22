# Application consolidation verification

**Class:** Implementation verification report  
**Status:** Relocation completed, 2026-09-22; experimental applications

[ADR-0009](../../../decisions/ADR-0009-applicative-infrastructure-consolidation.md) records the approved repository boundary. The [operation guide](../../README.md) provides setup and launch commands. This report describes source/runtime relocation; it does not assert semantic equivalence between academia GRRP and the generalized record protocol.

## Source and history

The 35-file generalized application/protocol baseline is recorded in [relocation_manifest.json](relocation_manifest.json), with original paths, destination paths and before/after SHA-256 digests. Original source hashes were rechecked before retirement. The record protocol implementation and extracted Git-store implementation remain byte-identical. Changes concern imports, runtime defaults, documentation and test/artifact locations; one storage test uses a shorter temporary clone destination for Git for Windows.

The old `webapp/` and `packages/gsp_record_protocol/` trees are retained at ignored `build/retired-webapp/` and `build/retired-gsp-record-protocol/`. They are rollback material, not alternate active implementations. Environments are recreated in the new location; a retired virtual environment is not portable merely because its files are retained.

Academia's source was imported from commit `b98730b46eca5fdf441937aef0180f5b3d4f94dd`. Its 121 tracked source files, original README and component licensing notices are retained with a verified complete source-history bundle. The original checkout remains clean at the same commit. Its [provenance guide](../../gr_academia_application/provenance/README.md) identifies source-byte representations and the deliberate relocation edits. No outer-repository history was rewritten or merged.

## Retained private data

The old generalized writer was stopped before transfer; no academia source writer was running. SQLite databases were copied through the backup API from read-only source connections. Full logical database digests matched immediately after copying and `quick_check` succeeded. Non-database file inventories were compared by relative path and SHA-256; transient SQLite shared-memory files were excluded from file-byte comparison.

| Property | Generalized | Academia |
|---|---|---|
| Existing accounts | 1 preserved | 3 preserved |
| Existing projects | 1 preserved | 2 preserved |
| Retained content | 1 legacy record | 5 native trajectories |
| Reachable project commits | 2 preserved | 26 and 8 preserved |
| Record repository bytes and references | Exact match | Exact match |
| Identity and authentication material | Existing database/session material retained | Existing account data and native key material retained |
| Semantic conversion | None; schema 0.1 retained | None; native GRRP retained |

The complete source/runtime ZIPs and detailed comparisons remain under ignored `build/private-backups/`, identified by `build/migration-current-backup.txt`. The ZIP archives are the authoritative backup artifacts; an earlier partial filesystem copy in that backup set is not a complete backup. Reports and archives contain private material and are not included in source provenance or the project index. The original academia checkout and data remain unchanged.

Academia startup rebuilds its derived search index in the new database. Consequently later database-file hashes are not expected to equal the offline backup; the independent audit compared complete account rows and native record trees after startup. No migration test accounts or demonstration records were added to retained user databases.

## Executed verification

| Check | Observed result |
|---|---|
| Generalized application plus common packages | **128 passed**, including three Edge browser journeys |
| Academia Python | **208 passed, 1 skipped**; POSIX editor fallback skipped on Windows |
| Academia TypeScript protocol | **43 passed** |
| Academia server | **48 passed**, including runtime path checks |
| Academia production build | Protocol, server and client passed |
| Academia deep-path write smoke | Separate test project/question created; graph read and GRRP validation passed |
| New live entry points | HTTP 200 at ports 8000 and 8001; expected protocol/account endpoints respond |
| Academia live browser | Edge renders the retained project listing with no uncaught JavaScript errors; screenshot inspected |
| Common launcher | Paths remain stable across working directories; absolute runtime overrides honored; relative overrides rejected |
| [Independent audit](migration_audit.md) | Account rows, record inventories, Git references, source provenance and import locations examined separately; provenance-label finding corrected and closed |

All active programme/application guide links resolve. Historical publication and imported historical document links were excluded from this active-navigation check. The source index excludes runtime databases, keys, environments and dependency trees. All three authoritative backup ZIPs passed archive CRC checks.

The combined generalized/common suite ran from the new environment with `GSP_BROWSER=msedge` and `--basetemp build/gm`. Academia's detailed commands, environment information and scope are in its [validation report](../../gr_academia_application/provenance/relocation_validation.md). Reproduction guidance is in [common verification](../conformance/README.md).

## Limits and subsequent work

The consolidation preserves two independent account and protocol systems. Shared code is available to future domains; academia does not yet consume the generalized protocol or Git transaction implementation. A domain mapping must preserve native identifiers, signed bytes, registrations, disclosure and unmapped content before interoperability can be claimed.

The inherited academia lockfile has six reported affected npm packages, documented in its validation report. Dependency maintenance, identity/custody findings from the earlier source review, deployment isolation, measured accessibility and a full operational restoration rehearsal remain separate work. Different ports and cookie names prevent ordinary namespace collisions; ports do not isolate browser cookies. Current services bind to loopback by default.

These checks establish the observed migration behavior. They do not adopt a Standard, certify production security, validate institutional practice or warrant the truth of recorded claims.
