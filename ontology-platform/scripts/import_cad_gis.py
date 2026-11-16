"""Publish a reviewed private CAD bundle using the configured native services."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_server.cli import load_config
from local_server.spatial_publish import publish_cad_bundle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--bundle',required=True)
    parser.add_argument('--env-file')
    args=parser.parse_args()
    config=load_config(args.config,args.env_file)
    result=publish_cad_bundle(config,Path(args.bundle),progress=lambda value:print(json.dumps(value,ensure_ascii=False),flush=True))
    print(json.dumps({key:result[key] for key in ('release_id','status','counts','files_verified','idempotent') if key in result},ensure_ascii=False))


if __name__=='__main__': main()
