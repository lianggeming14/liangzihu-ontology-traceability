"""Source-only structural and observational checks; never repairs observations."""
from collections import defaultdict,Counter
from decimal import Decimal,InvalidOperation
from datetime import datetime
from statistics import median

def issue(table,row,field,code,message,action='review',severity='warning',evidence=None):
    return {'table':table,'row_key':row['_l2_row_key'],'record_id':row.get('id',''),'field':field,'code':code,'severity':severity,'action':action,'message':message,'evidence':evidence or {}}
def num(s):
    try:
        v=Decimal(s)
        return v if v.is_finite() else None
    except (InvalidOperation,TypeError,ValueError):return None
def dt(s):
    try:
        parsed=datetime.fromisoformat(s)
        return parsed if parsed.tzinfo is not None else None
    except (ValueError,TypeError):return None
def result(code,total,failed=0,blocked=0,description=''):
    return {'code':code,'status':'fail' if failed else ('blocked' if blocked else 'pass'),'checked_count':total,'failed_count':failed,'blocked_count':blocked,'description':description,'details':{}}

def structural_checks(tables,schema):
    issues=[];checks=[];edges=[];indices={};pk_fail=0
    for table,rows in tables.items():
        groups=defaultdict(list)
        for r in rows:
            if not r.get('id'):
                issues.append(issue(table,r,'id','PRIMARY_KEY_MISSING','主键缺失；保留原记录，不能分配虚构业务编号。','quarantine','error'));pk_fail+=1
            else:groups[r['id']].append(r)
        indices[table]=groups
        for key,group in groups.items():
            if len(group)>1:
                for r in group:
                    issues.append(issue(table,r,'id','PRIMARY_KEY_CONFLICT','同主键多条非精确重复记录；全部待核，未任意保留一个版本。','quarantine','error',{'peer_source_rows':[x['_l2_row_key'] for x in group]}));pk_fail+=1
    checks.append(result('PRIMARY_KEY_UNIQUE',sum(len(v) for v in tables.values()),pk_fail,description='原行精确去重后的非空、唯一主键'))
    n=bad=0
    for table,rows in tables.items():
        for fk in schema.get('tables',{}).get(table,{}).get('foreign_keys',[]):
            field=fk['field'];target=fk['references']['table'];target_field=fk['references']['field']
            target_index=defaultdict(list)
            for tr in tables.get(target,[]):target_index[tr.get(target_field,'')].append(tr)
            for row in rows:
                value=row.get(field,'')
                if not value:continue
                n+=1;matches=target_index.get(value,[])
                if len(matches)!=1:
                    code='FOREIGN_KEY_NOT_FOUND' if not matches else 'FOREIGN_KEY_AMBIGUOUS'
                    issues.append(issue(table,row,field,code,'外键不能唯一关联到目标表，保留原标识待核。','quarantine','error',{'value':value,'target_table':target,'target_field':target_field,'matches':len(matches)}));bad+=1
                else:edges.append((row['_l2_row_key'],matches[0]['_l2_row_key'],field,target))
        pair={'attachment_links':('entity_table','entity_id'),'event_registry':('event_table','event_record_id')}.get(table)
        if pair:
            for row in rows:
                tf,rf=pair;target=row.get(tf,'');rid=row.get(rf,'');n+=1;matches=indices.get(target,{}).get(rid,[])
                if len(matches)!=1:
                    issues.append(issue(table,row,rf,'POLYMORPHIC_FOREIGN_KEY','动态目标表及记录编号不能唯一关联。','quarantine','error',{'table_value':target,'id_value':rid,'matches':len(matches)}));bad+=1
                else:edges.append((row['_l2_row_key'],matches[0]['_l2_row_key'],rf,target))
    checks.append(result('DECLARED_AND_POLYMORPHIC_FOREIGN_KEYS',n,bad,description='按显式表名和字段检查；不从别的字段猜测修复ID'))
    return issues,checks,edges

