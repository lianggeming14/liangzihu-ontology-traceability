from pathlib import Path
from collections import defaultdict
import json
ROOT=Path(__file__).resolve().parents[2]
VERSION='DB-READY-1.0.0'
def integrate(t,cfg):
    # Join environmental context to business events without changing quantity ledgers.
    for r in t['water_observations']:
        if '2025-01-05T08:00:00+08:00'<=r['observed_at']<'2025-01-07T08:00:00+08:00':
            for key in ['temperature_c','do_mg_l','ph','raw_ph']:r[key]=None
            r['measurement_context']='pond_dry_preparation';r['missing_reason']='not_applicable_no_water';r['quality_flag']='planned_non_observation_slot'
    obs={(r['pond_id'],r['observed_at'][:13]):r for r in t['water_observations']}
    for r in t['feeding_events']:
        r['device_id']='F'+r['pond_id'][1:]; r['feeding_area']='PT_'+r['pond_id']
        w=obs.get((r['pond_id'],r['occurred_at'][:13]))
        if w:
            r['water_temperature_c']=w['temperature_c'];r['dissolved_oxygen_mg_l']=w['do_mg_l'];r['water_observation_id']=w['id'];r['weather_id']=w['weather_id']
            r['environment_value_basis']='joined_synthetic_sensor_observation'
    for r in t['devices']:
        r['position_id']='PT_'+r['pond_id']
    for table,rows in t.items():
        for r in rows:
            for k in ['operator_id','sampler_id','advisor_id','verified_by']:
                if r.get(k) in ['STAFF01','STAFF02']:r[k]=r[k].replace('STAFF','PERSON')
            if r.get('reviewer_id')=='STAFF02':r['reviewer_id']='PERSON02'
    t['persons']=[dict(id='PERSON01',name='模拟记录员',role='recorder',is_fictional=True),dict(id='PERSON02',name='模拟审核员',role='reviewer',is_fictional=True)]
    manifest=json.loads((ROOT/'public_sources/attachment/sample_manifest.json').read_text('utf-8'))
    t['sources']=[]
    for sid in sorted({r['source_id'] for r in manifest['files']}):
        entries=[r for r in manifest['files'] if r['source_id']==sid]
        t['sources'].append(dict(id=sid,title=entries[0]['source_kind'],url=entries[0]['requested_url'],origin_kind=entries[0]['source_kind'],is_synthetic=False,local_path='public_sources/attachment/public_samples/'+entries[0]['relative_path'],access_conditions=entries[0]['note'],retrieved_at=entries[0]['retrieved_at_utc'],use_boundary='format_reference_not_local_measurement',version='attachment_snapshot_2026-10-31'))
    weather=json.loads((ROOT/'public_sources/weather_download.json').read_text('utf-8'))
    t['sources'].extend([dict(id='S07',title='Open-Meteo ERA5 2025 hourly',url=weather['url'],origin_kind='weather_reanalysis',is_synthetic=False,local_path='public_sources/era5_2025.json',access_conditions=weather['license'],retrieved_at='2026-10-31',use_boundary='external_grid_not_pond_station',version='ERA5_snapshot_2026-10-31'),dict(id='A01',title='本地明确模拟假设',url=None,origin_kind='scenario_assumption',is_synthetic=True,local_path='scenario/assumptions.json',access_conditions='synthetic_generated_for_this_task',retrieved_at=None,use_boundary='not_real_observation_or_prescription',version=VERSION)])
    t['production_plans']=[dict(id='PLAN-SYNTH-2025',farm_id='F01',year=2025,mode='ordinary_pond_polyculture',technical_document_path='scenario/assumptions.json',responsible_person_id='PERSON02',start_date='2025-01-01',end_date='2025-12-31',status='synthetic_cycle_closed')]
    # Daily aggregate is derived from actual feeding events; never independent random data.
    daily=defaultdict(float)
    for r in t['feeding_events']:daily[r['pond_id'],r['occurred_at'][:10]]+=r['quantity_kg']
    for r in t['feeding_events']:r['daily_total_kg']=round(daily[r['pond_id'],r['occurred_at'][:10]],3)
    balance={(r['cohort_id'],r['balance_date']):r for r in t['fish_daily_balance']}
    for r in t['health_cases']:
        b=balance.get((r['cohort_id'],r['discovered_at'][:10]))
        if b:
            r['population_denominator']=b['closing_count'];r['incidence_rate']=round(r['affected_count']/b['closing_count'],8)
            r['denominator_basis']='same_day_ledger_closing_count_synthetic'
    mortal=defaultdict(list)
    for r in t['mortality_events']:mortal[r['pond_id'],r['occurred_at'][:10]].append(r)
    for r in t['patrol_events']:
        deaths=mortal.get((r['pond_id'],r['occurred_at'][:10]),[]) if r['occurred_at'][11:13]=='18' else []
        if deaths:
            r['dead_count']=sum(v.get('count',v.get('dead_count',0)) for v in deaths)
            r['dead_weight_kg']=round(sum(v.get('weight_kg',v.get('dead_weight_kg',0)) for v in deaths),3)
            r['mortality_event_ids']=';'.join(v['id'] for v in deaths)
        if r['occurred_at']<'2025-01-10T09:00:00+08:00' or r['occurred_at']>'2025-11-20T09:00:00+08:00':
            r['swimming']='not_applicable_empty_pond';r['feeding_behavior']='not_applicable_empty_pond';r['bank_gathering']=None
    # All 12 production event types are discoverable through a typed registry.
    event_tables=['pond_preparations','stocking_events','feeding_events','water_samples','patrol_events','growth_samples','health_cases','treatment_events','water_operations','device_operations','mortality_events','disposal_events','transfer_events','harvests']
    t['event_registry']=[dict(id=table+':'+r['id'],event_table=table,event_record_id=r['id'],pond_id=r.get('pond_id'),cohort_id=r.get('cohort_id'),occurred_at=next((r[k] for k in ['occurred_at','sampled_at','started_at','discovered_at'] if r.get(k)),None)) for table in event_tables for r in t.get(table,[])]
