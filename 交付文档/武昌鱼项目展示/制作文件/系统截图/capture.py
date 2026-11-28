"""Recreate the exhibit screenshots and recordings; report hashes refer to this run."""

import argparse, csv, gzip, hashlib, io, json, shutil, subprocess, sys, time, zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from capture_support import CURRENT, VER, SHA, Recording, js, sha, open_browser
from capture_sphere import capture_sphere


def capture_chain(APP, releases, archive, OUT, PRIVATE, executable):
    SNAP = APP / "docs/fish/ontology-review/data"
    data = {}

    def gz(path):
        return json.loads(gzip.decompress((SNAP / path).read_bytes()))

    for cls, identity in [
        ("cohorts", "C01"),
        ("pond_cohort_occupancy", "OCC000001"),
        ("ponds", "P01"),
        ("water_observations", "O1_010_06"),
    ]:
        table = f"csv_{cls}"
        row = next(
            x
            for x in gz(f"classes/{table}.json.gz")["instances"]
            if x["id"] == identity
        )
        d = next(
            x for x in gz(row["detail_path"])["instances"] if x["iri"] == row["iri"]
        )
        data[identity] = d
        for v in [VER, CURRENT]:
            published = releases / v / "data" / row["detail_path"]
            assert sha(published) == sha(SNAP / row["detail_path"])
    orig = archive
    assert sha(orig) == SHA
    with zipfile.ZipFile(orig) as z:
        for r in data.values():
            prov = r["provenance"]
            raw = z.read(prov["source_file"])
            assert hashlib.sha256(raw).hexdigest() == prov["source_sha256"]
            rd = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            for index, record in enumerate(rd, 1):
                if index == prov["row_number"]:
                    assert (
                        record["id"] == r["id"] and rd.line_num == prov["csv_line_end"]
                    )
                    break
            else:
                raise ValueError("Required source row not found in the reviewed CSV")
    assert sha(SNAP / "manifest.json") == sha(releases / VER / "data/manifest.json")
    report = {
        "capture_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only published RDF snapshot rendered by original ontology browser in Chrome",
        "field_acceptance": False,
        "source_zip_sha256": SHA,
        "snapshot_published_release_id": VER,
        "manifest_sha256": sha(SNAP / "manifest.json"),
        "details_also_identical_in_release": CURRENT,
        "objects": {},
        "frames": [],
        "recordings": [],
    }
    for id, r in data.items():
        report["objects"][id] = {
            "iri": r["iri"],
            "class_iri": r["class_iri"],
            "detail_path": r["detail_path"],
            "detail_sha256": sha(SNAP / r["detail_path"]),
            "source": r["provenance"],
        }

    def link(id, **extra):
        r = data[id]
        return "#" + urlencode(
            {"view": "instance", "iri": r["iri"], "class": r["class_iri"], **extra}
        )

    def fld(key):
        return f"""Array.from(document.querySelectorAll('.property-row')).find(e=>e.querySelector('.property-meta')?.innerText.includes({js(key)}))"""

    server = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "scripts/serve_ontology_review.py",
            "--offline",
            "--port",
            "0",
        ],
        cwd=APP,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        info = json.loads(server.stdout.readline())
        base = info["url"]
        assert info["read_only"] and not info["sql_used"]
        with open_browser(executable, PRIVATE) as (b, url):
            report["browser"] = b.call("Browser.getVersion")["product"]
            report["viewport"] = {
                "css_pixels": [1440, 810],
                "screenshot_pixels": [2160, 1215],
            }

            def at(id):
                b.wait(
                    f"document.querySelector('h1')?.innerText==={js(data[id]['label'])}&&document.querySelector('.object-iri')?.innerText==={js(data[id]['iri'])}"
                )

            def nav(id, **extra):
                b.call("Page.navigate", {"url": base + link(id, **extra)})
                at(id)

            def targetid(id):
                return f'[data-relation="{data[id]["iri"]}"]'

            def shot(name, id, purpose, required):
                for word in required:
                    b.wait(f"document.body.innerText.includes({js(word)})")
                path = OUT / (name + ".png")
                b.png(path)
                report["frames"].append(
                    {
                        "file": path.name,
                        "object": id,
                        "purpose": purpose,
                        "route": b.eval("location.hash"),
                        "scroll_y": b.eval("Math.round(scrollY)"),
                        "sha256": sha(path),
                    }
                )
                print(name, flush=True)

            nav("C01")
            shot(
                "01_鱼群C01",
                "C01",
                "鱼群详情，规则模拟，源主键和塘口字段",
                ["C01", "P01"],
            )
            nav("C01", tab="relations", incomingPage=623)
            oc = targetid("OCC000001")
            b.wait(f"document.querySelector({js(oc)})!==null")
            b.scroll_to("document.querySelector(" + js(oc) + ")", 355)
            shot(
                "02_C01关联在塘记录",
                "C01",
                "鱼群的入向关系第623页进入在塘记录",
                ["OCC000001"],
            )
            b.click(oc)
            at("OCC000001")
            shot(
                "03_在塘记录OCC000001",
                "OCC000001",
                "在塘记录的身份与所属塘口、鱼群",
                ["OCC000001", "C01", "P01"],
            )
            b.scroll_to(fld("cohort_id"), 160)
            shot(
                "04_在塘起止时间",
                "OCC000001",
                "同一记录的鱼群号、进塘时间和离塘时间",
                ["2025-01-10", "2025-11-20"],
            )
            b.click("[data-tab=relations]")
            pp = targetid("P01")
            b.wait(f"document.querySelector({js(pp)})!==null")
            b.scroll_to("document.querySelector(" + js(pp) + ")", 370)
            clip = Recording(url, OUT / "动作A_由在塘记录进入塘口.mp4")
            clip.start()
            b.click(pp)
            at("P01")
            time.sleep(1.2)
            shot(
                "05_塘口P01",
                "P01",
                "1号模拟塘面积与属性",
                [
                    "P01",
                    "6,200" if "6,200" in b.eval("document.body.innerText") else "6200",
                ],
            )
            report["recordings"].append(clip.finish())
            nav("P01", tab="relations", incomingPage=925)
            wa = targetid("O1_010_06")
            b.wait(f"document.querySelector({js(wa)})!==null")
            b.scroll_to("document.querySelector(" + js(wa) + ")", 360)
            shot(
                "06_P01关联水质观测",
                "P01",
                "入向关系第925页，观测记录指向同一P01",
                ["O1_010_06"],
            )
            clip = Recording(url, OUT / "动作B_由塘口追溯水质与来源.mp4")
            clip.start()
            b.click(wa)
            at("O1_010_06")
            time.sleep(0.9)
            shot(
                "07_水质记录O1_010_06",
                "O1_010_06",
                "水质观测身份与塘口、设备和时间",
                ["O1_010_06", "P01", "D01"],
            )
            b.scroll_to(fld("temperature_c"), 285)
            time.sleep(1.3)
            shot(
                "08_水质读数",
                "O1_010_06",
                "同一观测的温度、溶氧与pH；规则模拟",
                ["11.13", "6.72", "7.21"],
            )
            b.click("[data-tab=evidence]")
            b.wait("document.querySelector('.evidence-card')!==null")
            b.scroll_to("document.querySelector('.evidence-card')", 136)
            time.sleep(0.85)
            shot(
                "09_来源行与批次",
                "O1_010_06",
                "247是数据记录序号，248是CSV物理结束行，源文件SHA256和导入批次均来自页面",
                ["247", "248", SHA, "csv/water_observations.csv"],
            )
            report["recordings"].append(clip.finish())
            b.scroll_to(
                "Array.from(document.querySelectorAll('.evidence-card dt')).find(e=>e.innerText==='来源文件')",
                360,
            )
            shot(
                "10_来源文件",
                "O1_010_06",
                "来源文件名、来源记录IRI与数据性质",
                ["csv/water_observations.csv"],
            )
    finally:
        server.terminate()
        server.wait()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", type=Path, required=True, help="ontology-platform source directory"
    )
    parser.add_argument(
        "--releases",
        type=Path,
        required=True,
        help="parent of the two immutable release directories",
    )
    parser.add_argument(
        "--source-zip",
        type=Path,
        required=True,
        help="original pinned 66-table archive",
    )
    parser.add_argument(
        "--browser",
        type=Path,
        required=True,
        help="installed Chrome or Chromium executable",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new output directory"
    )
    args = parser.parse_args()
    app, releases, archive, browser, output = [
        p.resolve()
        for p in (
            args.project,
            args.releases,
            args.source_zip,
            args.browser,
            args.output,
        )
    ]
    if (
        not browser.is_file()
        or not archive.is_file()
        or not (app / "scripts/serve_ontology_review.py").is_file()
    ):
        parser.error("Verify the project, source ZIP and browser paths")
    if not all((releases / r / "data/manifest.json").is_file() for r in (VER, CURRENT)):
        parser.error("Both original released snapshots are required")
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory() as scratch:
        private = Path(scratch)
        chain_scratch = private / "chain"
        chain_scratch.mkdir()
        report = capture_chain(app, releases, archive, output, chain_scratch, browser)
        sphere_scratch = private / "sphere"
        sphere_scratch.mkdir()
        capture_sphere(app, releases, output, sphere_scratch, browser, report)
    hist = app / "docs/local-server"
    archived = json.loads((hist / "browser-readback.json").read_bytes())
    report["archived_console_pictures"] = []
    for original, name in [
        ("desktop-console.png", "11_历史运行的版本标识.png"),
        ("desktop-resource.png", "12_历史固定版本导出入口.png"),
    ]:
        source = hist / "screenshots" / original
        shutil.copyfile(source, output / name)
        report["archived_console_pictures"].append(
            {
                "file": name,
                "source_path": source.relative_to(app).as_posix(),
                "historical_checked_at": archived["checked_at"],
                "release_id": archived["main"]["release_id"],
                "sha256": sha(output / name),
            }
        )
    report["archived_export_evidence"] = {
        "source": "docs/local-server/browser-readback.json",
        "checked_at": archived["checked_at"],
        "export_class": archived["main"]["export_class"],
        "actual_downloads": archived["main"]["downloads"],
    }
    (output / "取证清单.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
