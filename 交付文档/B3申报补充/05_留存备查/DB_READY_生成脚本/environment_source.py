"""Revised synthetic environment source without error injection.

Weather retains the existing public reanalysis input. Fish samples are
simulations derived from explicitly named occupied-cohort ledger snapshots.
"""
import json, math, random, statistics
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import defaultdict

TZ=timezone(timedelta(hours=8))
def stamp(day,h=0): return datetime(2025,1,1,h,tzinfo=TZ).__add__(timedelta(days=day)).isoformat()

def _time(value):
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)


def _sample_between(start, end, preferred):
    """Choose a strictly later instant before the next ledger-changing event."""
    if end <= start:
        return None
    if start < preferred < end:
        return preferred
    return start + min(timedelta(minutes=1), (end - start) / 2)


def _sampling_basis(stay, rows, tables):
    """Prefer an in-stay positive daily close, then a valid pre-outflow balance."""
    entered, left = _time(stay['entered_at']), _time(stay['left_at'])
    positive_closes = []
    for row in rows:
        day = _time(str(row['balance_date'])[:10] + 'T00:00:00+08:00')
        close_at = _time(row.get('occurred_at') or (day + timedelta(hours=23)).isoformat())
        sampled_at = close_at + timedelta(minutes=1)
        count = row.get('closing_count', 0)
        biomass = row.get('closing_biomass_kg', 0)
        if (count > 0 and biomass > 0 and entered <= close_at < sampled_at < left
                and sampled_at.date() == day.date()):
            positive_closes.append((sampled_at, row, count, biomass, close_at,
                                    'positive_daily_close',
                                    'Same-day positive ledger close; sample follows the booked snapshot by one minute.'))
    if positive_closes:
        positive_closes.sort(key=lambda item: item[0])
        return positive_closes[len(positive_closes) // 2]

    # A group stocked and fully harvested in the same month may have no positive
    # close. Sample its actual opening or entry book before the first outflow;
    # do not invent a positive closing balance or carry fish beyond departure.
    pond, cohort = stay['pond_id'], stay['cohort_id']
    events_in, events_out = [], []
    for table, pond_key, cohort_key, count_key, mass_key in [
        ('stocking_events', 'pond_id', 'cohort_id', 'count', 'weight_kg'),
        ('transfer_allocations', 'target_pond_id', 'target_cohort_id', 'count', 'weight_kg'),
    ]:
        for event in tables.get(table, []):
            if event.get(pond_key) == pond and event.get(cohort_key) == cohort and event.get(count_key, 0) > 0:
                events_in.append((_time(event['occurred_at']), event[count_key], event[mass_key]))
    for table, pond_key, cohort_key in [
        ('mortality_events', 'pond_id', 'cohort_id'),
        ('transfer_events', 'source_pond_id', 'source_cohort_id'),
        ('harvests', 'pond_id', 'cohort_id'),
    ]:
        for event in tables.get(table, []):
            if event.get(pond_key) == pond and event.get(cohort_key) == cohort:
                events_out.append(_time(event['occurred_at']))
    fallbacks = []
    for row in rows:
        day = _time(str(row['balance_date'])[:10] + 'T00:00:00+08:00')
        day_end = day + timedelta(days=1)
        start, end = max(day, entered), min(day_end, left)
        if start >= end:
            continue
        incoming = sorted(event for event in events_in if start <= event[0] < end)
        outgoing = sorted(event for event in events_out if start <= event < end)
        opening_count = row.get('opening_count', 0)
        opening_biomass = row.get('opening_biomass_kg', 0)
        if opening_count > 0 and opening_biomass > 0 and entered <= day:
            basis_at, count, biomass = day, opening_count, opening_biomass
            next_event = min([end] + outgoing + [event[0] for event in incoming])
            kind = 'opening_before_daily_outflows'
        elif incoming:
            basis_at = incoming[0][0]
            entries = [event for event in incoming if event[0] == basis_at]
            count = sum(event[1] for event in entries)
            biomass = sum(event[2] for event in entries)
            next_event = min([end] + [event for event in outgoing if event > basis_at]
                             + [event[0] for event in incoming if event[0] > basis_at])
            kind = 'entry_before_daily_outflows'
        else:
            continue
        sampled_at = _sample_between(max(start, basis_at), next_event, day + timedelta(hours=9))
        if sampled_at is not None and count > 0 and biomass > 0:
            fallbacks.append((sampled_at, row, count, biomass, basis_at, kind,
                              'No in-stay positive daily close this month; use opening/entry book before daily outflows, without unbooked growth.'))
    if fallbacks:
        fallbacks.sort(key=lambda item: item[0])
        return fallbacks[len(fallbacks) // 2]
    raise ValueError(f"No positive in-stay sampling basis for {pond}/{cohort}/{rows[0]['balance_date'][:7] if rows else 'missing balances'}")


def _growth_samples(tables, out, rng):
    """Emit one 30-fish sample for every main pond/cohort/occupied month."""
    cohorts = {row['id']: row for row in tables.get('cohorts', [])}
    balances = defaultdict(list)
    for row in tables.get('fish_daily_balance', []):
        balances[row['pond_id'], row['cohort_id'], row['balance_date'][:7]].append(row)
    emitted, sample_ids = set(), set()
    stays = sorted((row for row in tables.get('pond_cohort_occupancy', []) if row.get('role') == 'main'),
                   key=lambda row: (row['pond_id'], row['entered_at'], row['cohort_id']))
    for stay in stays:
        entered, left = _time(stay['entered_at']), _time(stay['left_at'])
        month = entered.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while month < left:
            next_month = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
            key = stay['pond_id'], stay['cohort_id'], month.strftime('%Y-%m')
            if entered < next_month and key not in emitted:
                basis = _sampling_basis(stay, balances[key], tables)
                sampled_at, balance, count, biomass, basis_at, kind, note = basis
                cohort = cohorts[stay['cohort_id']]
                species = cohort['species_id']
                sid = f"GR{int(stay['pond_id'][1:])}_{month.month}"
                if cohort.get('parent_cohort_id') or sid in sample_ids:
                    sid += '_' + stay['cohort_id']
                if sid in sample_ids:
                    raise ValueError(f'Duplicate growth sample ID: {sid}')
                emitted.add(key)
                sample_ids.add(sid)
                avg = biomass / count * 1000
                values = [max(1.0, round(avg * rng.uniform(.8, 1.2), 1)) for _ in range(30)]
                for j, weight in enumerate(values):
                    length = round((weight / .025) ** (1 / 3), 2)
                    code = 'A' if weight >= 500 else 'B'
                    out['growth_individuals'].append(dict(
                        id=f'{sid}_{j}', sample_id=sid, species_id=species,
                        body_length_cm=length, total_length_cm=round(length * 1.15, 2),
                        weight_g=weight, commercial_grade=code,
                        grade_definition_id=f'GRADE-{species}-{code}-V1',
                        health_status='no_visual_abnormality', appearance='synthetic_schematic'))
                passed = [value for value in values if value >= 500]
                saleable_ratio = sum(passed) / sum(values)
                estimated_biomass = round(biomass * 1.02, 3)
                out['growth_samples'].append(dict(
                    id=sid, pond_id=stay['pond_id'], cohort_id=stay['cohort_id'], species_id=species,
                    occupancy_id=stay['id'], sampled_at=sampled_at.isoformat(),
                    sample_point_id=f"PT_{stay['pond_id']}", sampling_method='simulated_random_net',
                    sample_size=30, mean_weight_g=round(statistics.mean(values), 3),
                    min_weight_g=min(values), max_weight_g=max(values),
                    std_weight_g=round(statistics.stdev(values), 3), grade_pass_rate=len(passed) / 30,
                    grade_pass_definition_id=f'GRADE-{species}-A-V1', saleable_weight_ratio=saleable_ratio,
                    growth_stage='growout', estimated_count=round(count * 1.02),
                    estimated_biomass_kg=estimated_biomass,
                    estimated_saleable_kg=round(estimated_biomass * saleable_ratio, 3),
                    ledger_balance_id=balance['id'], ledger_basis_at=basis_at.isoformat(),
                    ledger_basis_kind=kind, ledger_basis_note=note,
                    ledger_count=count, ledger_biomass_kg=biomass,
                    estimate_method='ledger_plus_explicit_2pct_bias', estimate_relative_error=.02,
                    confidence_level='synthetic_not_statistical', tool='SIM_scale', operator_id='STAFF01',
                    uniformity_cv=round(statistics.stdev(values) / statistics.mean(values), 4)))
                for label, code, subset in [('under_500g', 'B', [value for value in values if value < 500]),
                                             ('at_least_500g', 'A', passed)]:
                    out['growth_grade_items'].append(dict(
                        id=f'{sid}_{label}', sample_id=sid, species_id=species, grade=label,
                        commercial_grade=code, grade_definition_id=f'GRADE-{species}-{code}-V1',
                        count=len(subset), proportion=len(subset) / 30,
                        sample_weight_kg=sum(subset) / 1000, weight_proportion=sum(subset) / sum(values)))
            month = next_month


def generate(cfg,tables):
    rng=random.Random(cfg['seed']+10); out=defaultdict(list)
    days=list(range(365)) if cfg['mode']=='full' else [0,31,59,90,120,150,165,181,196,212,243,273,304,333,364]
    source=Path(cfg.get('weather_path',Path(__file__).resolve().parents[2]/'public_sources/era5_2025.json'))
    real=json.loads(source.read_text('utf-8')) if source.exists() else None
    weather={}; daily_temp={}
    for d in days:
        for h in range(24):
            k=d*24+h
            vals=([real['hourly'][x][k] for x in ['temperature_2m','relative_humidity_2m','precipitation','shortwave_radiation','wind_speed_10m']] if real else
                  [round(18+12*math.sin(2*math.pi*(d-105)/365)+3*math.sin(2*math.pi*(h-9)/24)+rng.gauss(0,.6),2),round(rng.uniform(45,95),1),round(rng.uniform(0,6),2) if rng.random()<.08 else 0,round(max(0,650*math.sin(math.pi*(h-6)/12)),1),round(rng.uniform(1,20),1)])
            row=dict(id=f'W{k:05}',observed_at=stamp(d,h),air_temperature_c=vals[0],relative_humidity_pct=vals[1],precipitation_mm=vals[2],shortwave_w_m2=vals[3],wind_speed_km_h=vals[4],grid_id='ERA5_30_11475' if real else 'SIM_GRID',grid_latitude=real['latitude'] if real else 30.0,grid_longitude=real['longitude'] if real else 114.75,requested_latitude=30.098191,requested_longitude=114.681967,model='ERA5' if real else 'ASSUMED_SEASONAL',spatial_resolution_degree=.25,timezone='Asia/Shanghai',reference_source_id='S07' if real else 'A01',origin_kind='weather_reanalysis' if real else 'rule_simulation',is_synthetic=not bool(real))
            out['weather_observations'].append(row); weather[d,h]=row
        daily_temp[d]=sum(weather[d,h]['air_temperature_c'] for h in range(24))/24
    for pi in range(1,7):
        p=f'P{pi:02}'; sensor=f'D{pi:02}'; aer=f'A{pi:02}'
        for dev,kind in [(sensor,'multiparameter_sensor'),(aer,'aerator'),(f'F{pi:02}','feeder'),(f'WP{pi:02}','water_pump')]:
            out['devices'].append(dict(id=dev,pond_id=p,device_type=kind,manufacturer='虚构设备厂',model='SIM-1',rated_power_kw=1.5 if kind=='aerator' else .2,position_id=f'PT_{p}',is_synthetic=True))
            out['device_installations'].append(dict(id='INS'+dev,device_id=dev,pond_id=p,installed_at=stamp(0),removed_at='2026-01-01T00:00:00+08:00',effective_end_exclusive=True,position_description='塘口中心模拟点'))
        for m in range(12):
            d=(datetime(2025,m+1,1)-datetime(2025,1,1)).days
            out['device_calibrations'].append(dict(id=f'CAL{pi}_{m+1}',device_id=sensor,started_at=stamp(d,12),ended_at=stamp(d,13),method='synthetic_buffer_test',reference_ph=7.0,offset_ph=.05,result='accepted',operator_id='STAFF01'))
        out['pond_preparations'].append(dict(id=f'PREP{pi:06}',pond_id=p,occurred_at=stamp(4,8),previous_cohort_id=None,previous_cohort_status='not_available_prior_year',operation='drain;dry;desilt;repair;refill',disinfectant_product_id='PR02',disinfectant_status='synthetic_format_dose_not_recommendation',dose_kg=150,application_method='pond_bottom_synthetic',refill_at=stamp(6,8),water_source='虚构蓄水池',water_level_m=1.8,water_test_status='synthetic_check_pass',equipment_check='pass',operator_id='STAFF01',reviewer_id='STAFF02',repair_cost_yuan=0))
        for d in days:
            for h in range(24):
                low=pi==1 and d==196 and 4<=h<=7
                cal=h==12 and datetime.fromisoformat(stamp(d)).day==1
                temp=round(daily_temp[d]*.65+8+.8*math.sin(2*math.pi*(h-10)/24)+pi*.12,2)
                do=round(2.3+.35*(h-4),2) if low else round(8.5-.08*temp+1.0*math.sin(2*math.pi*(h-10)/24)+rng.gauss(0,.15),2)
                ph=round(7.5+.35*math.sin(2*math.pi*(h-9)/24)+rng.gauss(0,.04),2)
                out['water_observations'].append(dict(id=f'O{pi}_{d:03}_{h:02}',pond_id=p,device_id=sensor,observed_at=stamp(d,h),recorded_at=(datetime.fromisoformat(stamp(d,h))+timedelta(minutes=1)).isoformat(),sample_point_id=f'PT_{p}',depth_m=.5,temperature_c=temp,do_mg_l=do,ph=7.05 if cal else ph,raw_ph=7.10 if cal else round(ph+.05,2),ph_correction=-.05,method='synthetic_sensor',measurement_context='calibration' if cal else 'pond',environment_condition='low_oxygen' if low else 'routine',quality_flag='calibration_excluded_from_pond_statistics' if cal else 'generated_valid',missing_reason=None,review_status='simulation_checked',weather_id=weather[d,h]['id']))
            for h in [6,18]:
                low=pi==1 and d==196 and h==6
                out['patrol_events'].append(dict(id=f'PAT{pi}_{d}_{h}',pond_id=p,occurred_at=stamp(d,h),operator_id='STAFF01',weather_id=weather[d,h]['id'],swimming='surface_gasping' if low else 'routine',feeding_behavior='reduced' if low else 'routine',bank_gathering=False,water_color='green',transparency_cm=round(rng.uniform(25,45),1),odor='none',algae='moderate',foam='none',dead_count=0,dead_weight_kg=0,dead_size_g=None,discovery_point_id=f'PT_{p}',aerator_status='running' if low else 'scheduled',pump_status='idle',feeder_status='scheduled',exception_description='synthetic_low_DO' if low else None,action='start_aerator' if low else 'routine_observation'))
            hours=4 if pi==1 and d==196 else (6 if 150<=d<=250 else 2)
            out['device_operations'].append(dict(id=f'OP{pi}_{d}',device_id=aer,pond_id=p,started_at=stamp(d,4),ended_at=stamp(d,4+hours),duration_h=hours,energy_kwh=1.5*hours,energy_basis='non_metered_device_estimate; utility_cost_includes_other_farm_loads',reason='low_oxygen_response' if pi==1 and d==196 else 'scheduled',command_id=f'CMD{pi}_{d}'))
            out['control_commands'].append(dict(id=f'CMD{pi}_{d}',device_id=aer,planned_at=stamp(d,3),issued_at=stamp(d,4),executed_at=stamp(d,4),command='start',result='success',alarm='low_DO' if pi==1 and d==196 else None))
            if d%7==0 or cfg['mode']=='sample':
                sid=f'WS{pi}_{d}'
                out['water_samples'].append(dict(id=sid,pond_id=p,sampled_at=stamp(d,9),sample_point_id=f'PT_{p}',depth_m=.5,sampler_id='STAFF01',received_at=stamp(d,11),lab_name='虚构检测室',sampling_method='grab_sample'))
                specs=[('TAN_as_N','mg/L as N',.18,.01,'colorimetric'),('NO2_as_N','mg/L as N',.025,.005,'colorimetric'),('NO3_as_N','mg/L as N',.5,.02,'colorimetric'),('transparency','cm',35,1,'Secchi'),('conductivity','uS/cm',310,1,'electrode'),('salinity','ppt',.1,.01,'conductivity_derived'),('ORP','mV',180,1,'electrode'),('chlorophyll_a','ug/L',25,.5,'spectrophotometry')]
                for j,(analyte,unit,mean,lod,method) in enumerate(specs):
                    bdl=analyte=='NO2_as_N' and d%28==0
                    failed=analyte=='chlorophyll_a' and pi==6 and d==84
                    value=None if bdl or failed else round(mean*rng.uniform(.7,1.3),3)
                    out['water_test_results'].append(dict(id=f'{sid}_{j}',sample_id=sid,analyte_code=analyte,value=value,raw_value='<0.005' if bdl else ('FAILED' if failed else str(value)),corrected_value=value,unit=unit,expression_basis='as_N' if analyte.endswith('as_N') else 'native',method=method,instrument_id='LAB_SIM01',detection_limit=lod,result_status='detection_failed' if failed else ('below_detection_limit' if bdl else 'reported'),missing_reason='test_failure' if failed else ('below_detection_limit' if bdl else None),verified_by='STAFF02',reported_at=stamp(d,16)))
            if d%30==0:
                out['water_operations'].append(dict(id=f'WO{pi}_{d}',pond_id=p,started_at=stamp(d,10),ended_at=stamp(d,11),operation='exchange',inflow_m3=150,outflow_m3=150,water_source='虚构蓄水池',product_id=None,dose_kg=None,dose_status='not_applicable_no_additive',do_before_mg_l=5.7,do_after_mg_l=6.1,fish_before='routine',fish_after='routine'))
        out['device_maintenance'].append(dict(id=f'MNT{pi}',device_id=sensor,pond_id=p,started_at='2025-08-15T12:10:00+08:00',ended_at='2025-08-15T12:45:00+08:00',fault='intermittent_upload',operation='cable_reseat_between_hourly_observations',replacement_device_id=None,cost_yuan=0,cost_status='included_in_staff_labor',result='restored'))
    _growth_samples(tables, out, rng)
    for i,(status,desc) in enumerate([('suspected','摄食减少，未确诊'),('excluded','复核无目标病原证据；非真实检验'),('suspected','浮头与低氧同时发生')],1):
        cid=f'HC{i}'; p=f'P{i:02}'
        if i==3:p='P01'
        out['health_cases'].append(dict(id=cid,pond_id=p,cohort_id='C01' if i==3 else f'C{2*i-1:02}',discovered_at='2025-07-16T06:00:00+08:00',affected_count=20,incidence_rate=.002,death_count=0,mortality_per_day=0,duration_days=2,diagnosis_status=status,preliminary_judgment='pending_verification',description=desc,action='observe;check_water;sample',recovery='routine_after_followup',recurrence=False))
        out['case_observations'].append(dict(id=f'CO{i}',case_id=cid,observed_at='2025-07-16T06:00:00+08:00',behavior='reduced_feeding',skin_description='示意，无实际病变标签',gill_description='pending',viscera_description='not_examined',diagnosis_basis='synthetic_format_only'))
        out['diagnostic_tests'].append(dict(id=f'DT{i}',case_id=cid,lab_name='虚构检测室',report_number=f'SIM-R{i}',sampled_at='2025-07-16T10:00:00+08:00',reported_at='2025-07-17T10:00:00+08:00',pathogen_code='UNSPECIFIED_PENDING',method='format_test_only',result='inconclusive' if status=='suspected' else 'simulated_negative',diagnosis_status=status))
        out['treatment_events'].append(dict(id=f'TR{i}',case_id=cid,pond_id=p,cohort_id=f'C{2*i-1:02}',started_at='2025-07-16T07:00:00+08:00',stopped_at='2025-07-18T07:00:00+08:00',operation_reason='health_observation',product_id=None,product_name=None,approval_number=None,manufacturer_lot=None,active_ingredient=None,dose=None,concentration=None,method='observation_and_aeration_only',course_days=2,target_species='团头鲂',target_disease='pending',contraindications='pending_product_evidence',withdrawal_days=None,withdrawal_status='not_applicable_no_drug_administered',earliest_harvest_date=None,product_parameter_status='pending_no_applicable_label',operator_id='STAFF01',advisor_id='STAFF02',purchase_cost_yuan=0,effect='behavior_recovered',adverse_reaction='not_applicable',execution_status='non_drug_care'))
    for d in days:
        for kind,base,sp in [('武昌鱼',18,'SP01'),('鲢',7,'SP02'),('豆粕',3.3,None)]:
            for channel in ['pond_gate','acquisition','wholesale','retail']:
                out['price_observations'].append(dict(id=f'PR{d}_{kind}_{channel}',observed_at=stamp(d,10),original_product_name=kind,species_id=sp,species_mapping_status='not_applicable_ingredient' if kind=='豆粕' else 'scenario_defined',product_type='feed_ingredient' if kind=='豆粕' else 'fish',grade='500-750g' if kind=='武昌鱼' else 'ungraded',commercial_grade='A' if kind=='武昌鱼' else None,grade_definition_id='GRADE-SP01-A-V1' if kind=='武昌鱼' else None,mapping_relation='subset_of' if kind=='武昌鱼' else ('not_applicable_ingredient' if kind=='豆粕' else 'ungraded'),quality_grade='standard',freshness='not_applicable' if kind=='豆粕' else 'live',region='湖北虚构市场',market_id='SIM_MARKET',channel=channel,price_yuan_per_kg=round(base*(1+.1*math.sin(d/365*2*math.pi))+rng.uniform(-.3,.3),2),observation_kind='simulated_quote',transaction_volume_kg=None,volume_status='not_reported_quote',tax_included=False,freight_included=False,packaging_included=False,commission_included=False,collected_at=stamp(d,11),credibility='scenario_assumption_not_validated_history',reference_source_id='S05',origin_kind='rule_simulation',is_synthetic=True))
    out['dictionaries']=[dict(id=f'DIC{i:03}',domain=domain,code=code,label=label,status=status) for i,(domain,code,label,status) in enumerate([
        ('staff','STAFF01','虚构记录员','synthetic'),('staff','STAFF02','虚构审核员','synthetic'),('product_type','vaccine','疫苗','not_used_no_label'),('product_type','drug','药品','pending_label_no_administration'),('product_type','health_product','动保产品','not_used'),('symptom','reduced_feeding','摄食降低','observational'),('disease','UNSPECIFIED_PENDING','未定疾病','pending'),('pathogen','UNSPECIFIED_PENDING','未定病原','pending'),('quality_grade','standard','模拟普通级','synthetic'),('channel','wholesale','批发','synthetic'),('income_type','fish_sale','鱼产品销售','synthetic'),('allocation','area','塘面面积分摊','synthetic'),('missing','not_collected','未采集','defined'),('missing','not_received','未收到','defined'),('missing','detection_failed','检测失败','defined'),('missing','not_applicable','不适用','defined'),('missing','below_detection_limit','低于检出限','defined'),('value_kind','estimated','估算','defined')],1)]
    for r in out['treatment_events']:
        r['precautions']='No medicine administered; product label and qualified review required before any drug use'
        if r['case_id']=='HC3':r['cohort_id']='C01'
    for i,r in enumerate(out['case_observations']):r['behavior']=['reduced_feeding','abnormal_swimming','surface_gasping'][i%3]
    out['pond_maintenance']=[dict(id=f'PM{pi}',pond_id=f'P{pi:02}',occurred_at='2025-01-05T08:00:00+08:00',operation='embankment_repair_and_drain_inspection',renovation_status='no_structural_modification',cost_basis='included_in_monthly_labor',cost_yuan=0,operator_id='PERSON01') for pi in range(1,7)]
    for domain,values in [('cost_category',sorted({r['category'] for r in tables.get('cost_entries',[])})),('grade',sorted({r['grade'] for r in tables.get('harvest_grade_items',[])})),('test_item',sorted({r['analyte_code'] for r in out['water_test_results']}))]:
        for v in values:out['dictionaries'].append(dict(id=f'DIC{len(out["dictionaries"])+1:03}',domain=domain,code=v,label=v,status='synthetic_defined'))
    return dict(out)
