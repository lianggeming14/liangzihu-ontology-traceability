# Fish sample RDF implementation plan

> For agentic workers: execute the RDF tasks below using the test-first workflow; the parent agent coordinates independent UI and map reviewers.

**Goal:** Rebuild the existing reviewed fish sample as an actual, queryable RDF ontology with classes, instances, typed values, navigable relationships and explicit provenance.

**Architecture:** Read the existing `fish_review_10pct_v1` PostgreSQL sample in one read-only repeatable-read transaction. Generate deterministic N-Triples in the distinct `urn:lzo:fish-review:sample:v1:` namespace, load only a new content-addressed named graph in the isolated test Fuseki dataset, and verify the complete graph before producing navigation snapshots.

**Tech stack:** Python 3.12, SQLAlchemy/psycopg, RDFLib terms and parser, HTTPX, PostgreSQL/PostGIS and Apache Jena Fuseki.

## Boundaries and model

- Source: 20,606 physical sample rows, 20,548 usable records, 68,343 relation-ledger entries. These are sample records; `accepted` means structural input acceptance, not formal platform adoption.
- The 64 source table classes are OWL classes below explicit role classes (business entities, observations, index records and reference structure). Labels, source column definitions, units and datatypes are retained.
- Every usable record receives `rdf:type` and typed per-table datatype properties. Existing sample UUIDs stay unchanged inside the new sample namespace. Null values remain missing and are declared explicitly as missing fields; they are not zero or invented literals.
- Resolved relationships receive object-property triples and exact inverse properties. Every relationship, including unresolved/external references, has a separate provenance record retaining source field, target identifiers, resolution and list position. Unresolved references do not create fake target instances.
- All physical source rows receive separate `prov:Entity` records, with original field strings, structural status, issues and sampling reason. Canonical instances link to their exact source row. The input ZIP remains pinned by SHA-256.
- The graph and every instance carry `sample_not_formally_adopted`; synthetic data and imported-unverified weather remain distinguishable. Nothing writes the existing formal graphs, approval records or importer queues.
- The graph name includes the pinned package hash and generated content digest. An existing graph is verified and reused, never cleared or overwritten with different contents.

## Files and interface

- `scripts/fish_rdf_sample.py`: deterministic RDF projection and navigation snapshot functions.
- `scripts/build_fish_rdf_sample.py`: guarded read-only SQL extraction, isolated Jena upload and complete graph verification.
- `scripts/check_fish_rdf_sample.py`: executable independent unit checks.
- `docs/fish/ontology-review/data/manifest.json`: concept hierarchy, stable IRIs, exact counts, graph identity and Jena verification.
- `docs/fish/ontology-review/data/classes/<table>.json`: every instance with typed values, outgoing/incoming links and provenance; supports frontend pagination.
- `docs/fish/ontology-review/rdf-readback.json`: source counts, full RDF digest comparison and SPARQL checks.
- Raw N-Triples and byte-preserving source artifacts are generated in ignored `.runtime`; distribution of a compressed ontology artifact is decided by the parent publication scope.

The snapshot contract is `fish-rdf-review/1`. Concept entries expose `iri`, `label`, `parent_iri`, `children`, `table`, `role`, `instance_count`, `total_instance_count`, and `instances_path`. Instance entries expose `iri`, `id`, `label`, `class_iri`, `properties`, `outgoing`, `incoming`, `unresolved_relations`, and `provenance`. Every link carries real source/target IRIs. Snapshot values must come from the RDF that was actually read back from Jena.

## Test and execution results

- [x] Test numeric precision, missing values, domain class hierarchy, inverse links, unresolved targets and physical duplicate source rows. Decimal and boolean regression cases were observed failing before correction.
- [x] Implement the RDF projector, preserving all source-row and relation-ledger identity, including eight extra source columns beyond the 1,346-field source dictionary.
- [x] Reject package mismatch, unknown target, class mismatch and non-local/non-review graph targets.
- [x] Extract the actual sample in a `REPEATABLE READ, READ ONLY` transaction and generate N-Triples and expected term inventories.
- [x] Import four separate graphs and compare every returned RDF term; execute SPARQL counts and inverse/orphan checks.
- [x] Run actual pySHACL on all 20,548 canonical sample instances, 1,354 datatype constraints and declared relation target-class constraints; zero violations. Original strings are retained but are not forced into semantic types.
- [x] Derive public navigation exclusively from successfully verified Jena readback. Check all 79,002 resolved source links and all 10,495 demo links in both directions; zero dangling or mistyped links.
- [x] Keep formal importer, approvals and workers untouched. The 971 pre-existing non-review graphs retained their counts.

## Final graph boundaries

The named graph whitelist is in `data/manifest.json` and is refreshed only after verification. Four graphs contain **2,720,969** RDF triples in total:

| Graph | Contents | Triples |
|---|---|---:|
| Sample | 20,548 typed instances, 20,606 raw provenance rows, 68,343 relation records | 2,183,946 |
| Map | 284 independently sourced spatial representations and six layers | 18,546 |
| Demo | 10,475 explicitly synthetic activity assignments and 20 pond profile template links | 125,954 |
| Drawing evidence | 6,297 original drawing evidence instances, including 3,202 measurements and 163 exact-source-UUID map bridges | 392,523 |

The shared canonical domain hierarchy includes aquaculture, ponds, fields, production events, observations, finance, equipment and documents. Source table/document classes remain leaves. A drawing's pond dossier is a document representation; it does not create a second physical pond or imply identity with a synthetic source pond.

The 20 drawing pond boundaries are linked to six synthetic pond profiles for explicitly authorized demonstration. Activity assignments are balanced independently per source table. These links use their own graph and predicates, preserve every original `pond_id`, and never copy synthetic depth/volume into a real map object's measurements.

Public snapshots contain **27,135** navigable instances in **112** concepts. The **84** deterministic gzip shards total **10,055,720 bytes**; the largest is **1,780,301 bytes**. Full raw strings and N-Triples remain in ignored `.runtime`; only normalized public snapshots, provenance locators, vocabulary, shapes and reports are published.

## Rebuild and verification

Use the existing locked platform dependencies and private local review configuration. This command reads the existing SQL sample, creates/reuses independent content-addressed review graphs, validates them and exports all four graphs' navigation:

```sh
python scripts/build_fish_rdf_sample.py --config config/fish-review.example.json
python scripts/verify_fish_rdf_navigation.py
```

The drawing extension is also independently replayable after the first three graphs pass:

```sh
python scripts/extend_fish_rdf_drawings.py
```

Standalone checks: `check_fish_rdf_sample.py` (12), `check_fish_map_rdf.py` (6), `check_fish_demo_rdf.py` (4), and `check_fish_drawing_rdf.py` (4). Actual service evidence is recorded in `rdf-readback.json`, `shacl-readback.json`, and `navigation-readback.json`; standalone tests do not replace these real PostgreSQL/Jena checks.

Jena canonicalizes decimal lexical forms. The exporter emits exact canonical decimal strings without floating-point conversion and preserves the original text separately. The initial exact-term mismatch was rejected; only the subsequently verified graphs are in the published whitelist. Unresolved source relationships remain visible as 67 unresolved records, without invented target instances. Local image coordinates remain unregistered and are not presented as surveyed geography.

## Review focus

Literal precision must survive Jena serialization; structural admission must never be presented as formal acceptance; relation list entries must not overwrite each other; unresolved edges must remain visible without fake instance nodes; re-running must not overwrite an existing graph or touch a formal graph.
