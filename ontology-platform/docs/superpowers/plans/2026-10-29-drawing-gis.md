# Drawing GIS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn five actual construction drawings into auditable spatial records and a map-facing API.

**Architecture:** Versioned evidence package, independent paper-coordinate PostGIS tables, authenticated read API and offline mirror. Preserve farm UUIDs and distinguish source statements from surveyed geography.

**Tech Stack:** Python 3.12, existing FastAPI/SQLAlchemy, PostgreSQL/PostGIS, SQLite mirror, vanilla JS adapter.

**Spec:** ../specs/2026-10-29-drawing-gis.md

## Global Constraints
- Five independent PDF paper spaces, unit pt, no invented CRS or measured dimensions.
- Existing real farm UUIDs retained, synthetic records excluded, no automatic name merge.
- Every count and extraction limitation has evidence; no claim of exhaustive OCR without it.
- All requested reviewed deliverables synced to authorized public GitHub main; no runtime data/credentials.

## Review Focus
- Duplicate annotation labels across drawings must not merge identities.
- Unknown units and drawing ratios must not become actual square metres.
- Invalid or stale pagination must fail instead of silently omitting records.
- Replaying a dataset must be harmless; same version with changed content rejected atomically.
- Auth failure and missing GIS storage must not return a misleading empty success.

### Task 1: Auditable package
Files: `scripts/build_drawing_gis.py`, `datasets/drawings/*`, `backend/src/lzo/gis/drawing_package.py`, `backend/tests/unit/test_drawing_package.py`.
Interfaces: `validate_package(dict)->dict`; package contains drawings, features, annotations, reviews, coverage, immutable content_sha256.
- [x] Test finite/closed bounded paper geometry, duplicate identities, unknown units, canonical digest tampering, synthetic exclusion.
- [x] Observe failing test, implement validation and deterministic builder, rerun tests.
- [x] Copy only vetted derived inputs; compute source hashes from five original PDFs; review each image and retain explicit omissions.

### Task 2: Stored drawing GIS and API
Files: `backend/src/lzo/gis/drawing_store.py`, `drawing_router.py`, `database/gis/005_drawings.sql`, `scripts/import_drawing_gis.py`, `backend/tests/unit/test_drawing_store.py`, `test_drawing_http.py`, `backend/tests/integration/test_drawing_postgis.py`.
Interfaces: `DrawingStore(engine).import_package(package)` atomically imports; `.drawings()`, `.features(drawing_id,kind,bbox,limit,cursor)`, `.feature(id)`, `.annotations(drawing_id,limit,cursor)`, `.coverage()` are read methods.
- [x] Test replay/conflict/rollback, bounded filtering, complete stable pagination, UUID detail and honest coordinate response; observe RED.
- [x] Add tables, repository and authenticated router using global internal view; append migration and wire main; observe GREEN.
- [x] Run real PostGIS integration in owned runtime and import actual reviewed package; report geometry validity separately.
- [x] Export OpenAPI and sync client contracts.

### Task 3: Map consumption and delivery
Files: `examples/drawing-map/*`, `docs/gis/drawings.md`, `docs/gis/verification.json`, `README.md`.
- [x] Test JS conversion/identity and complete page retrieval against API contract; implement browser viewer and farm adapter.
- [x] Run relevant tests and baseline unit suite; retain pass/fail/unavailable distinctions.
- [x] Independent final review, fix material issues and inspect public data paths.
- [ ] Commit exact changed paths, push without force and verify remote.
- [ ] Verify remote commit and selected file hashes; leave local deliverables accessible outside transport directory.
