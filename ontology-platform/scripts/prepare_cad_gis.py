"""Prepare verified CAD/GIS sources in a private runtime directory.

The bundle and source-files contain private full payloads. Publish only map.json
through the reviewed release workflow, never this entire output directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_server.spatial_source import prepare_cad_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", "--inputs", dest="inputs_dir", required=True, type=Path)
    parser.add_argument("--output-dir", "--output", dest="output_dir", required=True, type=Path)
    parser.add_argument("--source-manifest", "--manifest", dest="source_manifest", type=Path,
                        default=Path(__file__).resolve().parents[1] / "docs/local-server/gis-source-audit-2026-11-16.json")
    args = parser.parse_args(argv)
    manifest = json.loads(args.source_manifest.read_text(encoding="utf-8-sig"))
    bundle = prepare_cad_bundle(args.inputs_dir, args.output_dir, manifest)
    print(json.dumps({"contract": bundle["contract"], "batch_id": bundle["batch_id"], "counts": bundle["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
