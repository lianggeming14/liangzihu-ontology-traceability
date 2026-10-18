"""Reconcile operation docs with the final implementation and actual test evidence."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/backend-integration-20261019'


def main():
    test=ET.parse(OUT/'final-tests.xml').getroot()
    suites=list(test.iter('testsuite'))
    counts={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    counts['passed']=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    skip_reasons={}
    for item in test.iter('skipped'):
        reason=item.get('message','unknown')
        skip_reasons[reason]=skip_reasons.get(reason,0)+1
    verification={'date':'2026-10-19','suite':counts,'skip_reasons':skip_reasons,
                  'data_nature':'synthetic_isolated_tests','postgresql_verified':False,
                  'production_source_connected':False,'field_acceptance':False,
                  'evidence':['final-tests.xml','upgrade-preflight.json','upgrade-applied.json','http-release-check.json']}
    (OUT/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=OUT/'backend_manual.json';manual=json.loads(path.read_text(encoding='utf-8'))
    for section in manual['sections']:
        section['paragraphs']=[text.replace('相同规范化内容','相同来源快照内容').replace('实际导出数据放入 implementation/runtime 等已忽略的运行目录','实际导出数据放入 implementation/runtime/source-imports 这一已忽略的私有运行目录') for text in section.get('paragraphs',[])]
        for table in section.get('tables',[]):
            for row in table['rows']:
                for i,value in enumerate(row):
                    row[i]=value.replace('/ontology/relations?status=all','/ontology/relations?status=all')
                if row[0]=='GET /ontology/relations?status=all':
                    row[1]='查看指定valid_at时刻的不同状态关系；未传时为当前。完整历史见来源绑定relationships分页。'
                if row[0].startswith(('GET /','POST /')) and '/api/v1/' not in row[0]:
                    row[0]=row[0].replace(' /',' /api/v1/',1)
        section['code']=[line.replace('python implementation/','implementation/.venv/Scripts/python.exe implementation/').replace('python -m pytest','implementation/.venv/Scripts/python.exe -m pytest') for line in section.get('code',[])]
    fifth=next(s for s in manual['sections'] if s['title'].startswith('五 '))
    unit='带单位的目标属性要求 profile 的字段映射显式声明 source_unit，并与目标单位相同；可用 source_unit_field 对来源行中的单位列逐值核对。缺失或不符会拒绝接入。此入口不自动识别单位或换算；需要亩与公顷、K 与摄氏度等转换时，使用明确配置的 intake 转换规则并保留原值。'
    if unit not in fifth['paragraphs']:fifth['paragraphs'].append(unit)
    sixth=next(s for s in manual['sections'] if s['title'].startswith('六 '))
    nature='data_nature 可声明 production、synthetic、test 或 unspecified。production 只是来源声明，不是现场真实性认证。已有绑定的数据性质不可隐式改变；合成或测试身份不能改标成生产。修订快照必须晚于上一个已提交快照，且不能在未来；预报未来有效时间放在业务字段中。'
    if nature not in sixth['paragraphs']:sixth['paragraphs'].append(nature)
    seventh=next(s for s in manual['sections'] if s['title'].startswith('七 '))
    seventh['paragraphs']=[p.replace('关系网络接口是受预算限制的当前子图。','HTTP 关系网络接口展示当前存储的有界关系记录网络，其中包含候选和有效期已结束的关系。temporal_status 与 within_valid_interval 说明时间区间，status 另说明采纳状态，不能只看连线便认定当前归属。') for p in seventh['paragraphs']]
    paging='查询来源绑定详情时，用 binding_id 或 entity_key 定位；history_limit/history_offset 控制来源修订，relationship_limit/relationship_offset 控制关系历史，分页大小为 1–100。根据 history_page 或 relationships_page 的 has_more 与 next_offset 继续取页。仅依赖规划可用 projection=identity，避免读取全部来源原文；该投影不能同时展开历史。'
    evidence='GET /api/v1/inference/bundles/{entity_key} 返回独立 source_snapshots 分组。每个来源快照带绑定、修订、数据性质、属性、证据有效状态和 retrieval_manifest。usable_for_inference 默认 false，采纳前提由外部流程决定；证据撤回或实体修订不一致会产生 gaps，不能拿旧快照无条件驱动结论。'
    for p in (paging,evidence):
        if p not in seventh['paragraphs']:seventh['paragraphs'].append(p)
    cli_title='十三 梁子湖导入工具实操'
    manual['sections']=[s for s in manual['sections'] if s['title'] not in (cli_title,'十四 本次交付验证记录')]
    manual['sections'].append({'title':cli_title,'paragraphs':[
        '以下命令在项目根目录运行。AGRI_API_TOKEN 应通过受控终端环境提供，不要写进命令历史、脚本或文档。默认命令只预检；加 --apply 才正式写入。完整参数、SQL取数和恢复说明见 implementation/integrations/liangzihu/README.txt。',
        '先用 synthetic 来源和配套 11 条样例验证工具。已有本地数据库本轮只安装 18 个定义包和 liangzihu-platform 来源映射，不导入这 11 条样例。后续真实来源可使用该 source_id，或安装另一个明确命名的来源实例。',
        '真实源库使用授权只读账号执行 readonly-export-core.sql 或 readonly-export.sql。使用 psql 的 --output 参数保存 UTF-8 JSONL，避免 Windows PowerShell 5 的 > 重定向生成 UTF-16。SQL使用只读一致快照、显式列白名单和精确数值字符串，不使用 SELECT *。',
        '超过 100 条时先生成依赖计划。工具把同一循环依赖分量放在同批，先导入其他被依赖对象；超过预算的循环、缺失父记录和过大载荷会报错。plan 只是依赖规划，不表示远端值域已经验证。',
        'apply-plan 不加 --apply 只核查计划文件与 SHA-256，不调用远端写入。正式执行时逐批进行远端预检和提交，失败立即停止，保留 progress.json 和回执。整计划不是原子事务；恢复时重放原计划，不重建随机批次。--fetch-bindings 会取得已有身份与修订号用于计划，正式执行仍受并发修订检查。'
    ],'code':[
        'implementation/.venv/Scripts/python.exe implementation/ops/import_liangzihu.py coverage',
        'implementation/.venv/Scripts/python.exe implementation/ops/import_liangzihu.py preview --source-id synthetic-liangzihu --input implementation/integrations/liangzihu/synthetic-core-example.json --install-definitions',
        'implementation/.venv/Scripts/python.exe implementation/ops/import_liangzihu.py install-definitions --source-id liangzihu-platform --apply',
        'psql --no-psqlrc --quiet --tuples-only --no-align --set ON_ERROR_STOP=1 --file implementation/integrations/liangzihu/readonly-export-core.sql --output implementation/runtime/source-imports/core.jsonl',
        'implementation/.venv/Scripts/python.exe implementation/ops/import_liangzihu.py plan --source-id liangzihu-platform --input implementation/runtime/source-imports/core.jsonl --observed-at 2026-10-19T00:00:00+08:00 --data-nature production --output-dir implementation/runtime/source-imports/plan-001',
        'implementation/.venv/Scripts/python.exe implementation/ops/import_liangzihu.py apply-plan --plan-dir implementation/runtime/source-imports/plan-001 --apply'
    ]})
    manual['sections'].append({'title':'十四 本次交付验证记录','page_break_before':True,'paragraphs':[
        '以下结果来自本轮隔离合成测试。通过项不包含原平台生产数据、真实设备或 PostgreSQL 实库验收。SOURCE_SCHEMA 的确定映射已实现，不代表真实农场实例已经录入。',
        '本地升级使用 upgrade_local.py 在数据库一致副本上先预检，再备份活动文件，执行 005 迁移并只安装定义。旧对象和旧领域包记录逐行摘要核对，实体数量保持不变。报告见 outputs/backend-integration-20261019/upgrade-applied.json。',
        '两份文档与生成脚本一同交付，代码发生变化后应同步更新契约、测试和操作说明。使用公开 GitHub 同步时，必须保留 .gitignore 对真实数据目录的保护。'
    ],'tables':[{'headers':['项目','实际结果'],'widths':[40,60],'rows':[
        ['完整回归',f"{counts['passed']} 通过，{counts['failures']+counts['errors']} 失败，{counts['skipped']} 跳过"],
        ['数据库测试性质','持久 SQLite 隔离数据库与明确合成实例'],
        ['PostgreSQL 实库','未配置独立测试库及驱动，未验收'],
        ['来源结构覆盖','190 表、2114 字段、555 FK 已逐项分类'],
        ['默认启用映射','122 业务来源类、979 属性、409 FK'],
        ['真实平台与现场','未取得真实导出或生产 API，待联调及人工核对']]}]})
    path.write_text(json.dumps(manual,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report_path=OUT/'source_database_report.json';report=json.loads(report_path.read_text(encoding='utf-8'))
    report['title']='梁子湖农场平台数据库分析\n与本体论数据库对比报告'
    report['sections'][9]['paragraphs'][-1]='本轮已实现 SourceMappingService 及 005 迁移，提供来源身份绑定、可回滚预检、领域包与映射原子安装、批次幂等、对象修订、两阶段 FK 解析、单位契约、历史分页和独立来源证据快照。配套适配器支持 122 个来源类、979 个属性和 409 条外键。它首先完成来源记录到语义库的确定映射，不自动把源记录升级为原生观测或已采纳事实。'
    report['sections'][10]['paragraphs']=[p for p in report['sections'][10]['paragraphs'] if not p.startswith('本轮完整回归')]
    report['sections'][10]['paragraphs'].append(f"本轮完整回归结果为 {counts['passed']} 通过、{counts['failures']+counts['errors']} 失败、{counts['skipped']} 跳过。测试使用合成实例与隔离 SQLite；PostgreSQL、原平台真实数据联调和现场验收均未完成。工具可从授权源库只读导出，再按依赖分批导入，逐批保留回执和重放身份。")
    for section in report['sections']:
        section['title']=re.sub(r'[、，：:“”"（）()]',' ',section['title'])
        for table in section.get('tables',[]):
            if len(table['headers'])==4:table['widths']=[16,27,29,28]
            elif len(table['headers'])==3:table['widths']=[24,39,37]
    for ref in report['references']:
        if ref.get('id')=='N04':
            text=(ROOT/ref['path']).read_text(encoding='utf-8')
            ref['line']=next(i for i,l in enumerate(text.splitlines(),1) if 'def _evidence_bundle(' in l)
            ref['url']=ref['url'].split('#')[0]+'#L'+str(ref['line'])
            for section in report['sections']:
                section['sources']=[re.sub(r'(N04 implementation/agri/service.py:)\d+',r'\g<1>'+str(ref['line']),s) for s in section.get('sources',[])]
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=False))


if __name__=='__main__':main()
