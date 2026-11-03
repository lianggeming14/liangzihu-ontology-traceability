# Drawing semantics implementation plan

> **For agentic workers:** Use executing-plans / subagent-driven-development for the assigned independent files.

**Goal:** Extract meaningful dimensions and relationships from all five drawings and persist them in existing GIS and ontology stores.

**Architecture:** Reviewed metric evidence → reproducible typed semantic bundle and object profiles → existing governed semantic services → actual PG/Jena persistence and map-facing query.

**Tech Stack:** Existing Python 3.12, FastAPI, SQLAlchemy, PostGIS, RDF/Jena; no new framework.

**Spec:** ../specs/2026-11-03-drawing-semantics-design.md

- [x] Reinspect five drawings; preserve scale conflicts, depth/elevation distinctions, explicit feature links and project aggregates in metric-review JSON.
- [x] Test then implement metric parsing, polygon perimeter/area, local calibrated estimates, duplicate evidence grouping, deterministic subject/quantity/relationship identities.
- [x] Generate reviewed source statement inventory, object profiles and typed ontology bundle with coverage by drawing/quantity/class; preserve unresolved extraction gaps explicitly.
- [x] Implement formal ontology import with existing object/attribute/source/evidence services; preserve UUID, actual provenance, idempotency and required approval policy.
- [x] Add read endpoints and profile preview; test paging, filters, mixed-version refusal and source links.
- [x] Persist real derived package in PostGIS and query back quantities/relations with replay and app-role privilege checks.
- [ ] Actual formal ontology PG/Jena import: waiting for verified operator, owner scope and required independent schema approval. No identity or approval fabricated; reviewed schema and validation artifacts supplied.
- [x] Independently review data and implementation, fix discrepancies; run relevant unit/integration/browser checks.
- Delivery step: sync reviewed artifacts to authorized public GitHub main, verify remote hashes, and mirror local deliverables. The final commit/hash receipt is reported separately at delivery to avoid a self-referencing commit hash.
