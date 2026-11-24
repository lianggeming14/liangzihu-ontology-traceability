"""Read-only L2 business validation; no baseline or answer access.

All numeric comparisons use Decimal. An unavailable operand blocks the
comparison, rather than becoming zero. Derived tables are reconciled, never
added to the business facts. The caller owns normalization and PK/FK checks.
"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import json
import unicodedata

MONEY = Decimal('0.01')
WEIGHT = Decimal('0.002')
RATIO = Decimal('0.0001')
LOCAL = timezone(timedelta(hours=8))


def _time(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).strip().replace('/', '-').replace('Z', '+00:00'))
        return (result.replace(tzinfo=LOCAL) if result.tzinfo is None else result).astimezone(LOCAL)
    except (ValueError, TypeError):
        return None


def _text(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


class _Checks:
    def __init__(self, tables, context):
        self.tables = {name.removesuffix('.csv'): rows for name, rows in tables.items()}
        self.blocked = context.get('blocked_fields', set())
        self.issues = []
        self.stats = {}
        self.indexes = {}
        self.group_cache = {}

    def rows(self, table):
        return self.tables.get(table, [])

    def value(self, row, field, empty_ok=False):
        if row is None or (row.get('_l2_row_key', ''), field) in self.blocked:
            return None
        value = row.get(field)
        if value is None or (value == '' and not empty_ok):
            return None
        return value

    def number(self, row, field):
        value = self.value(row, field)
        try:
            number = Decimal(value)
            return number if number.is_finite() else None
        except (InvalidOperation, ValueError, TypeError):
            return None

    def time(self, row, field):
        return _time(self.value(row, field))

    def index(self, table):
        if table not in self.indexes:
            grouped = defaultdict(list)
            for row in self.rows(table):
                key = self.value(row, 'id')
                if key:
                    grouped[key].append(row)
            self.indexes[table] = {key: values[0] if len(values) == 1 else None for key, values in grouped.items()}
        return self.indexes[table]

    def link(self, row, field, table):
        key = self.value(row, field)
        return self.index(table).get(key) if key else None

    def groups(self, table, fields):
        key = table, tuple(fields)
        if key not in self.group_cache:
            grouped = defaultdict(list)
            unknown = False
            for row in self.rows(table):
                if table == 'cash_allocations' and len(fields) == 1 and fields[0] in ('purchase_id', 'settlement_id', 'cost_entry_id') and self.value(row, fields[0], True) == '':
                    continue
                values = tuple(self.value(row, field) for field in fields)
                if any(value is None for value in values):
                    unknown = True
                else:
                    grouped[values].append(row)
            self.group_cache[key] = grouped, unknown
        return self.group_cache[key]

    def children(self, table, field, identifier):
        groups, unknown = self.groups(table, (field,))
        # A blocked joining key could belong to any parent; do not silently
        # omit it from sums or declare a falsely complete reconciliation.
        return None if unknown or identifier is None else groups.get((identifier,), [])

    def total(self, rows, field):
        if not rows:
            return None
        values = [self.number(row, field) for row in rows]
        return None if any(value is None for value in values) else sum(values, Decimal(0))

    def record(self, code, table, row, field, result, description, evidence=None, severity='error'):
        stat = self.stats.setdefault(code, dict(code=code, status='pass', checked_count=0,
            failed_count=0, blocked_count=0, description=description,
            details={'failed_examples': [], 'blocked_examples': []}))
        evidence = evidence or {}
        if result is None:
            stat['blocked_count'] += 1
            if len(stat['details']['blocked_examples']) < 20:
                stat['details']['blocked_examples'].append({'row_key': row.get('_l2_row_key', ''), **evidence})
            code += '_BLOCKED'
            severity = 'warning'
            message = description + '：依赖值缺失、冲突、单位不明或无法解析，未计算。'
        else:
            stat['checked_count'] += 1
            if result:
                return
            stat['failed_count'] += 1
            if len(stat['details']['failed_examples']) < 20:
                stat['details']['failed_examples'].append({'row_key': row.get('_l2_row_key', ''), **evidence})
            message = description + '：不一致，保留原事实待核。'
        self.issues.append(dict(table=table, row_key=row.get('_l2_row_key', ''),
            record_id=row.get('id', ''), field=field, code=code, severity=severity,
            action='review', message=message, evidence=evidence))

    def compare(self, code, table, row, field, actual, expected, description, tolerance=MONEY, evidence=None):
        available = actual is not None and expected is not None
        detail = {'actual': str(actual) if actual is not None else None,
                  'expected': str(expected) if expected is not None else None,
                  'tolerance': str(tolerance), **(evidence or {})}
        self.record(code, table, row, field,
            abs(actual - expected) <= tolerance if available else None, description, detail)

    def identical(self, code, table, row, field, other, other_field=None, description='关联对象属性一致'):
        a, b = self.value(row, field), self.value(other, other_field or field)
        self.record(code, table, row, field, a == b if a is not None and b is not None else None,
                    description, {'actual': a, 'expected': b, 'linked_id': other.get('id', '') if other else None})

    def equation(self, code, table, row, target, operands, function, description, tolerance=MONEY, valid=True):
        values = [self.number(row, field) for field in operands]
        expected = function(*values) if valid and all(value is not None for value in values) else None
        self.compare(code, table, row, target, self.number(row, target), expected, description, tolerance,
                     {'operand_fields': operands})

    def finish(self):
        result = []
        for stat in self.stats.values():
            stat['status'] = 'fail' if stat['failed_count'] else 'blocked' if stat['blocked_count'] else 'pass'
            result.append(stat)
        return sorted(result, key=lambda c: c['code'])


def _occupancy(c):
    groups, unknown = c.groups('pond_cohort_occupancy', ('pond_id', 'cohort_id'))
    specs = [('feeding_events', 'occurred_at', 'pond_id', 'cohort_id'),
             ('mortality_events', 'occurred_at', 'pond_id', 'cohort_id'),
             ('harvests', 'occurred_at', 'pond_id', 'cohort_id'),
             ('growth_samples', 'sampled_at', 'pond_id', 'cohort_id'),
             ('transfer_events', 'occurred_at', 'source_pond_id', 'source_cohort_id'),
             ('transfer_allocations', 'occurred_at', 'target_pond_id', 'target_cohort_id')]
    for table, time_field, pond_field, cohort_field in specs:
        for row in c.rows(table):
            key = c.value(row, pond_field), c.value(row, cohort_field)
            at = c.time(row, time_field)
            entries = groups.get(key, [])
            intervals = [(c.time(o, 'entered_at'), c.time(o, 'left_at'), o) for o in entries]
            usable = [(start, end) for start, end, o in intervals if start and (end or c.value(o, 'left_at', True) == '')]
            valid = any(start <= at and (end is None or at <= end) for start, end in usable) if at else None
            if not at or None in key or not entries or unknown or len(usable) != len(intervals):
                valid = None
            c.record('BIZ_OCCUPANCY_TIME', table, row, time_field, valid,
                     '事件必须位于该鱼群在该塘的在塘时段内（含入塘及最终出塘时刻）',
                     {'pond_id': key[0], 'cohort_id': key[1], 'event_time': c.value(row, time_field),
                      'occupancy_ids': [o.get('id') for o in entries]})
    for row in c.rows('pond_cohort_occupancy'):
        start, end = c.time(row, 'entered_at'), c.time(row, 'left_at')
        result = end >= start if start and end else True if start and c.value(row, 'left_at', True) == '' else None
        c.record('BIZ_OCCUPANCY_INTERVAL', 'pond_cohort_occupancy', row, 'left_at', result, '在塘结束不得早于开始')


def _inventory(c):
    table = 'inventory_movements'
    rows = c.rows(table)
    for row in rows:
        for suffix, opening, closing, delta, tol in [
            ('QUANTITY', 'opening_quantity', 'closing_quantity', 'quantity_delta', WEIGHT),
            ('VALUE', 'opening_value_cny', 'closing_value_cny', 'amount_delta_cny', MONEY),
            ('LOT_QUANTITY', 'lot_opening_quantity', 'lot_closing_quantity', 'quantity_delta', WEIGHT),
            ('LOT_VALUE', 'lot_opening_value_cny', 'lot_closing_value_cny', 'amount_delta_cny', MONEY)]:
            c.equation('BIZ_INVENTORY_ROLL_' + suffix, table, row, closing, [opening, delta],
                       lambda a, b: a + b, '库存期初加变动等于期末', tol,
                       valid=c.value(row, 'unit') in ('kg', 'fish', 'g', 'L', 'ml') if 'QUANTITY' in suffix else True)
        for field in ('closing_quantity', 'closing_value_cny', 'lot_closing_quantity', 'lot_closing_value_cny'):
            value = c.number(row, field)
            c.record('BIZ_INVENTORY_NONNEGATIVE', table, row, field, value >= 0 if value is not None else None, '库存结余不可为负')
        movement = c.value(row, 'movement_type')
        quantity = c.number(row, 'quantity_delta')
        if movement in ('issue', 'loss', 'receipt', 'opening', 'return'):
            sign_ok = quantity <= 0 if quantity is not None and movement in ('issue', 'loss') else quantity >= 0 if quantity is not None else None
            c.record('BIZ_INVENTORY_DIRECTION', table, row, 'quantity_delta', sign_ok, '出入库数量方向与流水类型一致')

    # Stable original order resolves same-time movements; a missing timestamp
    # blocks the entire stream, since chronological neighbors are then unknown.
    for keys, quantity_open, quantity_close, value_open, value_close, label in [
        (('product_id',), 'opening_quantity', 'closing_quantity', 'opening_value_cny', 'closing_value_cny', 'PRODUCT'),
        (('product_id', 'product_batch_id'), 'lot_opening_quantity', 'lot_closing_quantity', 'lot_opening_value_cny', 'lot_closing_value_cny', 'LOT')]:
        groups, unknown = c.groups(table, keys)
        for group in groups.values():
            missing_time = any(c.time(row, 'occurred_at') is None for row in group)
            ordered = group if missing_time else sorted(group, key=lambda row: c.time(row, 'occurred_at'))
            for previous, row in zip(ordered, ordered[1:]):
                comparable = not unknown and not missing_time and c.value(previous, 'unit') == c.value(row, 'unit') and c.value(row, 'unit') is not None
                for current_field, previous_field, suffix, tol in [(quantity_open, quantity_close, 'QUANTITY', WEIGHT), (value_open, value_close, 'VALUE', MONEY)]:
                    c.compare('BIZ_INVENTORY_CONTINUITY_' + label + '_' + suffix, table, row, current_field,
                              c.number(row, current_field), c.number(previous, previous_field) if comparable else None,
                              '相邻库存流水期初承接上一笔期末', tol, {'previous_id': previous.get('id')})

    sources = {'purchase_item': ('purchase_items', 'quantity', 'amount_cny', 1, 'unit', 'product_batch_id'),
               'opening_balance': ('opening_balances', 'quantity', 'amount_cny', 1, 'unit', None),
               'feeding_event': ('feeding_events', 'quantity_kg', 'cost_cny', -1, None, 'product_batch_id'),
               'stocking_event': ('stocking_events', 'count', 'total_cost_cny', -1, None, 'seed_batch_id'),
               'pond_preparation': ('pond_preparations', 'dose_kg', None, -1, None, None)}
    source_groups, unknown = c.groups(table, ('source_type', 'source_id'))
    for (source_type, source_id), movements in source_groups.items():
        if source_type not in sources:
            # Count sheets and unused-feed checkout/return IDs are declared
            # external documents, not nonexistent relational event records.
            continue
        source_table, quantity_field, amount_field, sign, unit_field, batch_field = sources[source_type]
        source = c.index(source_table).get(source_id)
        first = movements[0]
        expected_quantity = c.number(source, quantity_field)
        unit = c.value(source, unit_field) if unit_field else 'fish' if source_type == 'stocking_event' else 'kg'
        if source_type == 'feeding_event' and (c.value(source, 'quantity_kg_unit', True) not in ('', 'kg', None) or (source and (source.get('_l2_row_key', ''), 'quantity_kg_unit') in c.blocked)):
            expected_quantity = None
        comparable = not unknown and unit is not None and all(c.value(m, 'unit') == unit for m in movements)
        code = 'BIZ_FEED_INVENTORY_QUANTITY' if source_type == 'feeding_event' else 'BIZ_INVENTORY_SOURCE_QUANTITY'
        c.compare(code, table, first, 'quantity_delta', c.total(movements, 'quantity_delta'),
                  sign * expected_quantity if comparable and expected_quantity is not None else None,
                  '来源业务数量与对应库存流水净数量一致', WEIGHT * max(1, len(movements)),
                  {'source_table': source_table, 'source_id': source_id, 'movement_ids': [m.get('id') for m in movements]})
        if amount_field:
            amount = c.number(source, amount_field)
            c.compare('BIZ_INVENTORY_SOURCE_AMOUNT', table, first, 'amount_delta_cny', c.total(movements, 'amount_delta_cny'),
                      sign * amount if amount is not None and not unknown else None, '来源业务金额与库存流水金额一致',
                      MONEY * max(1, len(movements)), {'source_table': source_table, 'source_id': source_id})
        for movement in movements:
            product_field = 'disinfectant_product_id' if source_type == 'pond_preparation' else 'product_id'
            c.identical('BIZ_INVENTORY_SOURCE_IDENTITY', table, movement, 'product_id', source, product_field, '库存产品与来源产品一致')
            if batch_field:
                c.identical('BIZ_INVENTORY_SOURCE_IDENTITY', table, movement, 'product_batch_id', source, batch_field, '库存批次与来源批次一致')
            if source_type in ('feeding_event', 'stocking_event', 'pond_preparation'):
                c.identical('BIZ_INVENTORY_SOURCE_IDENTITY', table, movement, 'pond_id', source, description='库存领用塘与业务塘一致')
            if source_type in ('feeding_event', 'stocking_event'):
                c.identical('BIZ_INVENTORY_SOURCE_IDENTITY', table, movement, 'cohort_id', source, description='库存领用鱼群与业务鱼群一致')
    for row in c.rows('feeding_events'):
        key = c.value(row, 'id')
        movements = source_groups.get(('feeding_event', key), [])
        c.record('BIZ_FEED_INVENTORY_COVERAGE', 'feeding_events', row, 'quantity_kg',
                 bool(movements) if key and not unknown else None, '每条投喂业务应有对应库存领用流水', {'movement_count': len(movements)})
        valid_unit = c.value(row, 'quantity_kg_unit', True) in ('', 'kg', None) and (row.get('_l2_row_key', ''), 'quantity_kg_unit') not in c.blocked
        c.equation('BIZ_FEED_AMOUNT', 'feeding_events', row, 'cost_cny', ['quantity_kg', 'unit_price_cny'], lambda q, p: q * p,
                   '投喂费用等于可比数量乘单价', MONEY, valid_unit)
    for row in c.rows('inventory_lot_status'):
        source = c.link(row, 'source_inventory_movement_id', table)
        for field, other in [('closing_quantity', 'lot_closing_quantity'), ('closing_value_cny', 'lot_closing_value_cny')]:
            c.compare('BIZ_INVENTORY_LOT_SNAPSHOT', 'inventory_lot_status', row, field, c.number(row, field), c.number(source, other), '批次快照与声明的来源流水一致', MONEY if 'value' in field else WEIGHT)
        for field in ('product_id', 'product_batch_id', 'unit'):
            c.identical('BIZ_INVENTORY_LOT_IDENTITY', 'inventory_lot_status', row, field, source)


def _aggregate(c, code, parent_table, child_table, fk, parent_field, child_field, description, tolerance=MONEY):
    for parent in c.rows(parent_table):
        children = c.children(child_table, fk, c.value(parent, 'id'))
        c.compare(code, parent_table, parent, parent_field, c.number(parent, parent_field), c.total(children, child_field),
                  description, tolerance * max(1, len(children or [])), {'child_count': len(children) if children is not None else None})


def _commerce(c):
    for row in c.rows('purchase_items'):
        c.equation('BIZ_PURCHASE_LINE_AMOUNT', 'purchase_items', row, 'amount_cny', ['quantity', 'unit_price_cny'], lambda q, p: q * p,
                   '采购明细金额等于数量乘单价', MONEY, c.value(row, 'unit') in ('kg', 'fish', 'g', 'L', 'ml'))
        parent = c.link(row, 'purchase_id', 'purchases')
        c.identical('BIZ_PURCHASE_SUPPLIER', 'purchase_items', row, 'supplier_id', parent, description='采购明细供应商与表头一致')
    _aggregate(c, 'BIZ_PURCHASE_TOTAL', 'purchases', 'purchase_items', 'purchase_id', 'amount_cny', 'amount_cny', '采购表头金额等于明细合计')
    for row in c.rows('harvests'):
        c.equation('BIZ_HARVEST_NET_WEIGHT', 'harvests', row, 'net_weight_kg', ['gross_weight_kg', 'tare_weight_kg'], lambda a, b: a - b, '出塘净重等于毛重减皮重', WEIGHT)
        c.equation('BIZ_HARVEST_SALEABLE', 'harvests', row, 'saleable_weight_kg', ['net_weight_kg', 'harvest_loss_weight_kg', 'transport_loss_weight_kg', 'deduction_weight_kg'], lambda n, h, t, d: n - h - t - d, '可售重量为净重减明确损耗及扣重', WEIGHT)
    _aggregate(c, 'BIZ_HARVEST_GRADE_WEIGHT', 'harvests', 'harvest_grade_items', 'harvest_id', 'saleable_weight_kg', 'net_weight_kg', '出塘规格重量汇总等于可售重量', WEIGHT)
    _aggregate(c, 'BIZ_HARVEST_GRADE_COUNT', 'harvests', 'harvest_grade_items', 'harvest_id', 'count', 'count', '出塘规格尾数汇总与出塘尾数一致', Decimal(0))
    for row in c.rows('harvest_grade_items'):
        parent = c.link(row, 'harvest_id', 'harvests')
        for field in ('pond_id', 'cohort_id', 'species_id'):
            c.identical('BIZ_HARVEST_GRADE_IDENTITY', 'harvest_grade_items', row, field, parent)
        count, weight = c.number(row, 'count'), c.number(row, 'net_weight_kg')
        c.compare('BIZ_HARVEST_GRADE_MEAN', 'harvest_grade_items', row, 'mean_weight_g', c.number(row, 'mean_weight_g'),
                  weight * 1000 / count if count and weight is not None else None, '规格均重等于重量除尾数', WEIGHT)
        parent_weight = c.number(parent, 'saleable_weight_kg')
        c.compare('BIZ_HARVEST_GRADE_RATIO', 'harvest_grade_items', row, 'weight_ratio', c.number(row, 'weight_ratio'),
                  weight / parent_weight if parent_weight and weight is not None else None, '规格重量占比与出塘可售重量一致', RATIO)
    _aggregate(c, 'BIZ_HARVEST_SALE_WEIGHT', 'harvests', 'harvest_sale_allocations', 'harvest_id', 'saleable_weight_kg', 'allocated_net_weight_kg', '出塘可售重量与销售分配合计一致', WEIGHT)
    _aggregate(c, 'BIZ_HARVEST_GRADE_SALE_WEIGHT', 'harvest_grade_items', 'harvest_sale_allocations', 'harvest_grade_item_id', 'net_weight_kg', 'allocated_net_weight_kg', '出塘规格重量与销售分配合计一致', WEIGHT)
    _aggregate(c, 'BIZ_SALE_ITEM_ALLOCATED_WEIGHT', 'sale_items', 'harvest_sale_allocations', 'sale_item_id', 'net_weight_kg', 'allocated_net_weight_kg', '销售明细重量与出塘分配合计一致', WEIGHT)
    for row in c.rows('harvest_sale_allocations'):
        grade = c.link(row, 'harvest_grade_item_id', 'harvest_grade_items')
        item = c.link(row, 'sale_item_id', 'sale_items')
        for field in ('harvest_id', 'pond_id', 'cohort_id', 'species_id', 'grade'):
            c.identical('BIZ_HARVEST_SALE_IDENTITY', 'harvest_sale_allocations', row, field, grade)
        for field in ('sale_id', 'species_id', 'grade'):
            c.identical('BIZ_HARVEST_SALE_IDENTITY', 'harvest_sale_allocations', row, field, item)
    for row in c.rows('sale_items'):
        c.equation('BIZ_SALE_LINE_AMOUNT', 'sale_items', row, 'amount_cny', ['net_weight_kg', 'unit_price_cny_per_kg', 'discount_cny'], lambda w, p, d: w * p - d, '销售明细金额等于净重乘成交价减折价')
        c.identical('BIZ_SALE_SPECIES', 'sale_items', row, 'species_id', c.link(row, 'sale_id', 'sales'), description='销售明细物种与表头一致')
    _aggregate(c, 'BIZ_SALE_TOTAL_AMOUNT', 'sales', 'sale_items', 'sale_id', 'gross_revenue_cny', 'amount_cny', '销售表头金额等于明细金额合计')
    _aggregate(c, 'BIZ_SALE_TOTAL_WEIGHT', 'sales', 'sale_items', 'sale_id', 'net_weight_kg', 'net_weight_kg', '销售表头净重等于明细净重合计', WEIGHT)
    for row in c.rows('settlements'):
        sale = c.link(row, 'sale_id', 'sales')
        c.compare('BIZ_SETTLEMENT_GROSS', 'settlements', row, 'gross_sales_amount_cny', c.number(row, 'gross_sales_amount_cny'), c.number(sale, 'gross_revenue_cny'), '结算毛额与销售毛额一致')
        for field in ('customer_id', 'currency'):
            c.identical('BIZ_SETTLEMENT_IDENTITY', 'settlements', row, field, sale)
        c.equation('BIZ_SETTLEMENT_NET', 'settlements', row, 'net_amount_cny', ['gross_sales_amount_cny', 'deductions_amount_cny'], lambda g, d: g - d, '结算净额等于毛额减扣款')
        c.equation('BIZ_SETTLEMENT_OUTSTANDING', 'settlements', row, 'outstanding_amount_cny', ['net_amount_cny', 'received_amount_cny'], lambda n, r: n - r, '结算未收金额等于净额减已收')
        net, weight = c.number(row, 'net_amount_cny'), c.number(sale, 'net_weight_kg')
        c.compare('BIZ_SETTLEMENT_NET_PRICE', 'settlements', row, 'actual_net_unit_price_cny_per_kg', c.number(row, 'actual_net_unit_price_cny_per_kg'), net / weight if net is not None and weight else None, '结算实际净价等于净额除销售净重', RATIO)
    _aggregate(c, 'BIZ_SETTLEMENT_DEDUCTIONS', 'settlements', 'settlement_deductions', 'settlement_id', 'deductions_amount_cny', 'amount_cny', '结算扣款总额与扣款明细一致')
    for row in c.rows('settlement_deductions'):
        parent = c.link(row, 'settlement_id', 'settlements')
        for field in ('sale_id', 'currency'):
            c.identical('BIZ_DEDUCTION_IDENTITY', 'settlement_deductions', row, field, parent)
        if c.value(row, 'recognition') == 'deduction_only_excluded_from_cost_entries':
            linked_costs = [r for r in c.rows('cost_entries') if c.value(r, 'settlement_deduction_id') == c.value(row, 'id')]
            c.record('BIZ_DEDUCTION_NO_DOUBLE_COUNT', 'settlement_deductions', row, 'cost_entry_id',
                     c.value(row, 'cost_entry_id', True) == '' and not linked_costs,
                     '明确仅作结算扣款的项目不得再作为利润成本重复扣减', {'linked_cost_ids': [r.get('id') for r in linked_costs]})


def _cash_cost(c):
    mapping = {'purchase_payment': ('purchase_id', 'purchases', 'supplier_id', 'payment'),
               'sale_receipt': ('settlement_id', 'settlements', 'customer_id', 'receipt'),
               'service_expense_payment': ('cost_entry_id', 'cost_entries', 'supplier_id', 'payment'),
               'annual_prepayment_to_monthly_expense': ('cost_entry_id', 'cost_entries', 'supplier_id', 'payment')}
    for row in c.rows('cash_allocations'):
        kind = c.value(row, 'allocation_type')
        cash = c.link(row, 'cash_transaction_id', 'cash_transactions')
        if kind not in mapping:
            c.record('BIZ_CASH_TARGET', 'cash_allocations', row, 'allocation_type', None, '收付款分配需有明确核销对象类型')
            continue
        target_field, target_table, counterparty_field, direction = mapping[kind]
        keys = [c.value(row, field, True) for field in ('purchase_id', 'settlement_id', 'cost_entry_id')]
        valid_keys = None if None in keys else sum(bool(key) for key in keys) == 1 and bool(c.value(row, target_field))
        c.record('BIZ_CASH_TARGET', 'cash_allocations', row, target_field, valid_keys, '收付款分配必须且仅能选择一个与类型一致的对象')
        target = c.link(row, target_field, target_table)
        actual_direction = c.value(cash, 'direction')
        c.record('BIZ_CASH_DIRECTION', 'cash_allocations', row, 'cash_transaction_id', actual_direction == direction if actual_direction else None, '核销方向与收付款方向一致', {'actual': actual_direction, 'expected': direction})
        actual, expected = c.value(cash, 'counterparty_id'), c.value(target, counterparty_field)
        # Payroll has no supplier in this schema. Absence limits matching;
        # it does not invent a supplier nor declare the payment erroneous.
        c.record('BIZ_CASH_COUNTERPARTY', 'cash_allocations', row, target_field, actual == expected if actual and expected else None,
                 '收付款往来对象与核销对象一致', {'actual': actual, 'expected': expected})
        if cash and target:
            c.identical('BIZ_CASH_CURRENCY', 'cash_allocations', row, 'currency', target) if 'currency' in row else c.record(
                'BIZ_CASH_CURRENCY', 'cash_allocations', row, target_field,
                c.value(cash, 'currency') == c.value(target, 'currency') if c.value(cash, 'currency') and c.value(target, 'currency') else None,
                '收付款币种与核销对象币种一致')
        amount = c.number(row, 'amount_cny')
        c.record('BIZ_CASH_ALLOCATION_POSITIVE', 'cash_allocations', row, 'amount_cny', amount >= 0 if amount is not None else None, '核销金额不得为负')
    _aggregate(c, 'BIZ_CASH_TOTAL', 'cash_transactions', 'cash_allocations', 'cash_transaction_id', 'amount_cny', 'amount_cny', '每笔收付款金额与核销分配总额一致')
    _aggregate(c, 'BIZ_SETTLEMENT_CASH_RECEIVED', 'settlements', 'cash_allocations', 'settlement_id', 'received_amount_cny', 'amount_cny', '结算已收金额与收款分配合计一致')
    # Optional polymorphic keys are blank by design: collect each target kind
    # separately instead of treating the other blank keys as missing data.
    for table, fk, expected_field in [('purchases', 'purchase_id', 'amount_cny'), ('cost_entries', 'cost_entry_id', 'amount_cny')]:
        by_target = defaultdict(list)
        for row in c.rows('cash_allocations'):
            key = c.value(row, fk)
            if key:
                by_target[key].append(row)
        for parent in c.rows(table):
            allocations = by_target.get(c.value(parent, 'id'), [])
            if not allocations:
                continue  # Costs accrued from stock are not paid again.
            total, due = c.total(allocations, 'amount_cny'), c.number(parent, expected_field)
            c.record('BIZ_CASH_TARGET_LIMIT', table, parent, expected_field,
                     total <= due + MONEY * len(allocations) if total is not None and due is not None else None,
                     '对象核销合计不得超出应付金额', {'allocated': str(total), 'due': str(due)})
    _aggregate(c, 'BIZ_COST_ALLOCATION_AMOUNT', 'cost_entries', 'cost_allocations', 'cost_entry_id', 'amount_cny', 'amount_cny', '费用分摊合计等于费用原额')
    for parent in c.rows('cost_entries'):
        children = c.children('cost_allocations', 'cost_entry_id', c.value(parent, 'id'))
        c.compare('BIZ_COST_ALLOCATION_RATIO', 'cost_entries', parent, 'amount_cny', c.total(children, 'allocation_ratio'), Decimal(1), '每笔费用分摊比例合计等于1', RATIO * max(1, len(children or [])))
    for row in c.rows('cost_allocations'):
        parent = c.link(row, 'cost_entry_id', 'cost_entries')
        amount, ratio = c.number(parent, 'amount_cny'), c.number(row, 'allocation_ratio')
        # Where available, explicit allocation bases avoid multiplying a
        # rounded ratio. The money tolerance remains one cent per line;
        # scaling a generic ratio tolerance by a large cost hides real errors.
        siblings = c.children('cost_allocations', 'cost_entry_id', c.value(row, 'cost_entry_id'))
        basis, basis_total = c.number(row, 'allocation_basis'), c.total(siblings, 'allocation_basis')
        precise_ratio = basis / basis_total if basis is not None and basis_total else ratio
        tolerance = MONEY * max(1, len(siblings or []))
        c.compare('BIZ_COST_ALLOCATION_LINE', 'cost_allocations', row, 'amount_cny', c.number(row, 'amount_cny'),
                  amount * precise_ratio if amount is not None and precise_ratio is not None else None,
                  '分摊金额与成本乘明确分摊基数占比一致；无基数时仅核对所列比例', tolerance)
        if basis is not None and basis_total:
            c.compare('BIZ_COST_ALLOCATION_BASIS_RATIO', 'cost_allocations', row, 'allocation_ratio', ratio, precise_ratio,
                      '分摊比例与明确分摊基数占比一致', RATIO)
        for field in ('currency', 'allocation_method', 'period_start', 'period_end'):
            c.identical('BIZ_COST_ALLOCATION_CONTEXT', 'cost_allocations', row, field, parent)
        if c.value(row, 'beneficiary_type') == 'cohort':
            cohort = c.link(row, 'cohort_id', 'cohorts')
            c.identical('BIZ_COST_ALLOCATION_BENEFICIARY', 'cost_allocations', row, 'pond_id', cohort)
    for row in c.rows('cost_entries'):
        if c.value(row, 'source_type') == 'feeding_event':
            feed = c.link(row, 'source_id', 'feeding_events')
            c.compare('BIZ_FEED_COST_RECOGNITION', 'cost_entries', row, 'amount_cny', c.number(row, 'amount_cny'), c.number(feed, 'cost_cny'), '投喂成本与费用确认金额一致')


def _transfers(c):
    for row in c.rows('transfer_events'):
        for suffix, tolerance in [('count', Decimal(0)), ('weight_kg', WEIGHT)]:
            c.equation('BIZ_TRANSFER_' + suffix.upper(), 'transfer_events', row, 'transferred_out_' + suffix,
                       ['received_' + suffix, 'loss_' + suffix], lambda a, b: a + b,
                       '转出数量等于收到数量加明确损耗', tolerance)
    _aggregate(c, 'BIZ_TRANSFER_ALLOCATION_COUNT', 'transfer_events', 'transfer_allocations', 'transfer_event_id', 'received_count', 'count', '转塘分配尾数合计等于实际接收尾数', Decimal(0))
    _aggregate(c, 'BIZ_TRANSFER_ALLOCATION_WEIGHT', 'transfer_events', 'transfer_allocations', 'transfer_event_id', 'received_weight_kg', 'weight_kg', '转塘分配重量合计等于实际接收重量', WEIGHT)
    for row in c.rows('transfer_allocations'):
        source = c.link(row, 'transfer_event_id', 'transfer_events')
        for field in ('source_pond_id', 'source_cohort_id'):
            c.identical('BIZ_TRANSFER_SOURCE', 'transfer_allocations', row, field, source)


def _fish_daily(c):
    """Audit supplied derived balances without using them to repair events."""
    table = 'fish_daily_balance'
    for row in c.rows(table):
        c.equation('BIZ_FISH_ROLL_COUNT', table, row, 'closing_count',
                   ['opening_count', 'stocked_count', 'transfer_in_count', 'transfer_out_count', 'mortality_count', 'harvest_count', 'adjustment_count'],
                   lambda opening, stocked, incoming, outgoing, dead, harvest, adjustment: opening + stocked + incoming - outgoing - dead - harvest + adjustment,
                   '派生日账尾数内部守恒（仅审计，不回填源事件）', Decimal(0))
        c.equation('BIZ_FISH_ROLL_BIOMASS', table, row, 'closing_biomass_kg',
                   ['opening_biomass_kg', 'stocked_weight_kg', 'transfer_in_weight_kg', 'transfer_out_weight_kg', 'mortality_weight_kg', 'harvest_weight_kg', 'growth_weight_kg', 'biomass_adjustment_kg'],
                   lambda opening, stocked, incoming, outgoing, dead, harvest, growth, adjustment: opening + stocked + incoming - outgoing - dead - harvest + growth + adjustment,
                   '派生日账生物量内部守恒（增长为所列假设，不验证真实性）', Decimal('0.005'))
        for field in ('opening_count', 'closing_count', 'opening_biomass_kg', 'closing_biomass_kg'):
            value = c.number(row, field)
            c.record('BIZ_FISH_NONNEGATIVE', table, row, field, value >= 0 if value is not None else None, '派生日账鱼量和生物量不得为负')
        count, biomass = c.number(row, 'closing_count'), c.number(row, 'closing_biomass_kg')
        mean = c.number(row, 'closing_mean_weight_g')
        if count == 0 and biomass == 0:
            c.record('BIZ_FISH_MEAN_WEIGHT', table, row, 'closing_mean_weight_g', mean in (None, Decimal(0)), '无存鱼时均重应为空或明确为零')
        else:
            c.compare('BIZ_FISH_MEAN_WEIGHT', table, row, 'closing_mean_weight_g', mean,
                      biomass * 1000 / count if count and biomass is not None else None, '派生日账期末均重与生物量及尾数一致', WEIGHT)
    groups, unknown = c.groups(table, ('pond_id', 'cohort_id'))
    for group in groups.values():
        dates = [c.time(row, 'balance_date') for row in group]
        missing_date = any(date is None for date in dates)
        ordered = group if missing_date else sorted(group, key=lambda row: c.time(row, 'balance_date'))
        for previous, row in zip(ordered, ordered[1:]):
            before, current = c.time(previous, 'balance_date'), c.time(row, 'balance_date')
            gap = (current.date() - before.date()).days if current and before else None
            c.record('BIZ_FISH_DATE_CONTINUITY', table, row, 'balance_date', gap == 1 if gap is not None and not unknown else None,
                     '同塘同鱼群派生日账日期逐日连续且无重叠', {'previous_id': previous.get('id'), 'day_gap': gap})
            for current_field, previous_field, code, tolerance in [('opening_count', 'closing_count', 'BIZ_FISH_CONTINUITY_COUNT', Decimal(0)),
                    ('opening_biomass_kg', 'closing_biomass_kg', 'BIZ_FISH_CONTINUITY_BIOMASS', WEIGHT)]:
                c.compare(code, table, row, current_field, c.number(row, current_field),
                          c.number(previous, previous_field) if gap == 1 and not missing_date and not unknown else None,
                          '相邻自然日派生日账期初承接前一期末', tolerance, {'previous_id': previous.get('id')})


def _source_issues(raw_root, schema):
    """Independent read of an explicit raw allow-list; exact duplicates only.

    No schema path is followed. This function never opens reference/generator.
    Identifiers are only NFKC/trim normalized; ambiguous PKs are excluded from
    counts and reported as unresolved, not resolved using a hidden truth set.
    """
    if not raw_root:
        return []
    root = Path(raw_root).resolve()
    if any(part.lower() in ('reference', 'generator', 'answers', 'baseline') for part in root.parts):
        raise ValueError('Source diagnostics require raw inputs, never reference material')
    names = ('pond_cohort_occupancy', 'feeding_events', 'growth_samples', 'harvest_grade_items', 'dictionaries')
    data, conflicts = {}, {}
    for name in names:
        path = root / (name + '.csv')
        if not path.is_file():
            data[name], conflicts[name] = [], []
            continue
        with path.open(encoding='utf-8-sig', newline='') as handle:
            unique = {}
            by_id = defaultdict(list)
            for row in csv.DictReader(handle):
                signature = tuple(row.items())
                if signature not in unique:
                    unique[signature] = row
                    normalized = {key: _text(value) for key, value in row.items()}
                    by_id[normalized.get('id', '')].append(normalized)
        conflicts[name] = sorted(key for key, rows in by_id.items() if len(rows) > 1 or not key)
        data[name] = [rows[0] for key, rows in by_id.items() if key and len(rows) == 1]
    occupancies = defaultdict(list)
    unresolved_occupancies = []
    for row in data['pond_cohort_occupancy']:
        start, end = _time(row.get('entered_at')), _time(row.get('left_at'))
        if not start or (row.get('left_at') and not end) or (end and end < start):
            unresolved_occupancies.append(row.get('id'))
        else:
            occupancies[(row.get('pond_id'), row.get('cohort_id'))].append((start, end, row))
    bad_feed, unresolved_feed, examined = [], [], 0
    for row in data['feeding_events']:
        at = _time(row.get('occurred_at'))
        intervals = occupancies.get((row.get('pond_id'), row.get('cohort_id')), [])
        if not at or not intervals:
            unresolved_feed.append(row.get('id'))
        else:
            examined += 1
            if not any(start <= at and (end is None or at <= end) for start, end, _ in intervals):
                bad_feed.append(row.get('id'))
    outputs = [dict(code='SOURCE_FEEDING_TIME', title='源端投喂在塘时序待修', affected_table='feeding_events',
        affected_record_ids=sorted(bad_feed), description=json.dumps({'独立原始可检查投喂数': examined, '在塘时段外投喂数': len(bad_feed),
        '不可判断投喂数': len(unresolved_feed), '不可判断投喂ID': unresolved_feed, '冲突主键': conflicts['feeding_events'],
        '口径': '完整原始行去重后，以原始占塘时段验证；不借助日余额或基准改写时间'}, ensure_ascii=False),
        required_source_fix='源端依入塘、转入及离塘时刻安排投喂，核对原始时间并同步库存、成本和环境关联；不得在L2移动事件时间。')]
    actual = set()
    sample_role = defaultdict(int)
    unresolved_samples = []
    for row in data['growth_samples']:
        at = _time(row.get('sampled_at'))
        intervals = occupancies.get((row.get('pond_id'), row.get('cohort_id')), [])
        matching = [(start, end, occ) for start, end, occ in intervals if at and start <= at and (end is None or at <= end)]
        if not at or not matching:
            unresolved_samples.append(row.get('id'))
            continue
        actual.add((row.get('pond_id'), row.get('cohort_id'), at.strftime('%Y-%m')))
        sample_role[matching[0][2].get('role', 'unknown')] += 1
    expected, source_ids, open_intervals = set(), set(), []
    for (pond, cohort), intervals in occupancies.items():
        for start, end, row in intervals:
            if row.get('role') != 'main':
                continue
            if end is None:
                open_intervals.append(row.get('id'))
                continue  # No invented reporting cutoff for unclosed periods.
            year, month = start.year, start.month
            while (year, month) <= (end.year, end.month):
                expected.add((pond, cohort, f'{year:04}-{month:02}'))
                if (pond, cohort, f'{year:04}-{month:02}') not in actual:
                    source_ids.add(row.get('id'))
                month += 1
                if month == 13:
                    year, month = year + 1, 1
    missing = sorted('/'.join(parts) for parts in expected - actual)
    outputs.append(dict(code='SOURCE_MAIN_SAMPLING_GAP', title='源端主养鱼群月度采样覆盖缺口', affected_table='pond_cohort_occupancy',
        affected_record_ids=sorted(source_ids), description=json.dumps({'预期主养塘鱼群月份数': len(expected),
        '已覆盖主养塘鱼群月份数': len(expected & actual), '缺口数': len(missing), '缺口塘鱼群月份': missing,
        '有效采样按在塘角色计数': dict(sample_role), '不可判断采样ID': unresolved_samples, '开放占塘区间未外推': open_intervals,
        '无效占塘ID': unresolved_occupancies, '冲突主键': {name: conflicts[name] for name in ('growth_samples', 'pond_cohort_occupancy')},
        '口径': '每个已闭合主养占塘区间所触及的自然月（含部分月）应有该塘该鱼群有效采样；这是审阅建议覆盖口径，非伪造采样计划'}, ensure_ascii=False),
        required_source_fix='源端明确塘口×主养鱼群×月份采样计划及部分月份规则，分别覆盖多个主养鱼群；补采或声明未采原因，保留原有套养鱼采样。'))
    # Current dictionaries only declare codes/labels, not a species-specific,
    # versioned, unit-bearing interval and sampling/market grade mapping.
    definitions = {r.get('code'): r for r in data['dictionaries'] if r.get('domain') == 'grade'}
    required = ('species_id', 'lower_bound', 'upper_bound', 'unit', 'boundary_rule', 'version')
    missing_codes = sorted({r.get('grade') for r in data['harvest_grade_items'] if r.get('grade') in ('A', 'B')
                            and not all(definitions.get(r.get('grade'), {}).get(field) for field in required)})
    affected = sorted(r['id'] for r in data['harvest_grade_items'] if r.get('grade') in missing_codes)
    pairs = sorted({(r.get('species_id', ''), r.get('grade', '')) for r in data['harvest_grade_items'] if r.get('grade') in missing_codes})
    outputs.append(dict(code='SOURCE_GRADE_DEFINITION_GAP', title='源端A/B规格区间及分级映射定义缺口', affected_table='harvest_grade_items',
        affected_record_ids=affected, description=json.dumps({'缺少充分定义的等级': missing_codes, '涉及物种等级组合': pairs,
        '受影响规格明细数': len(affected), '所需定义字段': required, '现有字典定义': {key: definitions.get(key) for key in missing_codes},
        '口径': 'A/B标签不能单独证明体重范围；均重相近不自动认定单条分级事实错误；数量金额守恒不证明规格语义有效'}, ensure_ascii=False),
        required_source_fix='提供按物种区分、具有上下界/单位/边界包含规则/版本的规格字典，保存可核验分级过程，并建立采样规格—出塘等级—行情规格映射。'))
    return outputs


def run_checks(tables, schema, context):
    """Return issue rows, aggregate check rows, and three source diagnostics."""
    c = _Checks(tables, context)
    _occupancy(c)
    _inventory(c)
    _commerce(c)
    _cash_cost(c)
    _transfers(c)
    _fish_daily(c)
    return c.issues, c.finish(), _source_issues(context.get('raw_root'), schema)
