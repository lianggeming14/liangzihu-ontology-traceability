"""Rebuild the exhibit table and PNG from the machine-readable trial records."""
from pathlib import Path
import csv
import json
import statistics

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator


ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))


def main():
    sql = load("整批66表正式SQL导入原始记录.json")
    bench = load("本轮四阶段原始输出.json")
    lower = load("整批66表入库逐次输出.json")
    assert bench["status"] == "passed"
    assert len(sql["runs"]) == 3 and all(sample["status"] == "passed" for sample in sql["runs"])
    case = bench["scenarios"][0]
    imports = [sample for sample in case["imports"] if sample["phase"] == "warm_new_content"]
    reads = case["reads"]["samples"]
    assert all(s["status"] == "passed" for s in [*imports, *reads])
    results = [
        ("冻结专用入口", "66表正式SQL导入与全量回读", [s["process_wall_seconds"] for s in sql["runs"]]),
        ("100塘口合成批次", "对象关系查询", [r["elapsed_seconds"] for r in reads if r["action"] == "resource"]),
        ("100塘口合成批次", "发布", [r["publication_seconds"] for r in imports]),
        ("100塘口合成批次", "JSON分页完整导出", [r["elapsed_seconds"] for r in reads if r["action"] == "export_json"]),
        ("100塘口合成批次", "SQL及RDF导入处理", [r["import_processing_seconds"] for r in imports]),
        ("100塘口合成批次", "HTTP上传登记", [r["http_202_seconds"] for r in imports]),
        ("100塘口合成批次", "上传至任务完成", [r["upload_to_complete_seconds"] for r in imports]),
        ("100塘口合成批次", "塘口实例列表查询", [r["elapsed_seconds"] for r in reads if r["action"] == "instances"]),
        ("66表来源层专项", "接收解析、文本落库与全量回读", [r["start_to_verified_seconds"] for r in lower["runs"]]),
    ]
    assert all(len(samples) == 3 for _, _, samples in results)
    with (ROOT / "试验汇总表.csv").open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.writer(out)
        writer.writerow(["范围", "操作", "第1次_秒", "第2次_秒", "第3次_秒", "三次算术均值_秒"])
        for group, action, samples in results:
            writer.writerow([group, action, *(f"{s:.9f}" for s in samples), f"{statistics.mean(samples):.9f}"])

    for family in ("Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "SimHei"):
        if any(f.name == family for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = family
            break
    plt.rcParams.update({"font.size": 10.5, "axes.unicode_minus": False, "axes.spines.top": False,
                         "axes.spines.right": False, "legend.frameon": False, "savefig.facecolor": "white"})
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.9), dpi=180)
    fig.subplots_adjust(left=.08, right=.975, top=.78, bottom=.19, wspace=.24)
    fig.suptitle("66 表正式导入与对象服务时延", x=.08, y=.966, ha="left", fontsize=20, fontweight="bold")
    fig.text(.08, .865, "同机三轮独立计时。两幅图的负载和纵轴量程不同。", color="#475569")
    for ax, series, title in zip(axes, (results[:1], results[1:4]), ("66 张业务表 · 153,862 条记录", "100 个合成塘口 · 1 个农场")):
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=12)
        ax.grid(axis="y", color="#d8dfe7", linewidth=.7)
        ax.set_axisbelow(True)
        ax.set_xticks([1, 2, 3], ["第 1 次", "第 2 次", "第 3 次"])
        ax.set_xlim(.84, 3.16)
        ax.set_ylabel("耗时（秒）")
        ax.set_ylim(0, max(max(row[2]) for row in series) * 1.55)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        for (_, name, samples), color, marker in zip(series, ["#155a8a", "#b65f21", "#24735f"], ["o", "s", "^"]):
            short = {"66表正式SQL导入与全量回读": "正式 SQL 导入", "JSON分页完整导出": "JSON 完整导出"}.get(name, name)
            ax.plot([1, 2, 3], samples, marker=marker, color=color, linewidth=2.2, markersize=6,
                    label=f"{short}  均值 {statistics.mean(samples):.3f} 秒")
        ax.legend(loc="upper left", fontsize=9, handlelength=2, borderaxespad=.35)
    fig.text(.08, .055, "完整导出每轮均为 2 页、100 个主体、1,400 条三元组。原始数据及逐次校验见同目录 JSON。", color="#475569", fontsize=9)
    fig.savefig(ROOT / "四项操作三轮实测.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
