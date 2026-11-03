# Drawing semantics in the governed ontology

`scripts/import_drawing_ontology.py` imports `drawing-semantics/1` bundles into
the existing PostgreSQL semantic objects/assertions/supports/type declarations
and the existing Jena projection. It creates no additional ontology tables.

The default invocation only validates. It does not load service settings or
connect to a database. The content hash is SHA-256 of canonical UTF-8 JSON with
the `content_sha256` field omitted, sorted keys, compact separators, unescaped
Unicode and finite JSON numbers.

```powershell
python scripts/import_drawing_ontology.py --report docs/gis/ontology-validation.json
```

For a concrete offline review package, add `--schema-document
docs/gis/proposed-drawing-schema.json`. An optional `--base-schema-document`
extends a supplied current SchemaDocument. The receipt includes exact added
class/property/relation IRIs and a document digest. It explicitly labels impact
as `offline_not_executed`: actual data/permission impact and the approval UUID
come only from the live governed `--apply` path. An empty local core has no
implicit approval or bootstrap identity.

Use the normal secret-safe environment loader and explicit existing operator
and scope identities for writes. Original files must be available beneath
`--source-root`; every declared original hash is checked before any mutation.

```powershell
python scripts/multistore_acceptance.py --env .runtime/multistore/services.env --env <other-private-service-env> -- scripts/import_drawing_ontology.py --apply --actor <operator-uuid> --owner-scope <farm-scope-uuid> --source-root <original-drawing-root> --drain-jobs 50000 --report docs/gis/ontology-import-result.json
```

An operator must already exist and hold the ordinary platform permissions:
schema view/edit/publish globally for schema preparation, and view/edit,
source.read/source.manage, evidence.read/evidence.manage and the relevant
artifact permissions for the data scope. The importer neither creates a
reviewer nor grants itself permissions. Normal operator provisioning remains
outside this importer.

If the current published schema lacks definitions, the importer creates an
additive draft from the current release and submits a real `schema.publish`
approval. Existing definitions, shapes, imports and restrictions are preserved.
The output includes draft UUID, approval UUID, revision, change digest, baseline
and impact. It returns `awaiting_schema_approval` (exit 2) without creating any
semantic entities. Initial schema bootstrap uses the same publication service
and does not exempt independent review. An actual independently authorized
reviewer must approve that exact request through the existing approval API/UI.
After approval, repeat the command with `--resume`. The script itself never
calls `ApprovalService.decide`.

All supplied properties and relationships, including values on
`DocumentStatement`, become **candidate** assertions with
`data_nature=imported_unverified`. `SourceSupport` retains the original drawing
artifact references, source identity, bundle snapshot and annotation locators.
The import timestamp is explicitly the record's time, not a survey,
construction or observation date. Only generated `importDataset`,
`importVersion`, and `importBundleSha256` bookkeeping is accepted as an
authorized platform statement. These also remain `imported_unverified`.

Objects remain in `draft` lifecycle state. `register_object` writes the normal
type declaration using the supplied class and preserves every farm UUID;
its declaration identifies a drawing-derived record, not verified existence of
a physical asset. Ambiguous facilities should use the bundle's annotation
class. An unrelated existing object with the same UUID is refused; resolving
that collision requires the existing identity-alignment workflow.

All objects are registered before relationships are patched, allowing normal
target-type validation. Each atomic step uses the existing actor-scoped
idempotency ledger. Repeated application resumes committed work without
duplicating sources, evidence or objects. A changed payload at the same
dataset/version conflicts. Live assertion checks refuse altered or withdrawn
supports rather than silently reinstating them. Use the same operator and
scope on resume; another identity does not inherit the first identity's command.

The normal worker and domain delivery handlers publish the changes.
`--drain-jobs` performs bounded ordinary delivery/worker ticks, without bypassing
permissions or directly writing SPARQL. In split mode, the GIS acknowledgements
must complete before RDF publication. Pending publication returns exit 3 and
must be resumed. A successful receipt confirms current projection heads and
reads the actual accepted/candidate graphs to verify expected statement terms.
For large bundles, worker ticks also run every 100 committed objects/patches,
sharing the same total tick budget. Keep the ordinary separate worker running
in production; a small exhausted tick budget may require resume after the
worker clears the configured queue limit.

Candidate graphs use `urn:lzo:resource:<uuid>:candidate`; accepted graphs use
`urn:lzo:resource:<uuid>:accepted`. The subject remains
`urn:lzo:object:<uuid>`, matching the UUID already held by drawing GIS. Ordinary
authorized graph/export APIs must explicitly include candidates when inspecting
source claims. The source evidence is immutable and has its own access checks.

Keep PostgreSQL/TDB2/S3 runtime data and private environment files ignored. Commit
the importer, tests, input bundle, original-file hashes and non-secret receipt;
do not commit raw originals or credentials. PostgreSQL/Jena persistence checks
are distinct from unit tests, and none of these operations constitute field
verification.
