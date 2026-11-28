"""Capture the six-graph archive using the released, read-only network queries."""

from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from types import SimpleNamespace
from pathlib import Path
import json, shutil, sys, threading
from capture_support import CURRENT, js, sha, open_browser


def capture_sphere(APP, releases, OUT, PRIVATE, executable, report):
    sys.path[:0] = [str(APP), str(APP / "scripts")]
    from local_server.query import QueryService
    from serve_ontology_review import make_handler

    release = releases / CURRENT
    glob = json.loads((release / "data/manifest.json").read_bytes())
    network_file = release / "data/ontology-network.json"
    network = json.loads(network_file.read_bytes())
    edge_id = "03a4e1430ce89913f33fe22d864ab56198fb0e9eebb186b049c270d928e5dd1a"
    edge = next(e for e in network["edges"] if e["id"] == edge_id)
    reader = QueryService(
        SimpleNamespace(limits={"page_size": 12, "max_page_size": 1000}),
        {
            "release_id": CURRENT,
            "manifest_path": str(release / "data/manifest.json"),
            "navigation_dir": str(release),
            "rdf_graphs": glob["rdf_graphs"],
        },
    )

    class SnapshotMode:
        snapshot_only = True

        def status(self):
            return {
                "mode": "rdf-snapshot",
                "available": False,
                "graph_iris": glob["rdf_graphs"],
                "snapshot_verified": True,
                "sql_used": False,
                "read_only": True,
            }

    temp = PRIVATE / "sphere-static"
    temp.mkdir(exist_ok=True)
    (temp / "data").mkdir(exist_ok=True)
    for source in (
        list((APP / "docs/fish/ontology-review").glob("*.mjs"))
        + list((APP / "docs/fish/ontology-review").glob("index.html"))
        + list((APP / "docs/fish/ontology-review").glob("assets.*"))
    ):
        if ".test." not in source.name:
            shutil.copyfile(source, temp / source.name)
    shutil.copyfile(release / "data/manifest.json", temp / "data/manifest.json")

    class Handler(make_handler(temp, SnapshotMode())):
        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/api/v1/network":
                return self.send_json(reader.network())
            if u.path == "/api/v1/network-relations":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self.send_json(
                    reader.network_relations(
                        q["source"],
                        q["predicate"],
                        q["target"],
                        limit=q.get("limit"),
                        cursor=q.get("cursor"),
                    )
                )
            return super().do_GET()

        def log_message(self, *_):
            pass

    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=s.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{s.server_port}/#view=network"
    report["six_graph_sphere"] = {
        "release_id": CURRENT,
        "browser_action": "read-only replay of unmodified ontology browser against released network files using the original QueryService.network and QueryService.network_relations methods",
        "field_acceptance": False,
        "counts": network["counts"],
        "navigation_network_sha256": sha(network_file),
        "edge": edge,
        "relation_page": network["relation_index"][edge_id]["pages"][0],
        "images": [],
    }
    res = reader.network_relations(
        edge["source"], edge["predicate"], edge["target"], limit=12
    )
    assert (
        res["total"] == 14
        and res["items"][9]["source_label"] == "C01"
        and res["items"][9]["target_label"] == "1号模拟塘"
    )
    report["six_graph_sphere"]["first_page_tenth_pair"] = res["items"][9]

    def capture(name, scope):
        path = OUT / (name + ".png")
        b.png(path)
        report["six_graph_sphere"]["images"].append(
            {"file": path.name, "scope": scope, "sha256": sha(path)}
        )
        print(name, flush=True)

    try:
        with open_browser(executable, PRIVATE) as (b, url):
            b.call("Page.navigate", {"url": base})
            b.wait("document.querySelector('.sphere-canvas')!==null")
            kind = "document.querySelector('[data-filter=kind]')"
            b.eval(
                f"{kind}.value='observed'; {kind}.dispatchEvent(new Event('change',{{bubbles:true}}))"
            )
            label = edge["source"]
            key = f'[data-node="{label}"]'
            for i in range(10):
                if b.eval(f"document.querySelector({js(key)})!==null"):
                    break
                b.click(".sphere-list-pagination button:last-child")
            b.click(key)
            b.wait(
                "document.querySelector('.sphere-selection h3').innerText==='CSV · 养殖批次'"
            )
            b.scroll_to("document.querySelector('.sphere-canvas')", 118)
            capture(
                "13_关系球与养殖批次类型",
                "类级球网；选中CSV养殖批次，仅显示已发布实例关系聚合边",
            )
            e = f'[data-edge="{edge_id}"]'
            for i in range(12):
                if b.eval(f"document.querySelector({js(e)})!==null"):
                    break
                b.click(".sphere-selection .pagination button:last-child")
            b.click(e)
            b.wait("document.querySelector('[data-open-edge]')!==null")
            b.scroll_to("document.querySelector('.sphere-canvas')", 118)
            capture(
                "14_聚合边养殖批次至塘口",
                "养殖批次类型至塘口类型的pond_id聚合边，14个唯一实例三元组",
            )
            b.click("[data-open-edge]")
            b.wait(
                "Array.from(document.querySelectorAll('.network-instance-pair')).some(x=>x.innerText.includes('C01')&&x.innerText.includes('1号模拟塘'))"
            )
            el = "Array.from(document.querySelectorAll('.network-instance-pair')).find(x=>x.innerText.includes('C01')&&x.innerText.includes('1号模拟塘'))"
            b.eval(f"{el}.scrollIntoView({{block:'center',behavior:'instant'}})")
            b.scroll_to("document.querySelector('.sphere-canvas')", 118)
            capture(
                "15_球网展开C01至P01实例",
                "球面为类级布局；右侧为该聚合边的真实实例对，包括C01至1号模拟塘",
            )
    finally:
        s.shutdown()
        s.server_close()
        th.join()
