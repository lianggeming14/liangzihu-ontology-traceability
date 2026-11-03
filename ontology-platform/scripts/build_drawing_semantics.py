"""Build typed measurements, complete object profiles and governed ontology input."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend/src'))
from lzo.gis.drawing_semantics import build_semantics
from lzo.gis.drawing_ontology_import import validate_bundle, build_plan, extend_document
from lzo.ontology.schemas import SchemaDocument


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'datasets/drawings')
    parser.add_argument('--version', default='1')
    args = parser.parse_args()
    load = lambda n: json.loads((args.directory/n).read_text('utf8'))
    bundle = validate_bundle(build_semantics(load('package.json'), load('metric-review-12.json'), load('metric-review-345.json'), version=args.version))
    for name, value in [('semantic-bundle.json', bundle), ('object-profiles.json', bundle['profiles']),
                        ('semantic-coverage.json', bundle['coverage']),
                        ('schema-document.json', extend_document(SchemaDocument(), build_plan(bundle)).model_dump(mode='json'))]:
        (args.directory/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8', newline='\n')
    print(json.dumps(dict(sha256=bundle['content_sha256'], nodes=len(bundle['nodes']), edges=len(bundle['edges']), measurements=len(bundle['measurements']), profiles=len(bundle['profiles']))))


if __name__ == '__main__':
    main()
