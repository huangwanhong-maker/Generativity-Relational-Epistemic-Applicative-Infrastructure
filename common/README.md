# Common implementation infrastructure

**Class:** Implementation guide  
**Status:** Experimental shared packages

| Component | Responsibility |
|---|---|
| [gsp_record_protocol](packages/gsp_record_protocol/README.md) | Independent record/module/transaction validation, candidate preparation, schema, graph projection and CLI |
| [gsp_git_store](packages/gsp_git_store/README.md) | Atomic Git storage, retained material, receipts, history and exports |
| [tools](tools/) | Explicit setup and independent application launch |
| [verification](conformance/README.md) | Shared package and application regression commands; future independent interoperability checks |
| [design](design/) | Relocation provenance and migration evidence |

Canonical technical texts remain [GR-SPEC-120](../../specifications/GR-SPEC-120-information-model/GR-SPEC-120.md) and [GR-SPEC-130](../../specifications/GR-SPEC-130-interchange/GR-SPEC-130.md), with their motivating Working Drafts at the programme root. The protocol package owns the single machine-readable schema resource for its version. No copied normative text is maintained here.

The Git package does not depend on Flask, accounts or the protocol validator. The protocol package does not depend on Git or either application. Each receiving application remains responsible for authentication, authority checks, applicable profile semantics and client behavior. Academia's native GRRP and TypeScript protocol packages remain domain-specific; their new location does not turn them into the general shared protocol.
