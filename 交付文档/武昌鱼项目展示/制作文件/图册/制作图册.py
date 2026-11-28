"""生成两页 A4 横版图册。可用 --source-dir 指定已解压的 66 张业务 CSV 所在目录，
逐字节、逐字段核对所选记录。依赖 Pillow、ReportLab、PyMuPDF 与 Windows 等线字体。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOTS = ROOT / "系统截图"
OUT = ROOT / "图册"
W, H = landscape(A4)
LEFT, GUTTER = 31, 28
COL = (W - LEFT * 2 - GUTTER) / 2
INK = "#162E31"
MUTED = "#465A5B"
JADE = "#126357"
LINE = "#BDCDC6"
PAPER = "#FFFFFF"
PROJECT = "武昌鱼智慧养殖数据治理与溯源服务系统"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_fonts():
    font_dir = Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("Atlas", str(font_dir / "Deng.ttf")))
    pdfmetrics.registerFont(TTFont("AtlasBold", str(font_dir / "Dengb.ttf")))


def text(canvas, x, top, value, size=12, *, font="Atlas", color=INK, right=False):
    canvas.setFillColor(HexColor(color))
    canvas.setFont(font, size)
    if right:
        canvas.drawRightString(x, H-top, value)
    else:
        canvas.drawString(x, H-top, value)


def rule(canvas, x, top, end, color=LINE, weight=.6):
    canvas.setStrokeColor(HexColor(color))
    canvas.setLineWidth(weight)
    canvas.line(x, H-top, end, H-top)


def crop_excerpt(source, boxes):
    """Combine aligned field strips from one unaltered screenshot."""
    with Image.open(source) as image:
        crops = [image.crop(box).convert("RGB") for box in boxes]
    width = max(crop.width for crop in crops)
    result = Image.new("RGB", (width, sum(crop.height for crop in crops)), "white")
    top = 0
    for crop in crops:
        result.paste(crop, (0, top))
        top += crop.height
    data = BytesIO()
    result.save(data, format="PNG")
    data.seek(0)
    return ImageReader(data), result.size


def panel(canvas, x, top, number, title, frame, boxes, sentences, source):
    text(canvas, x, top+13.5, str(number).zfill(2), 12, font="AtlasBold", color=JADE)
    text(canvas, x+26, top+14, title, 16, font="AtlasBold")
    box_top = top+24
    box_height = 98
    canvas.setFillColor(HexColor("#F6F9F7"))
    canvas.setStrokeColor(HexColor("#DBE3DF"))
    canvas.rect(x, H-box_top-box_height, COL, box_height, fill=1, stroke=1)
    picture, (width, height) = crop_excerpt(frame, boxes)
    scale = min((COL-18)/width, (box_height-10)/height)
    px = x+9
    py = H-box_top-box_height+(box_height-height*scale)/2
    canvas.drawImage(picture, px, py, width=width*scale, height=height*scale)
    for i, line in enumerate(sentences):
        text(canvas, x, top+140+i*15.5, line, 11.7)
    text(canvas, x, top+176.5, source, 9.6, color=MUTED)


def page_header(canvas, title, strap, page):
    text(canvas, LEFT, 29, PROJECT+"  /  作品图示", 10.5, font="AtlasBold", color=JADE)
    text(canvas, W-LEFT, 29, f"实验室模拟台账     {page} / 2", 10.5, color=MUTED, right=True)
    text(canvas, LEFT, 69, title, 31, font="AtlasBold")
    text(canvas, LEFT, 93, strap, 12.1, color=MUTED)
    rule(canvas, LEFT, 106.5, W-LEFT, color=JADE, weight=1)
    rule(canvas, LEFT, 325, W-LEFT)


def footer(canvas, label, line, link_name, url):
    rule(canvas, LEFT, 534, W-LEFT)
    text(canvas, LEFT, 553.5, label, 11.4, font="AtlasBold", color=JADE)
    text(canvas, LEFT, 574, line, 9.5, color=MUTED)
    text(canvas, W-LEFT, 574, link_name, 9.5, font="AtlasBold", color=JADE, right=True)
    width = pdfmetrics.stringWidth(link_name, "AtlasBold", 9.5)
    canvas.linkURL(url, (W-LEFT-width,H-578,W-LEFT,H-563), relative=0)


def verify_source_rows(source_dir, records):
    for record in records.values():
        path = source_dir / Path(record["path"]).name
        if sha256(path) != record["sha256"]:
            raise ValueError(f"CSV digest mismatch: {path.name}")
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            for index, row in enumerate(reader, start=1):
                if index == record["record_number"]:
                    if (reader.line_num != record["csv_line"]
                            or any(row[key] != value for key, value in record["values"].items())):
                        raise ValueError(f"Source fields or physical line mismatch: {path.name}")
                    break
            else:
                raise ValueError(f"Source row missing: {path.name}")


def main(source_dir=None):
    register_fonts()
    evidence = json.loads((HERE / "四表证据.json").read_text("utf-8-sig"))
    manifest = json.loads((SHOTS / "取证清单.json").read_text("utf-8-sig"))
    if manifest["snapshot_published_release_id"] != evidence["release_id"]:
        raise ValueError("Source-exhibit release mismatch")
    if manifest["source_zip_sha256"] != evidence["archive_sha256"]:
        raise ValueError("Source-exhibit package mismatch")
    records = {row["kind"]: row for row in evidence["samples"]}
    if source_dir is not None:
        verify_source_rows(source_dir, records)
    for record in records.values():
        expected = manifest["objects"][record["values"]["id"]]["source"]
        if (expected["row_number"] != record["record_number"]
                or expected["csv_line_end"] != record["csv_line"]
                or expected["source_file"] != record["path"]
                or expected["source_sha256"] != record["sha256"]):
            raise ValueError(f"Row or file digest mismatch: {record['path']}")
    screenshots = {}
    for shot in manifest["frames"] + manifest["archived_console_pictures"]:
        path = SHOTS / shot["file"]
        if sha256(path) != shot["sha256"]:
            raise ValueError(f"Screenshot digest mismatch: {path.name}")
        screenshots[int(path.name[:2])] = path

    fish = records["fish"]["values"]
    stay = records["occupancy"]["values"]
    pond = records["pond"]["values"]
    water = records["water"]["values"]
    if not (
        fish["id"] == stay["cohort_id"]
        and fish["pond_id"] == stay["pond_id"] == pond["id"] == water["pond_id"]
        and stay["entered_at"] <= water["observed_at"] < stay["left_at"]
    ):
        raise ValueError("The four selected source records do not form an in-period pond observation.")

    OUT.mkdir(exist_ok=True)
    pdf = OUT / "武昌鱼批次交接核查图册.pdf"
    canvas = Canvas(str(pdf), pagesize=(W,H), pageCompression=1, invariant=1)
    canvas.setTitle("武昌鱼批次交接核查图册")
    canvas.setSubject("固定发布快照的四表来源定位实例")
    canvas.setAuthor("武昌鱼智慧养殖数据治理与溯源服务系统")
    x2 = LEFT + COL + GUTTER
    at = [(LEFT,126), (x2,126), (LEFT,341), (x2,341)]
    source_link = "https://github.com/lianggeming14/upload-files/blob/" + evidence["source_commit"] + "/csv.zip"
    report_link = "https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/9ded95c99bad3a37a5d82d932db07454e2923c1f/ontology-platform/docs/csv-batch/README.md"

    page_header(canvas, "这批武昌鱼来自哪口塘？", "从鱼群编号出发，核对入住事件和塘口，再找一条发生在鱼群在塘期间的水质观测。", 1)
    cards = [
        (1, "在对象目录里锁定鱼群", 1, [(465,271,1085,434)],
         [f"鱼群 {fish['id']}，品名“{fish['original_commercial_name']}”。", f"2025 年 1 月 10 日起养，初始数量 {int(fish['initial_count']):,} 尾。"],
         "cohorts.csv  ·  数据第 1 条  /  文件第 2 行"),
        (2, "用在塘事件对上两个编号", 4, [(455,144,1168,185),(455,252,1168,294),(455,359,1168,402),(455,467,1168,511)],
         [f"{stay['id']} 将鱼群 {stay['cohort_id']} 与塘口 {stay['pond_id']} 关联。","入塘为 1 月 10 日 10:00，离塘为 11 月 20 日 14:00。"],
         "pond_cohort_occupancy.csv  ·  数据第 1 条  /  文件第 2 行"),
        (3, "打开同一口塘的档案", 5, [(465,270,1085,434)],
         [f"塘口 {pond['id']}，名称“{pond['name']}”，归属养殖场 {pond['farm_id']}。",f"档案面积 {pond['area_mu']} 亩，平均水深 {pond['mean_depth_m']} 米。"],
         "ponds.csv  ·  数据第 1 条  /  文件第 2 行"),
        (4, "沿塘口关系找到次日观测", 7, [(456,816,1168,859),(456,924,1168,967),(456,1141,1168,1183)],
         [f"{water['id']} 归属 {water['pond_id']}，观测于 1 月 11 日 06:00。","该时刻在上述入住区间内，读数描述这口塘的水体。"],
         "water_observations.csv  ·  数据第 247 条  /  文件第 248 行"),
    ]
    for xy, (num,title,shot,boxes,lines,origin) in zip(at, cards):
        panel(canvas, *xy, num,title,screenshots[shot],boxes,lines,origin)
    footer(canvas,"交接结论   C01 入住 P01，次日清晨的塘水观测可回查到第 248 行。",
           "画面取自原版浏览器的已发布只读快照，图内为界面字段节选。示例时间均为北京时间。", "打开本批次工程记录  ↗", report_link)
    canvas.showPage()

    page_header(canvas, "第 248 行里，哪些值可以复核？", "打开水质观测对象的属性和来源页，分别核对读数、记录序号、文件名与交接版本。", 2)
    cards = [
        (5, "查看三个水质字段", 8, [(455,442,1010,485),(455,550,1010,593),(455,658,1010,701)],
         [f"水温 {water['temperature_c']} ℃，溶解氧 {water['do_mg_l']} mg/L。",f"pH 原始读数 {water['raw_ph']}，校正偏移 {water['ph_correction']}，校正后为 {water['ph']}。"],
         "对象  O1_010_06  ·  属性"),
        (6, "分清记录序号与文件行号", 9, [(483,274,1214,338),(483,352,1214,416),(483,429,1214,493)],
         ["系统“原始行号”为 247，即第 247 条数据记录。","CSV 第 1 行是表头。这条记录在文件第 248 行。"],
         "来源记录类型  water_observations"),
        (7, "返回保留的原始文件", 10, [(485,122,1160,191),(485,539,1160,604)],
         ["在固定输入包中打开 csv/water_observations.csv。","先核对文件 SHA-256，再按第 248 行比对原值。"],
         "输入文件  csv.zip  ·  包内保留逐文件摘要"),
        (8, "固定交接使用的发布版本", 11, [(566,415,929,548)],
         ["历史控制台留存了同一发布的“现有审阅快照”。","交接双方保留这个发布标识，便可约定按同一版本复查。"],
         "发布标识  "+evidence["release_id"]),
    ]
    for xy,(num,title,shot,boxes,lines,origin) in zip(at,cards):
        panel(canvas,*xy,num,title,screenshots[shot],boxes,lines,origin)
    footer(canvas,"复核时请保留三项   原文件路径、CSV 行号、发布标识。",
           "固定输入包 SHA-256  "+evidence["archive_sha256"],"打开固定来源包  ↗",source_link)
    canvas.save()
    with fitz.open(pdf) as doc:
        if len(doc) != 2 or any(len(page.get_images()) != 4 for page in doc):
            raise ValueError("Expected four visual exhibits on each page")
        for token in ("OCC000001", "O1_010_06", "248", evidence["release_id"]):
            if token not in "".join(page.get_text() for page in doc):
                raise ValueError(f"Missing searchable evidence: {token}")
        doc[0].get_pixmap(matrix=fitz.Matrix(3,3), alpha=False).save(OUT / "武昌鱼批次交接核查四联图.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    main(parser.parse_args().source_dir)

