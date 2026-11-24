"""Behavioral checks for the revised, independently generated business source."""
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import importlib.util
import unittest


MODULE_PATH = Path(__file__).with_name('business_source.py')
spec = importlib.util.spec_from_file_location('business_source', MODULE_PATH)
business = importlib.util.module_from_spec(spec)
spec.loader.exec_module(business)


class BusinessSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = business.generate({'year': 2025, 'mode': 'full', 'seed': 20251031})

    def test_feeding_and_inventory_issue_remain_inside_occupied_interval(self):
        occupancy = {(r['pond_id'], r['cohort_id']): r
                     for r in self.tables['pond_cohort_occupancy']}
        feeds = {r['id']: r for r in self.tables['feeding_events']}
        for feed in feeds.values():
            interval = occupancy[(feed['pond_id'], feed['cohort_id'])]
            self.assertLess(interval['entered_at'], feed['occurred_at'], feed['id'])
            self.assertLess(feed['occurred_at'], interval['left_at'], feed['id'])
        for movement in self.tables['inventory_movements']:
            if movement['source_type'] == 'feeding_event':
                feed = feeds[movement['source_id']]
                self.assertEqual(feed['occurred_at'], movement['occurred_at'])
                self.assertAlmostEqual(feed['quantity_kg'], -movement['quantity_delta'], places=3)

    def test_cost_and_allocations_follow_source_time_and_cash_follows_service(self):
        sources = {r['id']: r for table in ('feeding_events', 'stocking_events',
                   'transfer_events', 'mortality_events') for r in self.tables[table]}
        costs = {r['id']: r for r in self.tables['cost_entries']}
        for cost in costs.values():
            source = sources.get(cost.get('source_id'))
            if source:
                self.assertGreaterEqual(cost['occurred_at'], source['occurred_at'], cost['id'])
            if cost['source_type'] == 'feeding_event':
                self.assertEqual(cost['occurred_at'], source['occurred_at'])
        for allocation in self.tables['cost_allocations']:
            self.assertEqual(costs[allocation['cost_entry_id']]['occurred_at'], allocation['occurred_at'])
        cash = {r['id']: r for r in self.tables['cash_transactions']}
        for allocation in self.tables['cash_allocations']:
            if allocation['allocation_type'] == 'service_expense_payment':
                cost = costs[allocation['cost_entry_id']]
                transaction = cash[allocation['cash_transaction_id']]
                self.assertGreaterEqual(transaction['occurred_at'], cost['occurred_at'])
                self.assertEqual(transaction['occurred_at'], allocation['occurred_at'])

    def test_harvest_grades_are_aggregated_from_integer_gram_individuals(self):
        self.assertIn('harvest_grade_individuals', self.tables.keys())
        individuals = self.tables.get('harvest_grade_individuals', [])
        self.assertTrue(individuals, 'Actual simulated individual harvest records are required')
        by_harvest = defaultdict(list)
        by_grade = defaultdict(list)
        grades = {r['id']: r for r in self.tables['harvest_grade_items']}
        for individual in individuals:
            weight = individual['weight_g']
            self.assertIsInstance(weight, int)
            self.assertGreater(weight, 0)
            self.assertEqual(individual['grade'], 'A' if weight >= 500 else 'B')
            self.assertEqual(individual['grade_definition_id'],
                             f"GRADE-{individual['species_id']}-{individual['grade']}-V1")
            group = grades[individual['harvest_grade_item_id']]
            for field in ('harvest_id', 'pond_id', 'cohort_id', 'species_id', 'grade', 'grade_definition_id'):
                self.assertEqual(individual[field], group[field])
            by_harvest[individual['harvest_id']].append(individual)
            by_grade[group['id']].append(weight)
        for harvest in self.tables['harvests']:
            rows = by_harvest[harvest['id']]
            self.assertEqual(len(rows), harvest['count'])
            self.assertEqual(sum(r['weight_g'] for r in rows), round(harvest['net_weight_kg'] * 1000))
            self.assertEqual(len({r['individual_number'] for r in rows}), harvest['count'])
        for grade in grades.values():
            weights = by_grade[grade['id']]
            self.assertGreater(len(weights), 0)
            self.assertEqual(len(weights), grade['count'])
            self.assertEqual(sum(weights), round(grade['net_weight_kg'] * 1000))
            self.assertEqual(min(weights), grade['min_weight_g'])
            self.assertEqual(max(weights), grade['max_weight_g'])
        for item in self.tables['sale_items']:
            self.assertGreater(item['net_weight_kg'], 0)
            self.assertGreater(item['amount_cny'], 0)
            self.assertEqual(item['grade_definition_id'], f"GRADE-{item['species_id']}-{item['grade']}-V1")

    def test_pr02_opening_lot_expiry_is_explicit_and_unavailable_at_year_end(self):
        product = next(r for r in self.tables['products'] if r['id'] == 'PR02')
        status = next(r for r in self.tables['inventory_lot_status'] if r['product_id'] == 'PR02')
        self.assertEqual(product['shelf_life_days'], 365)
        self.assertEqual(status['manufacture_on'], '2024-12-01')
        self.assertEqual(status['expires_on'], '2025-12-01')
        self.assertEqual(status['usability_status'], 'expired_pending_disposal')
        self.assertEqual(status['available_quantity'], 0.0)
        self.assertEqual(status['closing_quantity'], 305.0)
        self.assertIn('fictional', status['expiry_status'])

    def test_every_sale_price_resolves_to_its_species_grade_and_buyer_rule(self):
        prices = {('SP01', 'A', 'BUY01'): 15.2, ('SP01', 'A', 'BUY02'): 15.8,
                  ('SP01', 'B', 'BUY01'): 13.8, ('SP01', 'B', 'BUY02'): 14.4,
                  ('SP02', 'A', 'BUY01'): 7.8, ('SP02', 'A', 'BUY02'): 8.4,
                  ('SP02', 'B', 'BUY01'): 6.4, ('SP02', 'B', 'BUY02'): 7.0}
        sales = {r['id']: r for r in self.tables['sales']}
        for item in self.tables['sale_items']:
            customer = sales[item['sale_id']]['customer_id']
            self.assertEqual(prices[(item['species_id'], item['grade'], customer)],
                             item['unit_price_cny_per_kg'])

    def test_full_feeding_sessions_conserve_each_simulated_daily_feed_total(self):
        actual = defaultdict(int)
        for feed in self.tables['feeding_events']:
            actual[(feed['occurred_at'][:10], feed['cohort_id'])] += round(feed['quantity_kg'] * 1000)
        for balance in self.tables['fish_daily_balance']:
            self.assertEqual(actual[(balance['balance_date'], balance['cohort_id'])],
                             round(balance['feed_quantity_kg'] * 1000))

    def test_payroll_has_fictional_payment_partner_without_changing_monthly_amount(self):
        partners = {r['id']: r for r in self.tables['partners']}
        costs = {r['id']: r for r in self.tables['cost_entries'] if r['category'] == 'labor'}
        self.assertEqual(len(costs), 12)
        for cost in costs.values():
            self.assertTrue(cost['supplier_id'], 'Synthetic payroll must identify its collection partner')
            self.assertEqual(partners[cost['supplier_id']]['identity_status'], 'fictional')
            self.assertEqual(cost['amount_cny'], 4500.0)
        cash = {r['id']: r for r in self.tables['cash_transactions']}
        for allocation in self.tables['cash_allocations']:
            if allocation.get('cost_entry_id') in costs:
                cost = costs[allocation['cost_entry_id']]
                self.assertEqual(cash[allocation['cash_transaction_id']]['counterparty_id'], cost['supplier_id'])

    def test_sampling_mode_grade_distribution_is_repeatable_and_conserves_biology(self):
        cfg = {'year': 2025, 'mode': 'sample', 'seed': 71}
        first, second = business.generate(cfg), business.generate(cfg)
        self.assertEqual(first, second)
        changed_seed = business.generate({**cfg, 'seed': 72})
        self.assertEqual(first['fish_daily_balance'], changed_seed['fish_daily_balance'])
        self.assertEqual(first['harvests'], changed_seed['harvests'])
        self.assertIn('harvest_grade_individuals', first.keys())
        self.assertNotEqual(first.get('harvest_grade_individuals'), changed_seed.get('harvest_grade_individuals'))

    def test_existing_business_conservation_checks_still_pass(self):
        failures = [r for r in business.validate_business(self.tables) if not r['passed']]
        self.assertEqual(failures, [])

    def test_event_metadata_tracks_every_rescheduled_occurrence(self):
        for table, rows in self.tables.items():
            for row in rows:
                if 'occurred_at' not in row:
                    continue
                occurred = datetime.fromisoformat(row['occurred_at'])
                self.assertEqual(datetime.fromisoformat(row['recorded_at']), occurred + timedelta(minutes=12))
                self.assertEqual(datetime.fromisoformat(row['uploaded_at']), occurred + timedelta(minutes=35))
                self.assertEqual(datetime.fromisoformat(row['ingested_at']), occurred + timedelta(minutes=40))


if __name__ == '__main__':
    unittest.main()
