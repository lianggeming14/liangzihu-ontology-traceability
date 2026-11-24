"""Deterministic revised fictional aquaculture business ledger for database use.

All identities and business values are synthetic assumptions, not husbandry advice.
Integer grams, cents and fish counts are used internally to prevent hidden balancing.
The sampling mode reduces livestock and feeding frequency; its feeding rows explicitly
represent interval totals. The full mode records actual simulated feeding sessions.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
import math
import random

REVISION_METADATA = {
    'version': 'db-ready-business-v1',
    'source': 'Revised simulation code; no reference/baseline or anomaly answers used.',
    'interface': 'generate(cfg) -> dict[str, list[dict]]',
    'assumptions': {
        'feeding_time': 'Keep the daily total and session count; move a session after entry '
                        'with a 30 minute margin, and before exit. Initial entry day uses 11:00. '
                        'The feed, inventory issue and expense share one occurrence time.',
        'harvest_individuals': 'Each harvest receives synthetic positive integer gram individual '
                               'weights. Balanced random pair offsets around its exact mean '
                               'conserve original harvest count and mass. These are simulated '
                               'individuals, not field measurements or a validated growth distribution.',
        'harvest_randomness': 'Independent per-harvest Random seed made from cfg.seed and harvest id; '
                              'does not consume growth or feeding randomness.',
        'grade_definition': 'Per-species version V1: A weight_g >= 500; B 1 <= weight_g < 500. '
                            'Quality grade is independent. Only nonempty grade and sales lines are emitted.',
        'grade_price': 'Synthetic CNY/kg: SP01 A buyer1 15.2, buyer2 15.8; B minus 1.4. '
                       'SP02 A buyer1 7.8, buyer2 8.4; B minus 1.4. Each price line names its grade definition.',
        'PR02_opening_lot': 'Fictional material scenario, not a real product label: manufactured '
                            'December 1 before cfg.year; assumed shelf life 365 days. For 2025 this '
                            'is 2024-12-01 through 2025-12-01. Remaining book stock is expired '
                            'pending disposal at year end, available_quantity=0; no writeoff invented.',
        'payroll_partner': 'PAY01 is a fictional payroll collection/payment group representing '
                           'the simulated staff payroll; it is not an actual supplier or legal entity. '
                           'Monthly labor cost remains CNY 4500.',
        'service_cost_time': 'Source-linked cost and cost allocations cannot predate the originating '
                             'physical event. Disposal expense follows disposal. Service payment and '
                             'cash allocation use the cost occurrence timestamp; annual rent remains a prepayment.',
    },
    'new_tables': {
        'harvest_grade_individuals': {
            'grain': 'one simulated individual within one harvest',
            'fields': ['harvest_id', 'harvest_grade_item_id', 'pond_id', 'cohort_id', 'species_id',
                       'individual_number', 'grade', 'grade_definition_id', 'weight_g', 'weight_unit',
                       'weight_basis'],
            'additive_policy': 'Aggregate weight_g/count here OR harvest summaries; never add both.',
        },
    },
    'new_fields': {
        'harvest_grade_items': ['grade_definition_id', 'min_weight_g', 'max_weight_g', 'grading_basis'],
        'sale_items': ['grade_definition_id', 'price_basis'],
        'harvest_sale_allocations': ['grade_definition_id'],
        'opening_balances': ['manufacture_on', 'expires_on', 'shelf_life_days', 'expiry_status',
                             'expiry_parameter_basis'],
        'feeding_events': ['feeding_time_basis'],
        'partners': ['partner_scope'],
    },
    'required_grade_definitions': [
        {'id': f'GRADE-{species}-{grade}-V1', 'species_id': species, 'grade': grade,
         'lower_bound': 500 if grade == 'A' else 1, 'upper_bound': None if grade == 'A' else 500,
         'unit': 'g', 'lower_inclusive': True, 'upper_inclusive': False, 'version': 'V1',
         'definition_basis': 'fictional_simulation_rule_not_market_standard'}
        for species in ('SP01', 'SP02') for grade in ('A', 'B')
    ],
}

TABLES = (
    'farms ponds species cohorts pond_cohort_occupancy stocking_events '
    'transfer_events transfer_allocations mortality_events disposal_events '
    'fish_daily_balance feeding_events products partners purchases purchase_items '
    'inventory_movements opening_balances harvests harvest_grade_items harvest_grade_individuals sales '
    'sale_items harvest_sale_allocations settlements settlement_deductions '
    'cash_transactions cash_allocations cost_entries cost_allocations inventory_lot_status'
).split()


def generate(cfg):
    """Return table-name -> rows for a complete, internally balanced scenario."""
    year = int(cfg.get('year', 2025))
    mode = cfg.get('mode', 'full')
    if mode not in ('sample', 'full'):
        raise ValueError('mode must be sample or full')
    scenario_seed = int(cfg.get('seed', 20251031))
    t = {name: [] for name in TABLES}
    seq = defaultdict(int)
    row_index = {}
    start, end = date(year, 1, 10), date(year, 11, 20)
    split_day, partial_day = date(year, 6, 15), date(year, 9, 15)
    scale = 1 if mode == 'full' else 0.1

    def stamp(day, hour=9, minute=0):
        return f'{day.isoformat()}T{hour:02d}:{minute:02d}:00+08:00'

    def add(table, prefix, day=None, **fields):
        seq[table] += 1
        rid = fields.pop('id', f'{prefix}{seq[table]:06d}')
        row = {'id': rid, 'farm_id': 'F01', **fields}
        if day is not None:
            when = row.setdefault('occurred_at', stamp(day))
            dt = datetime.fromisoformat(when)
            row.setdefault('recorded_at', (dt + timedelta(minutes=12)).isoformat())
            row.setdefault('uploaded_at', (dt + timedelta(minutes=35)).isoformat())
            row.setdefault('ingested_at', (dt + timedelta(minutes=40)).isoformat())
            row.setdefault('updated_at', row['ingested_at'])
            row.setdefault('event_id', rid)
            row.setdefault('source_record_id', 'SIM-' + rid)
            row.setdefault('recorder_id', 'PERSON01')
            row.setdefault('reviewer_id', 'PERSON02')
            row.setdefault('source_system', 'fictional_farm_ledger_db_ready_v1')
            row.setdefault('review_status', 'synthetic_reviewed')
            row.setdefault('quality_flag', 'synthetic_valid')
            row.setdefault('is_estimated', False)
            row.setdefault('source_timezone', 'Asia/Shanghai')
            row.setdefault('time_precision', 'minute')
        t[table].append(row)
        row_index[rid] = row
        return row

    add('farms', 'F', id='F01', name='澄禾示范渔场（虚构）',
        operator_name='澄禾水产经营主体（虚构）', address='湖北模拟区域（非真实经营地址）',
        contact='不适用：虚构主体无真实联系方式', identity_status='fictional',
        longitude=114.684, latitude=30.102, crs='EPSG:4326',
        production_mode='ordinary_freshwater_pond_polyculture', timezone='Asia/Shanghai')
    for p in range(1, 7):
        area = 6000 + p * 200
        add('ponds', 'P', id=f'P{p:02d}', name=f'{p}号模拟塘', area_m2=area,
            area_mu=round(area / (2000 / 3), 4), mean_depth_m=1.8,
            maximum_depth_m=2.2, effective_volume_m3=area * 1.8,
            shape='rectangle', bottom_type='soil_with_silt',
            inlet_condition='independent_inlet', outlet_condition='independent_outlet',
            water_source='fictional_reservoir', commissioned_on=f'{year-3}-01-01',
            current_status='cycle_closed', geometry_id=f'GIS-P{p:02d}',
            equipment_configuration='aerator,pump,feeder,water_quality_sensor',
            previous_cycle_id=None, previous_cycle_status='not_collected')
        t['ponds'][-1].update(centroid_longitude=round(114.680+((p-1)%3)*.004,3),
                             centroid_latitude=round(30.100+((p-1)//3)*.004,3),
                             maintenance_history_status='no_major_pond_reconstruction_in_2025',
                             maintenance_history_note='routine_bottom_desilting_in_pond_preparations')
    for code, cn, latin, raw, role in [
        ('SP01', '团头鲂', 'Megalobrama amblycephala', '武昌鱼', 'main'),
        ('SP02', '鲢', 'Hypophthalmichthys molitrix', '鲢鱼', 'companion'),
    ]:
        add('species', 'SP', id=code, standard_name=cn, scientific_name=latin,
            original_name=raw, species_code=code, common_commercial_name=raw,
            mapping_status='scenario_identity_explicit',
            mapping_basis='scenario species declared; no generic bream mapping',
            strain=None, strain_status='not_collected', origin='fictional_Hubei_hatchery',
            brand=None, brand_status='not_applicable', geographical_indication_qualified=False,
            geographical_indication_status='not_claimed', default_role=role)
    partners = [
        ('SUP01', '模拟苗种供应单位', 'seed_supplier'),
        ('SUP02', '模拟饲料供应单位', 'feed_supplier'),
        ('SUP03', '模拟物资供应单位', 'materials_supplier'),
        ('BUY01', '模拟鲜活鱼采购客户甲', 'customer'),
        ('BUY02', '模拟鲜活鱼采购客户乙', 'customer'),
        ('LOG01', '模拟运输服务单位', 'logistics'),
        ('LAB01', '模拟检测机构', 'laboratory'),
        ('DIS01', '模拟无害化处理服务单位', 'disposal'),
        ('LAND01', '模拟塘口出租单位', 'landlord'),
        ('UTIL01', '模拟供电服务单位', 'utility'),
        ('PAY01', '模拟工资支付集合伙伴', 'payroll_payment_group'),
    ]
    for pid, name, kind in partners:
        add('partners', 'PART', id=pid, name=name + '（虚构）', partner_type=kind,
            identity_status='fictional', contact=None, contact_status='not_applicable',
            region='湖北模拟区域', currency='CNY')
        if pid == 'PAY01':
            t['partners'][-1]['partner_scope'] = 'fictional_staff_payroll_collection_group_not_real_legal_entity'
    for pid, name, typ, unit, price, species in [
        ('PR01', '模拟配合饲料A', 'feed', 'kg', 4.2, None),
        ('PR02', '模拟生石灰（塘体准备格式样例）', 'pond_preparation_material', 'kg', 1.2, None),
        ('PR03', '团头鲂苗种', 'seed', 'fish', 0.75, 'SP01'),
        ('PR04', '鲢苗种', 'seed', 'fish', 0.45, 'SP02'),
    ]:
        add('products', 'PR', id=pid, product_name=name, product_type=typ,
            unit=unit, assumed_unit_price_cny=price, species_id=species,
            brand='虚构试验品牌' if typ == 'feed' else None,
            brand_status='fictional' if typ == 'feed' else 'not_applicable',
            coarse_protein_pct=28 if typ == 'feed' else None,
            particle_diameter_mm=3 if typ == 'feed' else None,
            shelf_life_days=180 if typ == 'feed' else (365 if pid == 'PR02' else None),
            manufacturer='模拟生产单位（虚构）', registration_number=None,
            registration_status='not_applicable_non_medicine',
            parameter_basis='synthetic_assumption_not_product_recommendation')

    # Product quantities and valuation use kg for materials and count for seed.
    inv_quantity = defaultdict(int)  # grams for material; fish for seed
    inv_value = defaultdict(int)     # cents
    movement_queue = []

    def queue_movement(day, product, kind, units, cents, source_type, source_id,
                       pond_id=None, cohort_id=None, hour=7, minute=0, batch=None):
        movement_queue.append(dict(day=day, product=product, kind=kind, units=units,
                                   cents=cents, source_type=source_type, source_id=source_id,
                                   pond_id=pond_id, cohort_id=cohort_id, hour=hour, minute=minute,
                                   batch=batch or f'LOT-{product}-{year}'))

    def cost(day, category, cents, pond_id=None, cohort_id=None, source_type=None,
             source_id=None, period_start=None, period_end=None, **extra):
        supplier={'seed_consumption':'SUP01','feed_consumption':'SUP02',
                  'pond_preparation_material':'SUP03','mortality_disposal':'DIS01',
                  'pond_rent':'LAND01','electricity':'UTIL01','labor':'PAY01'}.get(category)
        cost_time = extra.pop('occurred_at', None)
        if cost_time is None:
            source = row_index.get(source_id)
            cost_time = source.get('occurred_at') if source else None
            if category == 'mortality_disposal':
                disposal = next((r for r in reversed(t['disposal_events'])
                                 if source_id in (r.get('transfer_event_id'), r.get('mortality_event_id'))), None)
                if disposal:
                    cost_time = max(cost_time or disposal['occurred_at'], disposal['occurred_at'])
            if cost_time is None:
                movement = next((m for m in reversed(movement_queue) if m['source_id'] == source_id), None)
                cost_time = stamp(day, movement['hour'], movement['minute']) if movement else stamp(day)
        row = add('cost_entries', 'COST', day, occurred_at=cost_time, category=category,supplier_id=supplier,
                  amount_cny=cents/100, currency='CNY', pond_id=pond_id,
                  cohort_id=cohort_id, source_type=source_type, source_id=source_id,
                  cost_type='direct' if pond_id else 'shared',
                  period_start=(period_start or day).isoformat(),
                  period_end=(period_end or day).isoformat(),
                  settlement_deduction_id=None,
                  profit_treatment='subtract_from_gross_sales_once',
                  allocation_method='direct' if pond_id else 'pond_area', **extra)
        targets = [(pond_id, 1)] if pond_id else [(p['id'], p['area_m2']) for p in t['ponds']]
        denom = sum(weight for _, weight in targets)
        remaining = cents
        for i, (pid, weight) in enumerate(targets):
            val = remaining if i == len(targets)-1 else round(cents * weight/denom)
            remaining -= val
            add('cost_allocations', 'CA', day, occurred_at=cost_time, cost_entry_id=row['id'],
                pond_id=pid, cohort_id=cohort_id, beneficiary_type='cohort' if cohort_id else 'pond',
                amount_cny=val/100, currency='CNY',
                allocation_basis=weight, allocation_basis_unit='share' if pond_id else 'm2',
                allocation_ratio=weight/denom, allocation_method=row['allocation_method'],
                period_start=row['period_start'], period_end=row['period_end'])
        return row

    def purchase(day, product, units, cents, supplier, batch=None):
        pu = add('purchases', 'PUR', day, supplier_id=supplier, invoice_number=None,
                 invoice_status='fictional_document_reference', contract_number=f'SIM-CON-{len(t["purchases"])+1:03}',
                 gross_amount_cny=cents/100, amount_cny=cents/100, currency='CNY',
                 tax_status='synthetic_tax_included', received_on=day.isoformat(),
                 received_at=stamp(day,6),purchase_time_basis='supplier_invoice_booking_after_physical_receipt',
                 is_consumption_cost=False, payment_status='paid')
        is_seed = product in ('PR03', 'PR04')
        qty = units if is_seed else units/1000
        item = add('purchase_items', 'PI', day, purchase_id=pu['id'], product_id=product,
                   product_batch_id=batch or f'LOT-{product}-{year}',
                   quantity=qty, unit='fish' if is_seed else 'kg',
                   unit_price_cny=round(cents/100/qty, 6), amount_cny=cents/100,
                   supplier_id=supplier, valuation_method='fixed_synthetic_unit_cost',
                   transaction_time_basis='purchase_document_booking_not_goods_arrival',
                   manufacture_on=None if is_seed else day.isoformat(),
                   expires_on=None if is_seed else (day+timedelta(days=180)).isoformat(),
                   expiry_status='not_applicable_live_seed' if is_seed else 'fictional_shelf_life_assumption')
        queue_movement(day, product, 'receipt', units, cents, 'purchase_item', item['id'], hour=6, batch=batch)
        cash = add('cash_transactions', 'CASH', day + timedelta(days=2),
                   direction='payment', counterparty_id=supplier, amount_cny=cents/100,
                   currency='CNY', payment_method='simulated_bank_transfer',
                   bank_reference=f'SIM-PAY-{pu["id"]}', balance_scope='business_operating_cash')
        add('cash_allocations', 'CALA', day+timedelta(days=2),
            cash_transaction_id=cash['id'], purchase_id=pu['id'], settlement_id=None,
            cost_entry_id=None, amount_cny=cents/100, allocation_type='purchase_payment')
        return item

    for product, units, cents in [('PR01', int(400*scale)*1000, int(168000*scale)),
                                  ('PR02', 1200000, 144000)]:
        qty = units/1000
        op = add('opening_balances', 'OPEN', date(year,1,1), balance_type='inventory',
                 product_id=product, quantity=qty, unit='kg', amount_cny=cents/100,
                 currency='CNY', valuation_method='fixed_synthetic_unit_cost',
                 as_of=f'{year}-01-01T00:00:00+08:00', pond_id=None, cohort_id=None)
        if product == 'PR02':
            manufactured = date(year-1, 12, 1)
            op.update(manufacture_on=manufactured.isoformat(),
                      expires_on=(manufactured + timedelta(days=365)).isoformat(),
                      shelf_life_days=365, expiry_status='fictional_opening_material_shelf_life_assumption',
                      expiry_parameter_basis='new_synthetic_scenario_not_actual_product_label')
        queue_movement(date(year,1,1), product, 'opening', units, cents, 'opening_balance', op['id'],
                       batch=f'LOT-{product}-OPEN-{year}')
    add('opening_balances', 'OPEN', date(year,1,1), balance_type='cash', product_id=None,
        quantity=None, unit=None, amount_cny=1000000.0, currency='CNY',
        valuation_method='nominal', as_of=f'{year}-01-01T00:00:00+08:00',
        pond_id=None, cohort_id=None)
    add('opening_balances', 'OPEN', date(year,1,1), balance_type='accounts_receivable',
        product_id=None, quantity=None, unit=None, amount_cny=0.0, currency='CNY',
        valuation_method='nominal', as_of=f'{year}-01-01T00:00:00+08:00', pond_id=None, cohort_id=None)
    for p in range(1,7):
        pid=f'P{p:02d}'
        queue_movement(date(year,1,5), 'PR02', 'issue', -150000, -18000,
                       'pond_preparation', f'PREP{p:06d}', pid, batch=f'LOT-PR02-OPEN-{year}')
        cost(date(year,1,5), 'pond_preparation_material', 18000, pid,
             source_type='inventory_issue', source_id=f'PREP{p:06d}')

    # Exact daily simulated fish ledger. Split children retain species and lineage.
    states, cohort_map = {}, {}
    for p in range(1,7):
        for s in range(2):
            cid = f'C{(p-1)*2+s+1:02d}'
            count = int((6000 if s == 0 else 600) * scale)
            mean_g = 60 if s == 0 else 100
            pid, species = f'P{p:02d}', f'SP{s+1:02d}'
            cohort = add('cohorts', 'COH', id=cid, pond_id=pid, species_id=species,
                parent_cohort_id=None, cohort_definition='biological_group_with_traceable_lineage',
                role='main' if s==0 else 'companion', start_date=start.isoformat(),
                expected_harvest_date=end.isoformat(), actual_end_date=end.isoformat(),
                initial_count=count, initial_weight_kg=count*mean_g/1000,
                initial_mean_weight_g=mean_g, initial_density_fish_per_mu=round(count/t['ponds'][p-1]['area_mu'],4),
                strain=None, strain_status='not_collected', seed_origin='fictional_Hubei_hatchery',
                original_commercial_name='武昌鱼' if s==0 else '鲢鱼', brand=None,
                geographical_indication_qualified=False, status='closed',
                technical_plan_id='PLAN-SYNTH-2025', responsible_person_id='PERSON02')
            cohort_map[cid]=cohort
            states[cid]={'pond':pid,'species':species,'count':0,'grams':0,'main':s==0}
            add('pond_cohort_occupancy','OCC',start,pond_id=pid,cohort_id=cid,
                entered_at=stamp(start,10),left_at=stamp(end,14),role=cohort['role'],
                entry_reason='stocking',exit_reason='final_harvest')
            product='PR03' if s==0 else 'PR04'
            seed_cents=count*(75 if s==0 else 45)
            pi=purchase(start,product,count,seed_cents,'SUP01',batch=f'SEED-{cid}')
            st=add('stocking_events','STK',start,occurred_at=stamp(start,10),pond_id=pid,cohort_id=cid,
                species_id=species,purchase_item_id=pi['id'],product_id=product,seed_batch_id=f'SEED-{cid}',
                supplier_id='SUP01',count=count,weight_kg=count*mean_g/1000,mean_weight_g=mean_g,
                size_distribution='synthetic_uniform_group',stocking_density_fish_per_mu=cohort['initial_density_fish_per_mu'],
                unit_price_cny=seed_cents/100/count,total_cost_cny=seed_cents/100,
                transport_method='oxygenated_tank',transport_duration_hours=2.5,
                transport_mortality_count=0,transport_mortality_rate=0.0,
                health_status='visual_check_only_no_diagnosis',quarantine_certificate_id=None,
                quarantine_status='not_received',water_temperature_c=11.0,dissolved_oxygen_mg_l=7.5,
                temperature_difference_c=0.5,acclimation_method='gradual_temperature_equalization',
                count_basis='synthetic_count',weight_basis='synthetic_weighing')
            queue_movement(start,product,'issue',-count,-seed_cents,'stocking_event',st['id'],pid,cid,hour=10,batch=f'SEED-{cid}')
            cost(start,'seed_consumption',seed_cents,pid,cid,'stocking_event',st['id'])

    feed_pending = defaultdict(int)
    feed_daily = defaultdict(int)
    harvest_groups=defaultdict(list)
    num_days=(end-start).days+1
    for di in range(num_days):
        day=start+timedelta(days=di)
        daily={}
        for cid,state in states.items():
            daily[cid]={'opening_count':state['count'],'opening_biomass_g':state['grams'],
                        'stocked_count':0,'stocked_g':0,'transfer_in_count':0,'transfer_in_g':0,
                        'transfer_out_count':0,'transfer_out_g':0,'mortality_count':0,'mortality_g':0,
                        'harvest_count':0,'harvest_g':0,'growth_g':0}
        if day==start:
            for cid,state in states.items():
                c=cohort_map[cid]
                state['count']=c['initial_count']; state['grams']=round(c['initial_weight_kg']*1000)
                daily[cid]['stocked_count']=state['count'];daily[cid]['stocked_g']=state['grams']
        # Growth follows a declared seasonal scenario, not an empirical production model.
        seasonal=max(0.15,math.sin(math.pi*(day.timetuple().tm_yday-25)/365))
        for cid,state in states.items():
            if state['count']:
                gain=round(state['count']*(2.7 if state['main'] else 3.7)*seasonal)
                if state['pond']=='P01' and day==date(year,7,16):gain=round(gain*.25)
                state['grams']+=gain;daily[cid]['growth_g']=gain
                if state['main']:
                    daily_feed=round(gain*1.55)
                    feed_pending[cid]+=daily_feed
                    feed_daily[(day,cid)]=daily_feed
        if day==split_day:
            source=states['C01'];move_each=int(900*scale);loss=int(10*scale)
            total=2*move_each+loss;out_g=round(source['grams']*total/source['count'])
            loss_g=round(out_g*loss/total);available_g=out_g-loss_g
            tr=add('transfer_events','TR',day,occurred_at=stamp(day,11),source_pond_id='P01',
                source_cohort_id='C01',pond_id='P01',cohort_id='C01',species_id='SP01',
                transferred_out_count=total,transferred_out_weight_kg=out_g/1000,
                received_count=2*move_each,received_weight_kg=available_g/1000,
                loss_count=loss,loss_weight_kg=loss_g/1000,reason='reduce_density_split_one_group_to_two_ponds',
                mean_weight_g=round(out_g/total,3),size_basis='derived_transfer_mass_per_count',
                loss_cause='synthetic_handling_loss',operation_person_id='PERSON01')
            source['count']-=total;source['grams']-=out_g
            daily['C01']['transfer_out_count']=total;daily['C01']['transfer_out_g']=out_g
            for n,(cid,pid) in enumerate([('C13','P02'),('C14','P03')]):
                grams=available_g//2 if n==0 else available_g-available_g//2
                states[cid]={'pond':pid,'species':'SP01','count':move_each,'grams':grams,'main':True}
                cohort=add('cohorts','COH',id=cid,pond_id=pid,species_id='SP01',parent_cohort_id='C01',
                    cohort_definition='split_child_biological_group',role='main',start_date=day.isoformat(),
                    expected_harvest_date=end.isoformat(),actual_end_date=end.isoformat(),
                    initial_count=move_each,initial_weight_kg=grams/1000,initial_mean_weight_g=round(grams/move_each,3),
                    initial_density_fish_per_mu=round(move_each/t['ponds'][n+1]['area_mu'],4),
                    strain=None,strain_status='not_collected',seed_origin='inherited_C01',
                    original_commercial_name='武昌鱼',brand=None,geographical_indication_qualified=False,
                    status='closed',technical_plan_id='PLAN-SYNTH-2025',responsible_person_id='PERSON02')
                cohort_map[cid]=cohort
                add('pond_cohort_occupancy','OCC',day,pond_id=pid,cohort_id=cid,entered_at=stamp(day,11),
                    left_at=stamp(end,14),role='main',entry_reason='split_transfer',exit_reason='final_harvest')
                add('transfer_allocations','TRA',day,occurred_at=stamp(day,11,15),event_id=tr['id'],transfer_event_id=tr['id'],
                    source_pond_id='P01',source_cohort_id='C01',target_pond_id=pid,target_cohort_id=cid,
                    pond_id=pid,cohort_id=cid,count=move_each,weight_kg=grams/1000)
                daily[cid]={k:0 for k in daily['C01']}
                daily[cid]['transfer_in_count']=move_each;daily[cid]['transfer_in_g']=grams
            add('disposal_events','DIS',day,occurred_at=stamp(day,11,30),event_id=tr['id'],transfer_event_id=tr['id'],
                mortality_event_id=None,pond_id='P01',cohort_id='C01',count=loss,weight_kg=loss_g/1000,
                method='sealed_collection_by_fictional_service',service_partner_id='DIS01',
                cost_cny=20.0,certificate_id=None,certificate_status='synthetic_record_only')
            t['disposal_events'][-1].update(recovery_method='hand_net_collection',transport_method='sealed_container')
            cost(day,'mortality_disposal',2000,'P01','C01','transfer_event',tr['id'])
        if di>0 and di%17==0:
            for cid,state in list(states.items()):
                if state['count']<2:continue
                count=max(1,round(state['count']*(0.0013 if state['main'] else 0.001)))
                grams=round(state['grams']*count/state['count'])
                state['count']-=count;state['grams']-=grams
                daily[cid]['mortality_count']=count;daily[cid]['mortality_g']=grams
                mo=add('mortality_events','MORT',day,occurred_at=stamp(day,8),pond_id=state['pond'],
                    cohort_id=cid,species_id=state['species'],count=count,weight_kg=grams/1000,
                    mean_weight_g=round(grams/count,3),possible_cause='undetermined_background_loss',
                    cause_status='unconfirmed',related_health_case_id=None,
                    discovery_location=f'GIS-{state["pond"]}-OUTLET',count_basis='synthetic_count')
                add('disposal_events','DIS',day,event_id=mo['id'],mortality_event_id=mo['id'],
                    transfer_event_id=None,pond_id=state['pond'],cohort_id=cid,count=count,weight_kg=grams/1000,
                    method='sealed_collection_by_fictional_service',service_partner_id='DIS01',
                    cost_cny=5.0,certificate_id=None,certificate_status='synthetic_record_only')
                t['disposal_events'][-1].update(recovery_method='hand_net_collection',transport_method='sealed_container')
                cost(day,'mortality_disposal',500,state['pond'],cid,'mortality_event',mo['id'])
        if day in (partial_day,end):
            for cid,state in list(states.items()):
                count=state['count'] if day==end else state['count']//3
                grams=state['grams'] if day==end else round(state['grams']*count/state['count'])
                state['count']-=count;state['grams']-=grams
                daily[cid]['harvest_count']=count;daily[cid]['harvest_g']=grams
                tare=round(grams*0.018)
                ha=add('harvests','HAR',day,occurred_at=stamp(day,14),pond_id=state['pond'],cohort_id=cid,
                    species_id=state['species'],harvest_type='final' if day==end else 'partial',
                    method='seine_net',count=count,gross_weight_kg=(grams+tare)/1000,
                    tare_weight_kg=tare/1000,net_weight_kg=grams/1000,saleable_weight_kg=grams/1000,
                    harvest_loss_count=0,harvest_loss_weight_kg=0.0,transport_loss_weight_kg=0.0,
                    deduction_weight_kg=0.0,quality_grade='synthetic_standard',
                    health_status='visual_check_only_no_diagnosis',residue_test_status='not_collected',
                    disposition='sale',vehicle_id='SIM-VEH01',weighing_basis='synthetic_exact_mass')
                # Synthetic individual weights are allocated without changing a single
                # harvest gram or fish. Pair offsets add dispersion while conserving mass.
                grade_rng = random.Random(f'{scenario_seed}:harvest-grade-v1:{ha["id"]}')
                whole_g, extra_g = divmod(grams, count)
                weights = [whole_g + (i < extra_g) for i in range(count)]
                grade_rng.shuffle(weights)
                for i in range(0, count - 1, 2):
                    spread = min(round(whole_g * 0.35), weights[i]-1, weights[i+1]-1)
                    offset = grade_rng.randint(-spread, spread)
                    weights[i] += offset
                    weights[i+1] -= offset
                individual_groups = {'A': [], 'B': []}
                for individual_number, weight_g in enumerate(weights, 1):
                    grade = 'A' if weight_g >= 500 else 'B'
                    individual_groups[grade].append((individual_number, weight_g))
                for grade, individuals in individual_groups.items():
                    if not individuals:
                        continue
                    n = len(individuals)
                    g = sum(weight for _, weight in individuals)
                    definition_id = f'GRADE-{state["species"]}-{grade}-V1'
                    hg=add('harvest_grade_items','HGI',day,occurred_at=stamp(day,14,30),event_id=ha['id'],harvest_id=ha['id'],
                        pond_id=state['pond'],cohort_id=cid,species_id=state['species'],grade=grade,
                        count=n,net_weight_kg=g/1000,weight_ratio=g/grams,
                        mean_weight_g=round(g/n,3),quality_grade='synthetic_standard',
                        grade_definition_id=definition_id,
                        min_weight_g=min(weight for _, weight in individuals),
                        max_weight_g=max(weight for _, weight in individuals),
                        grading_basis='aggregated_actual_simulated_integer_gram_individuals')
                    for individual_number, weight_g in individuals:
                        add('harvest_grade_individuals', 'HGIN', day, occurred_at=stamp(day,14,30),
                            event_id=ha['id'], harvest_id=ha['id'], harvest_grade_item_id=hg['id'],
                            pond_id=state['pond'], cohort_id=cid, species_id=state['species'],
                            individual_number=individual_number, grade=grade,
                            grade_definition_id=definition_id, weight_g=weight_g, weight_unit='g',
                            weight_basis='synthetic_integer_gram_allocation_not_field_measurement')
                    harvest_groups[(day,state['species'])].append((ha,hg,g))
        # Full mode: 1 winter feeding, 2 warm-season sessions, on actual occupied groups.
        for cid,state in states.items():
            if not state['main'] or not feed_pending[cid]:continue
            low_oxygen=state['pond']=='P01' and day==date(year,7,16)
            emit=mode=='full' or di%28==27 or day in (partial_day,end,split_day) or low_oxygen
            if not emit:continue
            total=feed_pending[cid];feed_pending[cid]=0
            sessions=1 if mode=='sample' or day.month in (1,2) or low_oxygen else 2
            remaining=total
            for si in range(sessions):
                grams=total//sessions if si==0 else remaining
                remaining-=grams
                cents=round(grams*0.42)
                feed_hour=12 if low_oxygen else (7 if si==0 else 12)
                feed_at = datetime.fromisoformat(stamp(day, feed_hour))
                occupancy = next(r for r in t['pond_cohort_occupancy']
                                 if r['cohort_id'] == cid and r['pond_id'] == state['pond'])
                entered = datetime.fromisoformat(occupancy['entered_at'])
                left = datetime.fromisoformat(occupancy['left_at'])
                if feed_at <= entered:
                    feed_at = entered + timedelta(minutes=30)
                    if occupancy['entry_reason'] == 'stocking':
                        feed_at = max(feed_at, datetime.fromisoformat(stamp(day,11)))
                if feed_at >= left:
                    feed_at = left - timedelta(minutes=30)
                if not entered < feed_at < left:
                    raise ValueError(f'No occupied feeding time for {cid} on {day}')
                fe=add('feeding_events','FEED',day,occurred_at=feed_at.isoformat(),
                    pond_id=state['pond'],cohort_id=cid,species_id='SP01',product_id='PR01',
                    product_batch_id=f'LOT-PR01-{year}-{day.month:02d}',quantity_kg=grams/1000,
                    daily_total_kg=total/1000,unit_price_cny=4.2,cost_cny=cents/100,
                    feeding_method='automatic_feeder',device_id=f'F{state["pond"][1:]}',
                    feeding_area=f'GIS-{state["pond"]}-FEED',frequency_per_day=sessions,
                    feeding_intensity='normal',leftover_status='none_observed',competition_behavior='normal',
                    water_temperature_c=round(9+20*seasonal,2),dissolved_oxygen_mg_l=round(7.2-1.8*seasonal,2),
                    weather_condition='synthetic_seasonal_context',
                    adjustment_reason='low_oxygen_dawn_feed_suspended_daily_growth_and_feed_reduced_75pct' if low_oxygen else 'biomass_and_season_rule',
                    suspended_session_count=1 if low_oxygen else 0,
                    suspended_session_local_time='07:00' if low_oxygen else None,
                    related_environment_scenario='LOW_DO_P01_20250716' if low_oxygen else None,
                    environment_value_basis='standalone_seasonal_planning_estimate_not_sensor_observation',
                    measurement_basis='interval_total' if mode=='sample' else 'session_weight',
                    aggregation_note='sample compresses feeding into 28-day interval totals' if mode=='sample' else None,
                    nutrition_parameter_basis='fictional_feed_profile',coarse_protein_pct=28,
                    particle_diameter_mm=3,shelf_life_days=180,
                    manufacture_on=date(year,day.month,1).isoformat(),
                    expires_on=(date(year,day.month,1)+timedelta(days=180)).isoformat(),
                     feed_brand='虚构试验品牌',inventory_selection_policy='current_month_purchase_lot',
                     feeding_time_basis='scheduled_inside_occupancy_after_entry_before_exit')
                queue_movement(day,'PR01','issue',-grams,-cents,'feeding_event',fe['id'],state['pond'],cid,
                               hour=feed_at.hour,minute=feed_at.minute,batch=f'LOT-PR01-{year}-{day.month:02d}')
                cost(day,'feed_consumption',cents,state['pond'],cid,'feeding_event',fe['id'])
        for cid,state in states.items():
            d=daily[cid]
            row=add('fish_daily_balance','FDB',day,occurred_at=stamp(day,23),pond_id=state['pond'],cohort_id=cid,
                species_id=state['species'],balance_date=day.isoformat(),
                opening_count=d['opening_count'],stocked_count=d['stocked_count'],
                transfer_in_count=d['transfer_in_count'],transfer_out_count=d['transfer_out_count'],
                mortality_count=d['mortality_count'],harvest_count=d['harvest_count'],adjustment_count=0,
                closing_count=state['count'],opening_biomass_kg=d['opening_biomass_g']/1000,
                stocked_weight_kg=d['stocked_g']/1000,transfer_in_weight_kg=d['transfer_in_g']/1000,
                transfer_out_weight_kg=d['transfer_out_g']/1000,mortality_weight_kg=d['mortality_g']/1000,
                harvest_weight_kg=d['harvest_g']/1000,growth_weight_kg=d['growth_g']/1000,
                biomass_adjustment_kg=0.0,closing_biomass_kg=state['grams']/1000,
                closing_mean_weight_g=round(state['grams']/state['count'],3) if state['count'] else None,
                feed_quantity_kg=feed_daily.get((day,cid),0)/1000,
                biomass_basis='exact_generator_state_not_field_truth',
                growth_basis='declared_seasonal_increment_assumption',feed_to_growth_ratio_assumed=1.55 if state['main'] else None,
                companion_growth_basis=None if state['main'] else 'natural_food_assumption_no_direct_feed_cost',
                estimate_error_kg=0.0)

    # Buy enough per month for that month's issues, preserving positive inventory.
    monthly_need=defaultdict(int)
    for m in movement_queue:
        if m['product']=='PR01' and m['kind']=='issue':monthly_need[m['day'].month]+=-m['units']
    for month,grams in sorted(monthly_need.items()):
        order_g=(math.ceil(grams/100000)+2)*100000
        purchase(date(year,month,1),'PR01',order_g,round(order_g*0.42),'SUP02',
                 batch=f'LOT-PR01-{year}-{month:02d}')
    # A small opening batch remains segregated after packaging damage and is discarded.
    opening_loss_g=int(400*scale)*1000
    queue_movement(date(year,2,10),'PR01','loss',-opening_loss_g,-round(opening_loss_g*0.42),
                   'inventory_count','COUNT-OPEN-PACKAGE-DAMAGE',hour=17,batch=f'LOT-PR01-OPEN-{year}')
    cost(date(year,2,10),'inventory_spoilage',round(opening_loss_g*0.42),
         source_type='inventory_count',source_id='COUNT-OPEN-PACKAGE-DAMAGE')
    loss_g=int(25000*scale)
    queue_movement(date(year,8,10),'PR01','loss',-loss_g,-round(loss_g*0.42),
                   'inventory_count','COUNT-20250810',hour=17,batch=f'LOT-PR01-{year}-08')
    cost(date(year,8,10),'inventory_spoilage',round(loss_g*0.42),source_type='inventory_count',source_id='COUNT-20250810')
    # A return and an explicit positive inventory adjustment exercise all movement types.
    ret_g=int(10000*scale)
    queue_movement(date(year,8,11),'PR01','issue',-ret_g,-round(ret_g*0.42),'unused_feed_checkout','CHECKOUT01',hour=7,batch=f'LOT-PR01-{year}-08')
    queue_movement(date(year,8,11),'PR01','return',ret_g,round(ret_g*0.42),'unused_feed_return','RETURN01',hour=17,batch=f'LOT-PR01-{year}-08')
    queue_movement(date(year,8,12),'PR02','adjustment',5000,600,'inventory_count','COUNT-20250812',hour=17,batch=f'LOT-PR02-OPEN-{year}')
    lot_quantity=defaultdict(int)
    lot_value=defaultdict(int)
    for m in sorted(movement_queue,key=lambda x:(x['day'],x['hour'],x['minute'],x['kind']=='issue',x['source_id'])):
        product=m['product'];seed=product in ('PR03','PR04');denom=1 if seed else 1000
        before_qty,before_val=inv_quantity[product],inv_value[product]
        inv_quantity[product]+=m['units'];inv_value[product]+=m['cents']
        lot_key=(product,m['batch'])
        lot_before_qty,lot_before_val=lot_quantity[lot_key],lot_value[lot_key]
        lot_quantity[lot_key]+=m['units'];lot_value[lot_key]+=m['cents']
        add('inventory_movements','INV',m['day'],occurred_at=stamp(m['day'],m['hour'],m['minute']),
            product_id=product,product_batch_id=m['batch'],movement_type=m['kind'],
            quantity_delta=m['units']/denom,unit='fish' if seed else 'kg',amount_delta_cny=m['cents']/100,
            opening_quantity=before_qty/denom,closing_quantity=inv_quantity[product]/denom,
            opening_value_cny=before_val/100,closing_value_cny=inv_value[product]/100,
            lot_opening_quantity=lot_before_qty/denom,lot_closing_quantity=lot_quantity[lot_key]/denom,
            lot_opening_value_cny=lot_before_val/100,lot_closing_value_cny=lot_value[lot_key]/100,
            valuation_method='fixed_synthetic_unit_cost_with_cent_rounding',
            source_type=m['source_type'],source_id=m['source_id'],
            pond_id=m['pond_id'],cohort_id=m['cohort_id'],
            movement_reason='explicit_count_surplus' if m['kind']=='adjustment' else m['kind'])

    # Every harvest splits between two sales; each sale combines multiple harvests.
    settlements=[]
    for (day,species),items in sorted(harvest_groups.items()):
        split=[[],[]]
        for ha,hg,g in items:
            first=round(g*0.6)
            split[0].append((ha,hg,first));split[1].append((ha,hg,g-first))
        for buyer_index,parts in enumerate(split):
            buyer=f'BUY0{buyer_index+1}'
            sale=add('sales','SALE',day+timedelta(days=1),customer_id=buyer,species_id=species,
                channel='wholesale' if buyer_index==0 else 'local_live_fish',contract_number=f'SIM-SC-{len(t["sales"])+1:03}',
                order_number=f'SIM-SO-{len(t["sales"])+1:03}',currency='CNY',
                tax_status='synthetic_tax_included',freight_bearer='seller',commission_bearer='seller',
                invoice_status='synthetic_invoice_reference',invoice_on=(day+timedelta(days=2)).isoformat(),
                live_status='live',gross_revenue_cny=0.0,net_weight_kg=0.0,
                gross_weight_kg=0.0,tare_weight_kg=0.0,return_weight_kg=0.0,
                actual_trade=True,quote_observation_id=None,price_basis='synthetic_assumption_no_historical_validation')
            gross_cents=0;net_g=0
            for grade in ('A','B'):
                chosen=[x for x in parts if x[1]['grade']==grade]
                grams=sum(x[2] for x in chosen)
                if not chosen or grams <= 0:
                    continue
                unit=15.2 if species=='SP01' else 7.8
                unit+=0.6*buyer_index-(1.4 if grade=='B' else 0)
                cents=round(grams*unit/10)
                line=add('sale_items','SI',day+timedelta(days=1),sale_id=sale['id'],species_id=species,
                    grade=grade,quality_grade='synthetic_standard',net_weight_kg=grams/1000,
                    unit_price_cny_per_kg=round(unit,2),amount_cny=cents/100,discount_cny=0.0,
                    original_commercial_name='武昌鱼' if species=='SP01' else '鲢鱼',
                    species_mapping_status='scenario_identity_explicit',brand=None,
                    origin='fictional_farm_F01',geographical_indication_qualified=False,
                    grade_definition_id=f'GRADE-{species}-{grade}-V1',
                    price_basis='fictional_grade_definition_price_schedule_not_market_observation')
                gross_cents+=cents;net_g+=grams
                for ha,hg,grams_part in chosen:
                    add('harvest_sale_allocations','HSA',day+timedelta(days=1),harvest_id=ha['id'],
                        harvest_grade_item_id=hg['id'],sale_id=sale['id'],sale_item_id=line['id'],
                        pond_id=ha['pond_id'],cohort_id=ha['cohort_id'],species_id=species,grade=grade,
                         allocated_net_weight_kg=grams_part/1000,allocation_basis='synthetic_weighed_split',
                         grade_definition_id=hg['grade_definition_id'])
            sale['gross_revenue_cny']=gross_cents/100;sale['net_weight_kg']=net_g/1000
            sale['gross_weight_kg']=net_g/1000;sale['tare_weight_kg']=0.0
            deduction_cents=round(gross_cents*0.025)+round(net_g*0.04)
            net_cents=gross_cents-deduction_cents
            settle=add('settlements','SET',day+timedelta(days=2),sale_id=sale['id'],customer_id=buyer,
                gross_sales_amount_cny=gross_cents/100,deductions_amount_cny=deduction_cents/100,
                net_amount_cny=net_cents/100,received_amount_cny=net_cents/100,outstanding_amount_cny=0.0,
                actual_net_unit_price_cny_per_kg=round(net_cents/100/(net_g/1000),4),
                payment_terms_days=30,due_on=(day+timedelta(days=32)).isoformat(),
                final_received_on=(day+timedelta(days=25)).isoformat(),currency='CNY',
                status='settled',profit_basis='gross_sales_minus_cost_entries_minus_settlement_deductions_once')
            settlements.append((settle,net_cents,day,buyer))
            freight=round(net_g*0.04)
            for kind,value in [('freight',freight),('commission',deduction_cents-freight)]:
                add('settlement_deductions','DED',day+timedelta(days=2),settlement_id=settle['id'],
                    sale_id=sale['id'],deduction_type=kind,amount_cny=value/100,currency='CNY',
                    payer='seller',recognition='deduction_only_excluded_from_cost_entries',
                    cost_entry_id=None,source_document_id=f'SIM-SET-DOC-{settle["id"]}')
    # Every settlement has two receipts; the second receipt settles two invoices
    # of the same customer and harvest date (one for each species).
    grouped=defaultdict(list)
    for settle,cents,day,buyer in settlements:
        first=round(cents*0.4)
        tx=add('cash_transactions','CASH',day+timedelta(days=7),direction='receipt',counterparty_id=buyer,
            amount_cny=first/100,currency='CNY',payment_method='simulated_bank_transfer',
            bank_reference=f'SIM-REC-{settle["id"]}-1',balance_scope='business_operating_cash')
        add('cash_allocations','CALA',day+timedelta(days=7),cash_transaction_id=tx['id'],
            settlement_id=settle['id'],purchase_id=None,cost_entry_id=None,amount_cny=first/100,
            allocation_type='sale_receipt')
        grouped[(day,buyer)].append((settle,cents-first))
    for (day,buyer),group in sorted(grouped.items()):
        total=sum(n for _,n in group)
        tx=add('cash_transactions','CASH',day+timedelta(days=25),direction='receipt',counterparty_id=buyer,
            amount_cny=total/100,currency='CNY',payment_method='simulated_bank_transfer',
            bank_reference=f'SIM-REC-MULTI-{day}-{buyer}',balance_scope='business_operating_cash')
        for settle,cents in group:
            add('cash_allocations','CALA',day+timedelta(days=25),cash_transaction_id=tx['id'],
                settlement_id=settle['id'],purchase_id=None,cost_entry_id=None,amount_cny=cents/100,
                allocation_type='sale_receipt')
    # Rent paid once, monthly expense recognition; electricity recognized per month.
    rent_amount=7200000
    rent_pay=add('cash_transactions','CASH',date(year,1,3),direction='payment',counterparty_id='LAND01',
        amount_cny=rent_amount/100,currency='CNY',payment_method='simulated_bank_transfer',
        bank_reference='SIM-ANNUAL-RENT',balance_scope='business_operating_cash')
    for month in range(1,13):
        pstart=date(year,month,1)
        pend=(date(year+1,1,1) if month==12 else date(year,month+1,1))-timedelta(days=1)
        rent=cost(pend,'pond_rent',rent_amount//12,source_type='annual_rental_contract',source_id='SIM-RENT-2025',
                  period_start=pstart,period_end=pend,recognition_method='monthly_accrual_from_annual_prepayment',
                  expense_contract_start=f'{year}-01-01',expense_contract_end=f'{year}-12-31')
        add('cash_allocations','CALA',date(year,1,3),cash_transaction_id=rent_pay['id'],
            settlement_id=None,purchase_id=None,cost_entry_id=rent['id'],amount_cny=rent_amount/12/100,
            allocation_type='annual_prepayment_to_monthly_expense')
        cents=round((1200+1300*max(0,math.sin(math.pi*(month-2)/12)))*100)
        cost(pend,'electricity',cents,source_type='electricity_bill',source_id=f'SIM-ELEC-{month:02}',
             period_start=pstart,period_end=pend,recognition_method='month_service_period')
        cost(pend,'labor',450000,source_type='payroll',source_id=f'SIM-PAYROLL-{month:02}',
             period_start=pstart,period_end=pend,recognition_method='month_service_period')
    # Non-inventory service costs are independently paid and allocated, not counted twice.
    for ce in list(t['cost_entries']):
        if ce['category'] not in ('mortality_disposal','electricity','labor'):continue
        day=date.fromisoformat(ce['period_end'])
        partner=ce['supplier_id']
        tx=add('cash_transactions','CASH',day,occurred_at=ce['occurred_at'],direction='payment',counterparty_id=partner,
            amount_cny=ce['amount_cny'],currency='CNY',payment_method='simulated_bank_transfer',
            bank_reference=f'SIM-COST-PAY-{ce["id"]}',balance_scope='business_operating_cash')
        add('cash_allocations','CALA',day,occurred_at=tx['occurred_at'],cash_transaction_id=tx['id'],settlement_id=None,
            purchase_id=None,cost_entry_id=ce['id'],amount_cny=ce['amount_cny'],allocation_type='service_expense_payment')
    # Year-end book balances are not synonymous with available, unexpired stock.
    last_by_lot={}
    for move in t['inventory_movements']:
        last_by_lot[(move['product_id'],move['product_batch_id'])]=move
    purchase_lots={r['product_batch_id']:r for r in t['purchase_items']}
    opening_lots={f'LOT-{r["product_id"]}-OPEN-{year}': r for r in t['opening_balances']
                  if r['balance_type'] == 'inventory'}
    as_of=date(year,12,31)
    for (product,batch),last in sorted(last_by_lot.items()):
        pi=purchase_lots.get(batch) or opening_lots.get(batch)
        expires=pi.get('expires_on') if pi else None
        qty=last['lot_closing_quantity']
        expired=bool(expires and expires<as_of.isoformat())
        status=('depleted' if qty==0 else ('expired_pending_disposal' if expired else
                ('usable_by_date_only' if expires else 'expiry_not_collected_material')))
        add('inventory_lot_status','ILS',as_of,occurred_at=stamp(as_of,23),product_id=product,product_batch_id=batch,
            as_of=stamp(as_of,23),closing_quantity=qty,unit=last['unit'],
            closing_value_cny=last['lot_closing_value_cny'],currency='CNY',
            manufacture_on=pi.get('manufacture_on') if pi else None,expires_on=expires,
            expiry_status=pi.get('expiry_status','opening_lot_expiry_not_collected') if pi else 'opening_lot_expiry_not_collected',
            usability_status=status,available_quantity=qty if status=='usable_by_date_only' else (None if status=='expiry_not_collected_material' else 0.0),
            expiry_assessment='not_applicable_live_seed' if product in ('PR03','PR04') else f'as_of_{year}_year_end',
            disposal_status='pending_not_posted' if status=='expired_pending_disposal' else 'not_required_by_this_status',
            valuation_basis='book_value_before_pending_writeoff_not_market_or_usable_value',
            source_inventory_movement_id=last['id'])
    return t


def validate_business(tables):
    """Detailed validation of keys, chronology, quantities, cash and expense rules."""
    t=tables;checks=[]

    def result(check_id,bad,description,checked):
        checks.append({'check_id':check_id,'passed':not bad,'checked_records':checked,
                       'failure_count':len(bad),'examples':bad[:10],'description':description})

    def close(a,b,tolerance=0.011):return abs(a-b)<=tolerance
    def total(rows,field):return sum(float(r.get(field) or 0) for r in rows)
    allrows=[(name,r) for name,rows in t.items() for r in rows]
    bad=[]
    for name,rows in t.items():
        ids=[r.get('id') for r in rows]
        if len(ids)!=len(set(ids)) or None in ids:bad.append(name)
    result('primary_keys',bad,'Every table has unique non-null id.',len(t))
    keys={n:{r['id'] for r in rows} for n,rows in t.items()}
    fks={'farm_id':'farms','pond_id':'ponds','source_pond_id':'ponds','target_pond_id':'ponds',
         'cohort_id':'cohorts','source_cohort_id':'cohorts','target_cohort_id':'cohorts','parent_cohort_id':'cohorts',
         'species_id':'species','product_id':'products','supplier_id':'partners','customer_id':'partners',
         'service_partner_id':'partners','counterparty_id':'partners','purchase_id':'purchases',
         'purchase_item_id':'purchase_items','transfer_event_id':'transfer_events',
         'mortality_event_id':'mortality_events','harvest_id':'harvests','harvest_grade_item_id':'harvest_grade_items',
         'sale_id':'sales','sale_item_id':'sale_items','settlement_id':'settlements',
         'cash_transaction_id':'cash_transactions','cost_entry_id':'cost_entries'}
    bad=[];count=0
    for name,r in allrows:
        for field,target in fks.items():
            if r.get(field) is not None:
                count+=1
                if r[field] not in keys[target]:bad.append(f'{name}/{r["id"]}/{field}')
    result('business_foreign_keys',bad,'Applicable business foreign keys resolve.',count)
    bad=[]
    for name,r in allrows:
        if r.get('occurred_at'):
            stamps=[r[k] for k in ('occurred_at','recorded_at','uploaded_at','ingested_at')]
            if stamps!=sorted(stamps) or any(not s.endswith('+08:00') for s in stamps):bad.append(f'{name}/{r["id"]}')
    result('record_chronology',bad,'Occurrence <= recording <= upload <= ingestion, explicit timezone.',len(allrows))
    bad_count=[];bad_mass=[];continuity=[];previous={}
    for r in t['fish_daily_balance']:
        expected=r['opening_count']+r['stocked_count']+r['transfer_in_count']-r['transfer_out_count']-r['mortality_count']-r['harvest_count']+r['adjustment_count']
        if expected!=r['closing_count'] or r['closing_count']<0:bad_count.append(r['id'])
        mass=r['opening_biomass_kg']+r['stocked_weight_kg']+r['transfer_in_weight_kg']-r['transfer_out_weight_kg']-r['mortality_weight_kg']-r['harvest_weight_kg']+r['growth_weight_kg']+r['biomass_adjustment_kg']
        if not close(mass,r['closing_biomass_kg'],0.0011) or r['closing_biomass_kg']<0:bad_mass.append(r['id'])
        prior=previous.get(r['cohort_id'])
        if prior and (prior['closing_count']!=r['opening_count'] or not close(prior['closing_biomass_kg'],r['opening_biomass_kg'],0.0011)):continuity.append(r['id'])
        previous[r['cohort_id']]=r
    result('fish_count_conservation',bad_count,'Daily exact fish-count conservation.',len(t['fish_daily_balance']))
    result('fish_biomass_conservation',bad_mass,'Daily mass accounts separately for explicit biological growth.',len(t['fish_daily_balance']))
    result('fish_balance_continuity',continuity,'Each closing state equals next opening state.',len(t['fish_daily_balance']))
    result('fish_cycle_closed',[cid for cid,r in previous.items() if r['closing_count'] or r['closing_biomass_kg']],
           'All cohorts finish with zero fish before year end.',len(previous))
    bad=[]
    for tr in t['transfer_events']:
        alloc=[r for r in t['transfer_allocations'] if r['transfer_event_id']==tr['id']]
        if total(alloc,'count')+tr['loss_count']!=tr['transferred_out_count'] or not close(total(alloc,'weight_kg')+tr['loss_weight_kg'],tr['transferred_out_weight_kg'],0.0011):bad.append(tr['id'])
    result('transfer_conservation',bad,'Transfer allocation + explicit handling loss = transfer out.',len(t['transfer_events']))
    bad=[];transfer_index={r['id']:r for r in t['transfer_events']};harvest_index={r['id']:r for r in t['harvests']}
    for table,field,index in [('transfer_allocations','transfer_event_id',transfer_index),
                              ('disposal_events','transfer_event_id',transfer_index),
                              ('harvest_grade_items','harvest_id',harvest_index)]:
        for r in t[table]:
            if r.get(field):
                event=index.get(r[field])
                if not event or r['occurred_at']<event['occurred_at']:bad.append(f'{table}/{r["id"]}')
    result('physical_event_detail_chronology',bad,'Transfer receipts/disposal and harvest grading follow their physical events.',len(t['transfer_allocations'])+len(t['disposal_events'])+len(t['harvest_grade_items']))
    bad=[];prior={}
    for r in t['inventory_movements']:
        p=prior.get(r['product_id'])
        if not close(r['opening_quantity']+r['quantity_delta'],r['closing_quantity'],0.0011) or not close(r['opening_value_cny']+r['amount_delta_cny'],r['closing_value_cny']) or r['closing_quantity']<0 or r['closing_value_cny']<0:bad.append(r['id'])
        elif p and (not close(p['closing_quantity'],r['opening_quantity'],0.0011) or not close(p['closing_value_cny'],r['opening_value_cny'])):bad.append(r['id'])
        prior[r['product_id']]=r
    result('inventory_conservation',bad,'Inventory quantity and value conserve sequentially; no negative stock.',len(t['inventory_movements']))
    bad=[];prior={}
    for r in t['inventory_movements']:
        key=(r['product_id'],r['product_batch_id']);p=prior.get(key)
        if not close(r['lot_opening_quantity']+r['quantity_delta'],r['lot_closing_quantity'],0.0011) or not close(r['lot_opening_value_cny']+r['amount_delta_cny'],r['lot_closing_value_cny']) or r['lot_closing_quantity']<0 or r['lot_closing_value_cny']<0:bad.append(r['id'])
        elif p and (not close(p['lot_closing_quantity'],r['lot_opening_quantity'],0.0011) or not close(p['lot_closing_value_cny'],r['lot_opening_value_cny'])):bad.append(r['id'])
        prior[key]=r
    result('inventory_lot_conservation',bad,'Every product batch conserves independently without negative quantity or value.',len(t['inventory_movements']))
    bad=[]
    status_rows=t.get('inventory_lot_status',[])
    for r in status_rows:
        last=prior.get((r['product_id'],r['product_batch_id']))
        if not last or not close(last['lot_closing_quantity'],r['closing_quantity'],0.0011) or not close(last['lot_closing_value_cny'],r['closing_value_cny']):bad.append(r['id'])
        if r['usability_status']=='expired_pending_disposal' and (not r['expires_on'] or r['expires_on']>=r['as_of'][:10] or r['available_quantity']!=0):bad.append(r['id'])
    if len(status_rows)!=len(prior):bad.append('lot_status_cardinality')
    result('inventory_lot_status_reconciliation',bad,'Year-end lot book balances reconcile; expired lots are not available stock.',len(status_rows))
    issues=defaultdict(list)
    for r in t['inventory_movements']:issues[(r['source_type'],r['source_id'])].append(r)
    bad=[]
    for fe in t['feeding_events']:
        rows=issues[('feeding_event',fe['id'])]
        if not close(-total(rows,'quantity_delta'),fe['quantity_kg'],0.0011) or not close(-total(rows,'amount_delta_cny'),fe['cost_cny']):bad.append(fe['id'])
    result('feeding_inventory_links',bad,'Every feeding links to actual quantity and value inventory consumption.',len(t['feeding_events']))
    bad=[];batch_index={r['product_batch_id']:r for r in t['purchase_items']}
    for fe in t['feeding_events']:
        lot=batch_index.get(fe['product_batch_id']);day=fe['occurred_at'][:10]
        if not lot or not (fe['manufacture_on']<=day<=fe['expires_on']) or lot['manufacture_on']!=fe['manufacture_on'] or lot['expires_on']!=fe['expires_on']:bad.append(fe['id'])
    result('feed_batch_validity',bad,'Feed batch exists and feeding precedes its expiry.',len(t['feeding_events']))
    bad=[]
    for pu in t['purchases']:
        items=[r for r in t['purchase_items'] if r['purchase_id']==pu['id']]
        if not close(total(items,'amount_cny'),pu['amount_cny']) or pu['is_consumption_cost']:bad.append(pu['id'])
    result('purchase_not_consumption',bad,'Purchase detail totals match; purchase is not consumption cost.',len(t['purchases']))
    bad=[]
    for h in t['harvests']:
        grades=[r for r in t['harvest_grade_items'] if r['harvest_id']==h['id']]
        alloc=[r for r in t['harvest_sale_allocations'] if r['harvest_id']==h['id']]
        if not close(total(grades,'net_weight_kg'),h['net_weight_kg'],0.0011) or total(grades,'count')!=h['count'] or not close(total(alloc,'allocated_net_weight_kg'),h['saleable_weight_kg'],0.0011) or not close(h['gross_weight_kg']-h['tare_weight_kg'],h['net_weight_kg'],0.0011):bad.append(h['id'])
    result('harvest_sale_weight_conservation',bad,'Grades, gross/tare/net and all sale allocations reconcile exactly.',len(t['harvests']))
    bad=[];grade_index={r['id']:r for r in t['harvest_grade_items']};sale_item_index={r['id']:r for r in t['sale_items']}
    for a in t['harvest_sale_allocations']:
        hg=grade_index.get(a['harvest_grade_item_id']);si=sale_item_index.get(a['sale_item_id'])
        if not hg or not si or hg['harvest_id']!=a['harvest_id'] or si['sale_id']!=a['sale_id'] or hg['grade']!=a['grade'] or si['grade']!=a['grade'] or hg['species_id']!=a['species_id'] or si['species_id']!=a['species_id'] or hg['cohort_id']!=a['cohort_id'] or hg['pond_id']!=a['pond_id']:bad.append(a['id'])
    for hg in t['harvest_grade_items']:
        alloc=[r for r in t['harvest_sale_allocations'] if r['harvest_grade_item_id']==hg['id']]
        if not close(total(alloc,'allocated_net_weight_kg'),hg['net_weight_kg'],0.0011):bad.append(hg['id'])
    result('harvest_grade_allocation_consistency',bad,'Allocated harvest grade, species, pond, cohort and weight agree with both endpoints.',len(t['harvest_sale_allocations']))
    bad=[]
    for si in t['sale_items']:
        alloc=[r for r in t['harvest_sale_allocations'] if r['sale_item_id']==si['id']]
        if not close(total(alloc,'allocated_net_weight_kg'),si['net_weight_kg'],0.0011) or not close(si['amount_cny'],round(si['net_weight_kg']*si['unit_price_cny_per_kg'],2)):bad.append(si['id'])
    result('sale_items_conservation',bad,'Sale quantities and unit-price amounts reconcile.',len(t['sale_items']))
    bad=[]
    for sale in t['sales']:
        items=[r for r in t['sale_items'] if r['sale_id']==sale['id']]
        if not close(total(items,'amount_cny'),sale['gross_revenue_cny']) or not close(total(items,'net_weight_kg'),sale['net_weight_kg'],0.0011):bad.append(sale['id'])
    result('sale_header_conservation',bad,'Sale header matches all line amounts and weights.',len(t['sales']))
    bad=[]
    for se in t['settlements']:
        deductions=[r for r in t['settlement_deductions'] if r['settlement_id']==se['id']]
        receipts=[r for r in t['cash_allocations'] if r.get('settlement_id')==se['id']]
        if not close(total(deductions,'amount_cny'),se['deductions_amount_cny']) or not close(se['gross_sales_amount_cny']-se['deductions_amount_cny'],se['net_amount_cny']) or not close(total(receipts,'amount_cny'),se['received_amount_cny']) or not close(se['received_amount_cny']+se['outstanding_amount_cny'],se['net_amount_cny']):bad.append(se['id'])
    result('settlement_conservation',bad,'Gross minus deductions = net = receipts plus receivable.',len(t['settlements']))
    bad=[]
    for tx in t['cash_transactions']:
        alloc=[r for r in t['cash_allocations'] if r['cash_transaction_id']==tx['id']]
        if not close(total(alloc,'amount_cny'),tx['amount_cny']):bad.append(tx['id'])
    result('cash_allocation_conservation',bad,'Every receipt/payment is allocated once in full.',len(t['cash_transactions']))
    bad=[];cash_index={r['id']:r for r in t['cash_transactions']};settle_index={r['id']:r for r in t['settlements']}
    purchase_index={r['id']:r for r in t['purchases']}
    for a in t['cash_allocations']:
        tx=cash_index.get(a['cash_transaction_id'])
        if a.get('settlement_id'):
            se=settle_index.get(a['settlement_id'])
            if not se or not tx or tx['direction']!='receipt' or tx['counterparty_id']!=se['customer_id'] or tx['occurred_at']<se['occurred_at']:bad.append(a['id'])
        if a.get('purchase_id'):
            pu=purchase_index.get(a['purchase_id'])
            if not pu or not tx or tx['direction']!='payment' or tx['counterparty_id']!=pu['supplier_id']:bad.append(a['id'])
    result('cash_allocation_counterparty_chronology',bad,'Cash direction and counterparty match invoices; collection follows settlement.',len(t['cash_allocations']))
    bad=[]
    for ce in t['cost_entries']:
        alloc=[r for r in t['cost_allocations'] if r['cost_entry_id']==ce['id']]
        if not close(total(alloc,'amount_cny'),ce['amount_cny']) or not close(total(alloc,'allocation_ratio'),1,1e-9) or ce['period_start']>ce['period_end']:bad.append(ce['id'])
    result('cost_allocation_conservation',bad,'Cost allocated once by explicit period and basis; cents reconcile.',len(t['cost_entries']))
    bad=[]
    for r in t['cost_allocations']:
        ce=next((c for c in t['cost_entries'] if c['id']==r['cost_entry_id']),None)
        if ce and (ce['period_start']!=r['period_start'] or ce['period_end']!=r['period_end']):bad.append(r['id'])
    result('cost_period_alignment',bad,'Each allocation retains its originating service period.',len(t['cost_allocations']))
    by_day_cohort={(r['balance_date'],r['cohort_id']):r for r in t['fish_daily_balance']}
    bad=[]
    for h in t['harvests']:
        balance=by_day_cohort.get((h['occurred_at'][:10],h['cohort_id']))
        if not balance or balance['harvest_count']!=h['count'] or not close(balance['harvest_weight_kg'],h['net_weight_kg'],0.0011) or (h['harvest_type']=='final' and balance['closing_count']!=0):bad.append(h['id'])
    result('harvest_fish_ledger_agreement',bad,'Each harvest matches fish ledger; final harvest leaves no residual fish.',len(t['harvests']))
    result('deductions_not_double_cost',[r['id'] for r in t['cost_entries'] if r.get('settlement_deduction_id')],
           'Deductions are excluded from cost ledger; gross-based profitability subtracts once.',len(t['cost_entries']))
    bad=[]
    harvest_lookup={r['id']:r for r in t['harvests']};sale_lookup={r['id']:r for r in t['sales']}
    for a in t['harvest_sale_allocations']:
        h=harvest_lookup.get(a['harvest_id']);s=sale_lookup.get(a['sale_id'])
        if h and s and (h['occurred_at']>s['occurred_at'] or h['species_id']!=a['species_id'] or s['species_id']!=a['species_id']):bad.append(a['id'])
    result('harvest_sale_chronology_species',bad,'Sales occur after harvest and species agree throughout allocation.',len(t['harvest_sale_allocations']))
    result('no_unfounded_gi',[f'{n}/{r["id"]}' for n,r in allrows if r.get('geographical_indication_qualified') is True],
           'No geographical-indication qualification is fabricated.',len(allrows))
    return checks
