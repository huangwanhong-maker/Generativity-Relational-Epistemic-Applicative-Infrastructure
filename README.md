# Applicative infrastructure

**Class:** Implementation and operation guide  
**Status:** Experimental shared infrastructure and independent domain applications

**Source repository:** [Generativity-Relational-Epistemic-Applicative-Infrastructure](https://github.com/huangwanhong-maker/Generativity-Relational-Epistemic-Applicative-Infrastructure)

This repository provides common record and Git-storage packages, repeatable local setup tools and two application submodules. It implements parts of the Generativity Standards Program's research and working specifications while keeping application behavior, protocol evidence and programme authority distinct.

The current domains are a generalized visual record workspace and Generative Relational Academia. Each has a separate entry point, account database, runtime and source history. Academia retains its native GRRP model; consolidation and shared hosting do not establish interoperability with the generalized protocol.

## Repository responsibilities

~~~text
applicative_infrastructure/                 This Git repository
├── common/                                Shared code and operation guidance
│   ├── packages/gsp_record_protocol/       Model validation, transactions and modules
│   ├── packages/gsp_git_store/             Git storage and atomic publication
│   ├── design/                            Architecture and migration evidence
│   ├── conformance/                       Verification scope and reproduction
│   └── tools/                             Independent setup and launch tools
├── gr_generalized_application/            Application Git submodule
│   └── web_application/                   Python web application and browser interface
├── gr_academia_application/               Application Git submodule
│   ├── web_application/                   React, Fastify and TypeScript packages
│   ├── domain_packages/grrp/              Native Python domain protocol and CLI
│   └── provenance/                        Original source history and import manifest
└── .runtime/                              Ignored; never part of a source commit
    ├── generalized/                       Accounts and user project Git repositories
    ├── academia/                          Accounts, index, native records and keys
    └── environments/                      Separate Python environments
~~~

| Area | Responsibility |
|---|---|
| [Common packages](common/README.md) | Reusable implementation with no dependency on a domain application |
| [Generalized application](gr_generalized_application/README.md) | General records, visual graphs, event-defined spacetime and trajectories, modules, retained files and project transactions |
| [Academia application](gr_academia_application/README.md) | Scholarly trajectories, native GRRP operations and domain workspaces |
| [Verification](common/conformance/README.md) | Tests and the limits of their interoperability claims |

This repository is itself a submodule of the programme. Programme standards, specifications, manuscripts, governance and ADRs remain canonical in the parent repository. Links such as the [Programme Brief](../PROGRAMME_BRIEF.md), [GR-SPEC-120](../specifications/GR-SPEC-120-information-model/GR-SPEC-120.md), [GR-SPEC-130](../specifications/GR-SPEC-130-interchange/GR-SPEC-130.md) and [consolidation decision](../decisions/ADR-0009-applicative-infrastructure-consolidation.md) resolve in that complete checkout. An infrastructure-only clone can run the applications without those publication files.

## Clone and maintain submodules

With GitHub SSH access configured, obtain this repository and both application submodules:

~~~powershell
git clone --recurse-submodules git@github.com:huangwanhong-maker/Generativity-Relational-Epistemic-Applicative-Infrastructure.git applicative_infrastructure
cd applicative_infrastructure
~~~

The application sources are hosted independently as [Generalized-Generativity-Relational-Social-Science-Application](https://github.com/huangwanhong-maker/Generalized-Generativity-Relational-Social-Science-Application) and [Generative-Relational-Academia-Application](https://github.com/huangwanhong-maker/Generative-Relational-Academia-Application). For the complete programme, recursively clone [Generativity-Epistemic-Infrastructure](https://github.com/huangwanhong-maker/Generativity-Epistemic-Infrastructure) instead. The [programme Git guide](https://github.com/huangwanhong-maker/Generativity-Epistemic-Infrastructure/blob/main/docs/development/git_repository_layers.md) covers SSH configuration and publishing.

Each application is pinned to a specific commit. After changing an application, commit its source there, then commit the changed submodule reference here. If this repository is checked out inside the programme, commit its updated reference in the programme as well. Common-package and launcher edits belong directly to this repository. Use the following to inspect the selected revisions:

~~~powershell
git submodule status --recursive
~~~

After updating this repository, use `git submodule sync --recursive` and `git submodule update --init --recursive` to restore its committed application revisions. Publish application commits before the infrastructure commit that references them; publish infrastructure before a programme commit that references it. A submodule may have a detached HEAD, so select a development branch before committing application changes.

Source submodules are distinct from the Git repositories that applications create for users' records. Private project repositories belong in runtime storage and are excluded from source version control.

## Setup

Use Python 3.11 or later and Git on PATH. Academia additionally needs Node.js/npm; Node 22.12 or later on the Node 22 release line is suitable for the current frontend tooling and matches the validated major version. Installation downloads declared dependencies. Commands below run from **this infrastructure directory**:

~~~powershell
python common/tools/setup_application.py generalized --dev
python common/tools/setup_application.py academia --dev
~~~

Run either command independently if only one application is needed. Use Python 3's local command name on Linux/WSL. On Windows the setup tool uses extended Python paths for deeply nested dependencies without changing system settings.

Setup creates separate environments under the ignored runtime environment directory. Generalized setup installs its requirements and the two editable common packages; its interface has no Node build. Academia setup installs its native Python package, runs npm's lockfile installation, and builds its protocol, server and client. Repeating setup can reuse an existing environment. Omit the development option when Python test dependencies are unnecessary; academia still needs its declared TypeScript build dependencies.

Cloning an application alone does not reproduce this layout or install shared tooling. The infrastructure checkout is the supported combined development environment. Domain README files describe lower-level entry points and dependencies.

## Launch independently

Run each application in its own terminal:

~~~powershell
python common/tools/run_application.py generalized
python common/tools/run_application.py academia
~~~

| Application | Default address | Default runtime | Session cookie |
|---|---|---|---|
| Generalized | http://127.0.0.1:8000 | .runtime/generalized/ | gsp_session |
| Academia | http://127.0.0.1:8001 | .runtime/academia/ | gra_session |

The launcher accepts host and port arguments and defaults to loopback. For example:

~~~powershell
python common/tools/run_application.py generalized --port 8002
~~~

Ctrl+C stops the selected process. The launcher resolves paths from its own location, so invoking it by absolute path works from another directory.

Both applications have their own accounts; no shared sign-on or shared project authority is introduced. Generalized registration is available in its interface. Academia preserves its account-provisioning behavior and has an [operator CLI](gr_academia_application/README.md#accounts) when registration is closed. No demonstration account or default password is installed.

Separate ports and cookie names prevent ordinary naming collisions; ports do not isolate browser cookies. Local launch commands are development/operator entry points rather than a production service manager. Local previews created during migration have ignored process logs under the programme's build output.

## Configuration

Explicit path overrides passed to the launcher must be absolute. Use separate locations for unrelated deployments.

| Variable | Purpose |
|---|---|
| GSP_DATA_DIR | Generalized account database and project repositories |
| GSP_COOKIE_SECURE | Set to 1 when generalized is served exclusively through HTTPS |
| GSP_TRUSTED_HOSTS | Generalized accepted request hostnames |
| GRA_RUNTIME | Academia parent runtime directory |
| GRA_RECORDS | Academia native record tree; overrides the derived default |
| GRA_DB | Academia account/index database; overrides the derived default |
| GRA_PYTHON | Single absolute Python interpreter path with native grrp installed |
| GRA_CLIENT | Academia compiled client directory |

The launcher selects host and port through its command arguments. Domain guides document additional direct-server settings. A source checkout or environment rebuild does not create a copy of an existing runtime.

## Data and recovery

Both SQLite databases contain retained account information. Academia's database also has rebuildable indexes, but that does not make the database disposable. A complete backup includes the matching account database, project repositories, retained material, record-local keys and relevant SQLite journals. Stop the application's writer before a filesystem copy, or use a specifically verified online backup procedure. Treat backup archives as private data.

The application relocation preserved four accounts, three projects, record bytes, native keys and reachable Git histories. It did not convert the legacy generalized project or academia's native records. Detailed scope and checks are in the [migration verification](common/design/migration_verification.md) and [independent audit](common/design/migration_audit.md).

The original migration workspace retains complete source/runtime ZIP backups under ignored programme build/private-backups/; build/migration-current-backup.txt identifies that workspace's backup set. Former local source trees remain under build/retired-webapp/ and build/retired-gsp-record-protocol/. These are local recovery artifacts and do not accompany a clone. The original academia checkout and runtime remain unchanged.

For rollback, stop the new writer before restoring a matched runtime backup and application revision. Restore accounts and record custody together. Do not run two writers against the same restored data directory. Recreate virtual environments after moving their source/environment layout; retaining their old files does not make them portable.

## Verification

Install development dependencies first. From this directory on Windows PowerShell:

~~~powershell
& ./.runtime/environments/generalized/Scripts/python.exe -m pytest -c gr_generalized_application/web_application/pytest.ini gr_generalized_application/web_application/tests common/packages/gsp_record_protocol/tests common/packages/gsp_git_store/tests --basetemp .runtime/test-output/generalized -q
& ./.runtime/environments/academia/Scripts/python.exe -m pytest gr_academia_application/domain_packages/grrp/tests --basetemp .runtime/test-output/academia -q
npm.cmd --prefix gr_academia_application/web_application test
npm.cmd --prefix gr_academia_application/web_application run build
~~~

Use bin/python instead of Scripts/python.exe and npm instead of npm.cmd on POSIX. Pytest's temporary-output directory is disposable and must never name retained runtime data. Prefer a short checkout/test path on Windows because Git clone tests can encounter path-length limits.

Set the GSP_BROWSER environment variable to msedge to include the generalized browser journeys using installed Edge; the [browser test guide](gr_generalized_application/web_application/TESTING.md) describes alternatives. The migration recorded 427 passing tests and one platform-specific skip across the applications and shared packages. These dated checks verify observed behavior and do not establish cross-application semantic equivalence.

## Current boundaries and further domains

The generalized application consumes the common packages. Academia currently retains separate Python and TypeScript GRRP implementations. A future adapter needs explicit mappings for identity, signed bytes, authority, disclosure, modules, partial mappings and retained files before interoperability can be claimed.

The applications remain experimental. Generalized sharing, recovery, selective erasure and formal review workflows remain limited; academia retains known identity/custody questions and six affected npm packages in its [dated relocation assessment](gr_academia_application/provenance/relocation_validation.md). Review domain-specific limitations before exposing either service beyond its local operating context.

A future domain receives its own repository/submodule, entry point, runtime, profile and operation guide. Extract further common code when a concrete shared interface and preservation tests justify it. Domain history and concepts remain traceable rather than being flattened into a universal application schema.

## Contributing and license

Use [CONTRIBUTORS.md](CONTRIBUTORS.md) to maintain contribution attribution. Keep shared packages independent of domain application imports, add meaningful verification for behavioral changes, and update the programme's decisions and specifications when an implementation exposes a conceptual or interoperability gap.

Project-authored material is available under the [MIT License](LICENSE), with copyright held by the contributors recorded in [CONTRIBUTORS.md](CONTRIBUTORS.md). [LICENSE.md](LICENSE.md) explains scope, historical additional grants and third-party exclusions. Each application submodule has its own license and contributor record. User-created records, files and research material retain their own rights.