def observation_checks(tables,blocked_fields):
    issues=[];checks=[]
    water=tables.get('water_observations',[])
    n_missing=n_context=n_consistency=n_range=0
    for r in water:
        context=r.get('measurement_context','')
        planned=context=='pond_dry_preparation' and r.get('missing_reason')=='not_applicable_no_water'
        if context!='pond':
            n_context+=1
            issues.append(issue('water_observations',r,'measurement_context','NON_POND_OBSERVATION','校准或计划无水时槽保留，排除池塘正常观测统计。','annotate','info',{'context':context}))
        for f in ['temperature_c','do_mg_l','ph','raw_ph']:
            if not r.get(f) and not planned:
                issues.append(issue('water_observations',r,f,'MISSING_EXPECTED_OBSERVATION','应有的观测值缺失且无计划无水依据，保留空值，不插值或补零。','review','warning'));n_missing+=1
        for f,lo,hi in [('temperature_c',Decimal('-2'),Decimal('45')),('do_mg_l',Decimal('0'),Decimal('30')),('ph',Decimal('0'),Decimal('14')),('raw_ph',Decimal('0'),Decimal('14'))]:
            v=num(r.get(f,''))
            if v is not None and (r['_l2_row_key'],f) not in blocked_fields and not lo<=v<=hi:
                issues.append(issue('water_observations',r,f,'OBSERVATION_PLAUSIBILITY_RANGE','超出本清洗规则的宽松物理合理性检查范围；只标记，不替换数值。','review','warning',{'lower':str(lo),'upper':str(hi),'value':str(v)}));n_range+=1
        a,b,c=(num(r.get(f,'')) for f in ['ph','raw_ph','ph_correction'])
        if all(x is not None for x in (a,b,c)) and abs(a-b-c)>Decimal('0.011'):
            issues.append(issue('water_observations',r,'ph','PH_CORRECTION_INCONSISTENT','pH与原读数加校正偏移不一致；不能以原读数反算覆盖。','review','warning',{'ph':str(a),'raw_ph':str(b),'correction':str(c)}));n_consistency+=1
    checks.extend([result('EXPECTED_WATER_VALUES',len(water)*4,n_missing,description='计划无水除外，空值不补'),result('WATER_PLAUSIBILITY_RANGE',len(water),n_range,description='仅用于待核候选，不作为生物学确诊'),result('PH_CORRECTION_IDENTITY',len(water),n_consistency,description='pH=raw_ph+ph_correction，容差0.011')])
    # No observation replacement: robust neighbour and run-length tests only label candidates.
    series=defaultdict(list)
    for r in water:
        t=dt(r.get('observed_at',''))
        if t is not None and r.get('measurement_context')=='pond':series[r.get('device_id','')].append((t,r))
    spike_count=stuck_count=0
    for device,seq in series.items():
        seq.sort(key=lambda x:(x[0],x[1]['_l2_row_key']))
        for field,floor in [('temperature_c',Decimal('5')),('do_mg_l',Decimal('3.5'))]:
            for i,(t,r) in enumerate(seq):
                v=num(r.get(field,''))
                if v is None or (r['_l2_row_key'],field) in blocked_fields or r.get('environment_condition')=='low_oxygen':continue
                neighbours=[num(rr.get(field,'')) for tt,rr in seq[max(0,i-4):i]+seq[i+1:i+5] if abs((tt-t).total_seconds())<=6*3600 and (rr['_l2_row_key'],field) not in blocked_fields and rr.get('environment_condition')!='low_oxygen']
                neighbours=[x for x in neighbours if x is not None]
                if len(neighbours)<5:continue
                center=median(neighbours);mad=median([abs(x-center) for x in neighbours]);threshold=max(floor,8*mad)
                if abs(v-center)>threshold:
                    issues.append(issue('water_observations',r,field,'TEMPORAL_OUTLIER_CANDIDATE','相邻时段稳健比较出现突变；保留原值并等待传感器或现场证据核查。','review','warning',{'neighbour_median':str(center),'threshold':str(threshold),'value':str(v)}));spike_count+=1
        run=[]
        def flush():
            nonlocal stuck_count
            if len(run)>=6:
                for t,r in run:
                    issues.append(issue('water_observations',r,'temperature_c','SENSOR_STUCK_CANDIDATE','同设备至少6个连续小时水温完全相同，列为卡值候选，不自动改值。','review','warning',{'hours':len(run),'device_id':device,'run_start':run[0][0].isoformat(),'run_end':run[-1][0].isoformat()}));stuck_count+=1
        for t,r in seq:
            value=r.get('temperature_c','')
            if not value or (r['_l2_row_key'],'temperature_c') in blocked_fields:
                flush();run=[];continue
            if run and (value!=run[-1][1].get('temperature_c') or (t-run[-1][0]).total_seconds()!=3600):flush();run=[]
            run.append((t,r))
        flush()
    checks.extend([result('TEMPORAL_OUTLIER_SCREEN',len(water),spike_count,description='同设备相邻6小时，最少5个邻点，偏离>max(固定下限,8*MAD)'),result('SENSOR_FLAT_RUN_SCREEN',len(water),stuck_count,description='连续6小时相同水温仅标候选')])
    by_time=defaultdict(list);peer_bad=peer_checked=0
    valid_ponds={r.get('id') for r in tables.get('ponds',[])}
    for r in water:
        if r.get('measurement_context')=='pond' and r.get('pond_id') in valid_ponds and num(r.get('temperature_c','')) is not None and (r['_l2_row_key'],'temperature_c') not in blocked_fields:
            by_time[r.get('observed_at')].append(r)
    for group in by_time.values():
        for r in group:
            peers={x.get('pond_id'):num(x['temperature_c']) for x in group if x.get('pond_id')!=r.get('pond_id')}
            if len(peers)<4:continue
            peer_checked+=1;m=median(peers.values());v=num(r['temperature_c'])
            if abs(v-m)>=Decimal('3'):
                issues.append(issue('water_observations',r,'temperature_c','CROSS_POND_TEMPERATURE_CANDIDATE','同刻至少4个其他塘水温中位数与本值相差至少3°C，仅标记复核候选；塘间真实差异仍可能存在。',evidence={'peer_median':str(m),'value':str(v),'threshold_c':'3','peer_count':len(peers)}));peer_bad+=1
    checks.append(result('CROSS_POND_TEMPERATURE_SCREEN',peer_checked,peer_bad,description='跨塘比较只生成待核候选，禁止据此改温度'))
    tests=tables.get('water_test_results',[]);test_bad=0
    for r in tests:
        if r.get('result_status')=='reported' and not r.get('value'):
            issues.append(issue('water_test_results',r,'value','MISSING_REPORTED_TEST_VALUE','检测状态为已报告但数值为空，保留空值待核。'));test_bad+=1
        if r.get('result_status') in {'below_detection_limit','detection_failed'}:
            issues.append(issue('water_test_results',r,'value','CENSORED_OR_FAILED_TEST','保留检测限定符和失败原因；不把低于检出限或失败转换成0。','annotate','info',{'status':r.get('result_status'),'raw_value':r.get('raw_value')}))
        value=num(r.get('value',''));corrected=num(r.get('corrected_value',''))
        if value is not None and corrected is not None and (r['_l2_row_key'],'value') not in blocked_fields and abs(value-corrected)>Decimal('0.000001'):
            issues.append(issue('water_test_results',r,'value','LAB_VALUE_CONFLICT','value与corrected_value不一致；两个源值都保留，未任选其一覆盖。'));test_bad+=1
    checks.append(result('LAB_RESULT_STATE',len(tests),test_bad,description='检测状态、数值、限定符与校正值'))
    semantic_n=semantic_bad=0
    for r in tables.get('price_observations',[]):
        semantic_n+=1
        if not r.get('species_id') and 'unresolved' in r.get('species_mapping_status',''):
            issues.append(issue('price_observations',r,'species_id','SOURCE_SPECIES_MAPPING_UNRESOLVED','市场泛称不能唯一映射物种；保留原商品名及空物种ID，禁止直接归入团头鲂。'));semantic_bad+=1
    for r in tables.get('patrol_events',[]):
        semantic_n+=1
        if (num(r.get('dead_count','')) or Decimal(0))>0 and not r.get('dead_size_g'):
            issues.append(issue('patrol_events',r,'dead_size_g','SOURCE_DEAD_FISH_SIZE_UNDOCUMENTED','有死鱼数量但规格为空且无取得状态，作为源端资料待核；不从死亡明细倒填。'));semantic_bad+=1
    for r in tables.get('inventory_lot_status',[]):
        semantic_n+=1
        if not r.get('available_quantity') and r.get('closing_quantity'):
            issues.append(issue('inventory_lot_status',r,'available_quantity','SOURCE_USABLE_INVENTORY_UNCONFIRMED','批次可用量未确认；账面库存不等于可用库存，保留空值和有效期状态。'));semantic_bad+=1
    checks.append(result('SOURCE_SEMANTIC_UNRESOLVED',semantic_n,semantic_bad,description='原生来源资料缺口，与注入的数据错误分开解释'))
    # Prices are compared only with the same source product/specification/market/month.
    groups=defaultdict(list)
    for r in tables.get('price_observations',[]):
        key=tuple(r.get(f,'') for f in ['original_product_name','grade','market_id','channel'])+(r.get('observed_at','')[:7],)
        if (r['_l2_row_key'],'price_yuan_per_kg') not in blocked_fields:groups[key].append(r)
    price_bad=0
    for key,rs in groups.items():
        values=[num(r.get('price_yuan_per_kg','')) for r in rs];values=[v for v in values if v is not None]
        if len(values)<8:continue
        m=median(values);mad=median([abs(v-m) for v in values]);threshold=max(Decimal('5'),6*mad)
        for r in rs:
            v=num(r.get('price_yuan_per_kg',''))
            if v is not None and abs(v-m)>threshold:
                issues.append(issue('price_observations',r,'price_yuan_per_kg','PRICE_OUTLIER_CANDIDATE','同产品/规格/市场/渠道/月度报价偏离中位数，保留待核，不替换为均价。',evidence={'median':str(m),'threshold':str(threshold)}));price_bad+=1
    checks.append(result('PRICE_ROBUST_SCREEN',sum(map(len,groups.values())),price_bad,description='报价分组统计仅作异常候选'))
    # Source timestamps are not rewritten to manufacture a plausible ordering.
    timing_total=timing_bad=0
    for table,rows in tables.items():
        for r in rows:
            anchor=next((f for f in ['observed_at','occurred_at','sampled_at','reported_at'] if r.get(f)),None)
            pairs=[('started_at','ended_at'),('planned_at','issued_at'),('issued_at','executed_at')]
            if anchor:pairs.extend([(anchor,'recorded_at'),(anchor,'uploaded_at')])
            if r.get('recorded_at'):pairs.extend([('recorded_at','uploaded_at'),('uploaded_at','ingested_at')])
            for left,right in pairs:
                a=dt(r.get(left,''));b=dt(r.get(right,''))
                if a is None or b is None:continue
                timing_total+=1
                if b<a:
                    issues.append(issue(table,r,right,'TIME_ORDER_CONFLICT','时间先后关系冲突，保留全部原时刻待核。',evidence={'earlier_field':left,'later_field':right,'earlier':a.isoformat(),'later':b.isoformat()}));timing_bad+=1
            a=dt(r.get(anchor,'')) if anchor else None;b=dt(r.get('uploaded_at',''))
            if a and b and (b-a).total_seconds()>24*3600:
                issues.append(issue(table,r,'uploaded_at','UPLOAD_DELAY_OVER_24H','上传距业务/观测时刻超过24小时；按发生时间保留，不改成上传时间。',evidence={'anchor_field':anchor,'delay_hours':round((b-a).total_seconds()/3600,4)}));timing_bad+=1
    checks.append(result('TIMESTAMP_ORDER_AND_LATENCY',timing_total,timing_bad,description='时刻先后及>24小时上传延迟标记；迟报不改写事实'))
    return issues,checks
