"""Locate cited entry points in the application document's exact Git commit."""
import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path


COMMIT = "9ded95c99bad3a37a5d82d932db07454e2923c1f"
MODULES = {
    "importer": ["_read_csv", "prepare_input", "build_batch"],
    "worker": ["store_batch", "process_job"],
    "rdf": ["generate_rdf", "load_and_verify", "build_navigation", "verify_files"],
    "http": ["make_handler"],
    "query": ["decode_cursor", "QueryService.instances", "QueryService.resource", "QueryService.export"],
    "store": ["Store.submit_job", "Store.register_release", "Store.get_release", "Store.publish_release"],
}


def git(repo, *args):
    return subprocess.check_output(["git", "-c", "safe.directory=" + repo.as_posix(),
                                    "-C", str(repo), *args])


def inspect(repo):
    obj = git(repo, "rev-parse", "--verify", COMMIT + "^{commit}").decode().strip()
    if obj != COMMIT:
        raise ValueError("unexpected commit")
    record = {"commit": obj, "tree": git(repo, "rev-parse", COMMIT + "^{tree}").decode().strip(),
              "method": "read_only_git_blobs_and_python_AST", "modules": []}
    for name, symbols in MODULES.items():
        path = "ontology-platform/local_server/" + name + ".py"
        source = git(repo, "show", COMMIT + ":" + path)
        parsed = ast.parse(source)
        definitions = {}
        for node in parsed.body:
            if isinstance(node, ast.FunctionDef):
                definitions[node.name] = node
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef):
                        definitions[node.name + "." + child.name] = child
        matches = {symbol: [definitions[symbol].lineno, definitions[symbol].end_lineno] for symbol in symbols}
        record["modules"].append({"path": path, "sha256": hashlib.sha256(source).hexdigest(),
                                  "definitions_start_end": matches})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.repo.resolve()), indent=2))


if __name__ == "__main__":
    main()
