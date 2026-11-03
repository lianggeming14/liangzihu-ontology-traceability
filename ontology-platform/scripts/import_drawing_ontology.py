"""Validate drawing semantics, or explicitly write through existing governance."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'datasets/drawings/semantic-bundle.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Prepare schema approval or write approved-schema candidates')
    mode.add_argument('--resume', action='store_true', help='Resume the same actor/scope/dataset/version using the governed ledger')
    parser.add_argument('--actor', type=UUID, help='Existing authorized platform operator UUID; no reviewer is impersonated')
    parser.add_argument('--owner-scope', type=UUID)
    parser.add_argument('--source-root', type=Path, help='Root containing the original drawing paths in the bundle')
    parser.add_argument('--drain-jobs', type=int, default=0, help='Bounded normal store delivery and worker ticks')
    parser.add_argument('--report', type=Path, help='Write the non-secret validation/import receipt')
    parser.add_argument('--schema-document', type=Path, help='Write an offline proposed SchemaDocument for review; never publishes it')
    parser.add_argument('--base-schema-document', type=Path, help='Optional existing SchemaDocument to extend without replacing definitions')
    args = parser.parse_args(argv)
    if args.drain_jobs < 0 or args.drain_jobs > 100000:
        parser.error('--drain-jobs must be between 0 and 100000')
    if (args.apply or args.resume) and not all((args.actor, args.owner_scope, args.source_root)):
        parser.error('--apply/--resume requires --actor, --owner-scope and --source-root')
    from lzo.gis.drawing_ontology_import import build_plan, GovernedDrawingImport
    importer = None
    try:
        value = json.loads(args.bundle.read_text(encoding='utf8'))
        plan = build_plan(value)
        schema_review = None
        if args.schema_document:
            from lzo.gis.drawing_ontology_import import extend_document, digest
            from lzo.ontology.schemas import SchemaDocument
            from lzo.semantic.semantic_profile import validate_document
            base = SchemaDocument.model_validate(json.loads(args.base_schema_document.read_text('utf8'))) if args.base_schema_document else SchemaDocument()
            proposed = extend_document(base, plan)
            validate_document(proposed)
            document = proposed.model_dump(mode='json')
            args.schema_document.parent.mkdir(parents=True, exist_ok=True)
            args.schema_document.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
            schema_review = {'document_path': str(args.schema_document), 'document_sha256': digest(document),
                'classes': len(proposed.classes), 'properties': len(proposed.properties), 'relations': len(proposed.relations),
                'added_classes': sorted({c.iri for c in proposed.classes} - {c.iri for c in base.classes}),
                'added_properties': sorted({p.iri for p in proposed.properties} - {p.iri for p in base.properties}),
                'added_relations': sorted({r.iri for r in proposed.relations} - {r.iri for r in base.relations}),
                'impact_status': 'offline_not_executed', 'independent_approval_required': True,
                'shape_change': proposed.shapes != base.shapes, 'published': False}
        if not args.apply and not args.resume:
            result = {'status': 'validated_only', 'database_written': False, 'rdf_written': False,
                'content_sha256': plan['content_sha256'], 'entities': len(plan['objects']),
                'candidate_assertions': sum(a['state'] == 'candidate' for a in plan['assertions']),
                'accepted_import_bookkeeping': sum(a['state'] == 'accepted' for a in plan['assertions']),
                'source_drawings': len(plan['drawings']), 'data_nature': 'imported_unverified'}
        else:
            from lzo.storage.migration import runtime_settings
            importer = GovernedDrawingImport(runtime_settings(), args.actor, args.owner_scope)
            result = importer.apply(value, args.source_root, drain_jobs=args.drain_jobs)
        if schema_review is not None:
            result['schema_review'] = schema_review
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(output + '\n', encoding='utf8')
        print(output)
        return 2 if result['status'] == 'awaiting_schema_approval' else 3 if result['status'] in ('schema_installing', 'projection_pending') else 0
    except Exception as error:
        # Exceptions from drivers/settings may embed DSNs. Never serialize them.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
            'error_code': getattr(error, 'code', 'DRAWING_IMPORT_FAILED'),
            'detail': 'No credentials or raw exception text emitted; inspect the safe validation report and platform job status.'}))
        return 1
    finally:
        if importer is not None:
            importer.close()


if __name__ == '__main__':
    raise SystemExit(main())
