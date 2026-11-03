"""Readable complete field/pond perimeter register from the sealed typed bundle."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    bundle=json.loads((ROOT/'datasets/drawings/semantic-bundle.json').read_text('utf8'))
    lines=['# 五张竣工图：田块与鱼塘尺寸清单','',
        '数据性质：原图转录与条件推算，未经过现场测绘验收。每个对象的原文、来源定位、量纲、推算依据和关系均保留在对象档案与查询接口。',
        '', '纸面周长以 PDF 点（pt）计算；1:1000 与 1:4000 是图签比例条件下的情景，不是两个可任选的真实结果。参考长度推算范围仅反映参考线比例差异，未覆盖全部描线和端点误差。',
        '',f"来源包 SHA-256：`{bundle['source_package_sha256']}`",'',f"语义数据包 SHA-256：`{bundle['content_sha256']}`",'',
        '| 图纸 | 对象 | 类别 | 纸面周长 pt | 参考长度推算 m | 推算范围 m | 1:1000 情景 m | 1:4000 情景 m | 单塘水深 |',
        '|---|---|---|---:|---:|---|---:|---:|---|']
    for p in bundle['profiles']:
        if p['kind'] not in ('field','pond'):continue
        g=p['ground_estimate'];interval=g.get('perimeter_range_m');sc={s['scale_denominator']:s for s in p['scale_scenarios']}
        values=[p['drawing_id'],p['label'],'田块' if p['kind']=='field' else '塘面',f"{p['paper_metrics']['perimeter_pt']:.3f}",
            str(g.get('perimeter_m') or '未采用'),'—' if interval is None else '–'.join(map(str,interval)),
            str(sc[1000]['perimeter_m']),str(sc[4000]['perimeter_m']),'不适用' if p['kind']=='field' else '原图未见逐塘标注']
        lines.append('| '+' | '.join(values)+' |')
    lines+=['','## 已提取的深度相关数据','',
        '| 数据 | 值 | 适用对象 |','|---|---|---|',
        '| 生态渠深度 | 1.1 m | 工程表中生态渠项目 |',
        '| 环形沟深度 | 0.8 m | 工程表中环形沟项目 |',
        '| 生态渠 I 型-1、III 型-2、III 型-5 渠底高程 | 17.94 m | 对应编号沟段；高程基准未明 |',
        '| 清5—清17项目平均清淤厚度 | 1 m | 86300.15 m³ ÷ 86300.15 m²，工程汇总推导 |',
        '| 单塘水深 | 未见可靠逐塘标注 | 不以沟深、渠底高程或汇总清淤厚度替代 |',
        '', '## 查询入口','',
        '- `GET /api/v1/drawing-gis/profiles/{田块或鱼塘UUID}`：周长、面积、尺度情景、深度缺项、关联测量及依据。',
        '- `GET /api/v1/drawing-gis/measurements?kind=channel_depth`：所有沟深记录及原文。',
        '- `GET /api/v1/drawing-gis/measurements?kind=bottom_elevation`：渠底高程，单独于深度。',
        '- `GET /api/v1/drawing-gis/measurements?subject_id={UUID}`：对象全部结构化记录。',
        '- `GET /api/v1/drawing-gis/relationships?subject_id={UUID}`：对象关系。',
        '- `GET /api/v1/drawing-gis/entities/{UUID}`：关系目标的类别、名称和属性。','',
        '这些接口读取已安装的 GIS 查询模型。正式本体核心库与 Jena 的导入状态须以独立导入报告为准。','']
    (ROOT/'docs/gis/object-metrics.md').write_text('\n'.join(lines),encoding='utf8',newline='\n')
    print(json.dumps({'field_and_pond_rows':120,'bundle_sha256':bundle['content_sha256']}))


if __name__=='__main__':main()
