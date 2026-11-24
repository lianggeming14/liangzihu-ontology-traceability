"""Regression checks for occupancy-complete, temporally valid source sampling."""
import importlib.util
import math
from pathlib import Path
import statistics
import sys
import unittest
from collections import defaultdict
from datetime import datetime

HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(OUTPUT / 'generator'))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


environment = load_module('environment_source', HERE / 'environment_source.py')
business_path = HERE / 'business_source.py'
business = load_module('business_source' if business_path.exists() else 'business',
                       business_path if business_path.exists() else OUTPUT / 'generator' / 'business.py')


class EnvironmentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = {'seed': 20251031, 'year': 2025, 'mode': 'full',
                   'weather_path': str(OUTPUT / 'public_sources' / 'era5_2025.json')}
        cls.business = business.generate(cls.cfg)
        cls.tables = environment.generate(cls.cfg, cls.business)

    def test_all_78_main_cohort_months_have_individual_samples_and_stable_ids(self):
        expected = {(f'P{p:02}', f'C{p * 2 - 1:02}', f'2025-{m:02}')
                    for p in range(1, 7) for m in range(1, 12)}
        expected.update({('P02', 'C13', f'2025-{m:02}') for m in range(6, 12)})
        expected.update({('P03', 'C14', f'2025-{m:02}') for m in range(6, 12)})
        samples = self.tables['growth_samples']
        self.assertEqual(len(samples), 78)
        self.assertEqual({(r['pond_id'], r['cohort_id'], r['sampled_at'][:7]) for r in samples}, expected)
        self.assertEqual(len({r['id'] for r in samples}), 78)
        for row in samples:
            month = int(row['sampled_at'][5:7])
            suffix = '_' + row['cohort_id'] if row['cohort_id'] in {'C13', 'C14'} else ''
            self.assertEqual(row['id'], f"GR{int(row['pond_id'][1:])}_{month}{suffix}")
        self.assertEqual(len(self.tables['growth_individuals']), 2340)

    def test_sampling_time_and_ledger_basis_are_inside_the_named_occupancy(self):
        occupancy = {r['id']: r for r in self.business['pond_cohort_occupancy']}
        balances = {r['id']: r for r in self.business['fish_daily_balance']}
        for row in self.tables['growth_samples']:
            stay = occupancy[row['occupancy_id']]
            sampled = datetime.fromisoformat(row['sampled_at'])
            self.assertEqual((stay['pond_id'], stay['cohort_id']), (row['pond_id'], row['cohort_id']))
            self.assertLessEqual(datetime.fromisoformat(stay['entered_at']), sampled)
            self.assertLess(sampled, datetime.fromisoformat(stay['left_at']))
            basis = balances[row['ledger_balance_id']]
            self.assertEqual(basis['closing_count'], row['ledger_count'])
            self.assertEqual(basis['closing_biomass_kg'], row['ledger_biomass_kg'])
            self.assertLessEqual(datetime.fromisoformat(row['ledger_basis_at']), sampled)
            self.assertEqual(row['estimated_count'], round(row['ledger_count'] * 1.02))
            self.assertEqual(row['estimated_biomass_kg'], round(row['ledger_biomass_kg'] * 1.02, 3))

    def test_statistics_grades_and_saleable_biomass_derive_from_the_same_30_fish(self):
        individuals = defaultdict(list)
        grades = defaultdict(list)
        for row in self.tables['growth_individuals']:
            individuals[row['sample_id']].append(row)
        for row in self.tables['growth_grade_items']:
            grades[row['sample_id']].append(row)
        for sample in self.tables['growth_samples']:
            fish = individuals[sample['id']]
            weights = [r['weight_g'] for r in fish]
            passed = [v for v in weights if v >= 500]
            self.assertEqual(len(weights), 30)
            self.assertEqual(sample['mean_weight_g'], round(statistics.mean(weights), 3))
            self.assertEqual(sample['std_weight_g'], round(statistics.stdev(weights), 3))
            self.assertEqual(sample['min_weight_g'], min(weights))
            self.assertEqual(sample['max_weight_g'], max(weights))
            self.assertEqual(sample['grade_pass_rate'], len(passed) / 30)
            self.assertAlmostEqual(sample['saleable_weight_ratio'], sum(passed) / sum(weights))
            self.assertEqual(sample['estimated_saleable_kg'],
                             round(sample['estimated_biomass_kg'] * sum(passed) / sum(weights), 3))
            self.assertEqual(sample['uniformity_cv'], round(statistics.stdev(weights) / statistics.mean(weights), 4))
            self.assertTrue(all(r['species_id'] == sample['species_id'] for r in fish))
            self.assertEqual(sum(r['count'] for r in grades[sample['id']]), 30)
            for grade in grades[sample['id']]:
                code = 'A' if grade['grade'] == 'at_least_500g' else 'B'
                subset = passed if code == 'A' else [v for v in weights if v < 500]
                self.assertEqual(grade['commercial_grade'], code)
                self.assertEqual(grade['grade_definition_id'], f"GRADE-{sample['species_id']}-{code}-V1")
                self.assertEqual(grade['count'], len(subset))
                self.assertEqual(grade['proportion'], len(subset) / 30)
                self.assertAlmostEqual(grade['sample_weight_kg'], sum(subset) / 1000)

    def test_unresolved_bream_quote_is_excluded_and_other_identities_remain(self):
        quotes = self.tables['price_observations']
        self.assertEqual(len(quotes), 4380)
        self.assertEqual({r['original_product_name'] for r in quotes}, {'武昌鱼', '鲢', '豆粕'})
        for quote in quotes:
            if quote['original_product_name'] == '武昌鱼':
                self.assertEqual(quote['species_id'], 'SP01')
                self.assertEqual(quote['grade'], '500-750g')
                self.assertEqual(quote['grade_definition_id'], 'GRADE-SP01-A-V1')
                self.assertEqual(quote['mapping_relation'], 'subset_of')
            elif quote['original_product_name'] == '鲢':
                self.assertEqual(quote['species_id'], 'SP02')
                self.assertEqual(quote['grade'], 'ungraded')
                self.assertIsNone(quote['grade_definition_id'])
            else:
                self.assertIsNone(quote['species_id'])
                self.assertEqual(quote['product_type'], 'feed_ingredient')

    def test_weather_and_valid_low_oxygen_calibration_and_missing_result_states_remain(self):
        self.assertEqual(len(self.tables['water_observations']), 52560)
        self.assertTrue(all(r['model'] == 'ERA5' and not r['is_synthetic']
                            for r in self.tables['weather_observations']))
        self.assertTrue(any(r['environment_condition'] == 'low_oxygen' for r in self.tables['water_observations']))
        self.assertTrue(any(r['measurement_context'] == 'calibration' for r in self.tables['water_observations']))
        results = self.tables['water_test_results']
        for status in ['below_detection_limit', 'detection_failed']:
            subset = [r for r in results if r['result_status'] == status]
            self.assertTrue(subset)
            self.assertTrue(all(r['value'] is None and r['missing_reason'] for r in subset))

    def fixture(self, day, entered, left, opening, stocked, closing):
        return {
            'cohorts': [{'id': 'C01', 'species_id': 'SP01', 'parent_cohort_id': None}],
            'pond_cohort_occupancy': [{'id': 'OCC1', 'pond_id': 'P01', 'cohort_id': 'C01',
                                      'role': 'main', 'entered_at': entered, 'left_at': left}],
            'fish_daily_balance': [{'id': 'FDB1', 'pond_id': 'P01', 'cohort_id': 'C01',
                                    'species_id': 'SP01', 'balance_date': day,
                                    'occurred_at': day + 'T23:00:00+08:00',
                                    'opening_count': opening, 'opening_biomass_kg': opening * .3,
                                    'stocked_count': stocked, 'stocked_weight_kg': stocked * .3,
                                    'transfer_in_count': 0, 'transfer_in_weight_kg': 0,
                                    'closing_count': closing, 'closing_biomass_kg': closing * .3}],
            'stocking_events': [{'id': 'STK1', 'pond_id': 'P01', 'cohort_id': 'C01',
                                 'occurred_at': entered, 'count': stocked, 'weight_kg': stocked * .3}] if stocked else [],
            'harvests': [{'id': 'HAR1', 'pond_id': 'P01', 'cohort_id': 'C01', 'occurred_at': left,
                          'count': opening + stocked, 'net_weight_kg': (opening + stocked) * .3}],
        }

    def test_entry_day_sampling_is_after_entry_even_if_nine_am_is_too_early(self):
        tables = self.fixture('2025-06-15', '2025-06-15T10:00:00+08:00',
                              '2025-06-15T14:00:00+08:00', 0, 100, 0)
        result = environment.generate({**self.cfg, 'mode': 'sample'}, tables)
        self.assertEqual(len(result['growth_samples']), 1)
        sample = result['growth_samples'][0]
        self.assertGreater(datetime.fromisoformat(sample['sampled_at']), datetime.fromisoformat(tables['pond_cohort_occupancy'][0]['entered_at']))
        self.assertLess(datetime.fromisoformat(sample['sampled_at']), datetime.fromisoformat(tables['pond_cohort_occupancy'][0]['left_at']))
        self.assertEqual(sample['ledger_count'], 100)
        self.assertEqual(sample['ledger_biomass_kg'], 30)
        self.assertEqual(sample['ledger_basis_kind'], 'entry_before_daily_outflows')

    def test_final_single_day_month_samples_positive_opening_before_harvest(self):
        tables = self.fixture('2025-11-20', '2025-11-20T00:00:00+08:00',
                              '2025-11-20T14:00:00+08:00', 100, 0, 0)
        result = environment.generate({**self.cfg, 'mode': 'sample'}, tables)
        self.assertEqual(len(result['growth_samples']), 1)
        sample = result['growth_samples'][0]
        self.assertEqual(sample['id'], 'GR1_11')
        self.assertEqual(sample['ledger_count'], 100)
        self.assertEqual(sample['ledger_basis_kind'], 'opening_before_daily_outflows')
        self.assertLess(datetime.fromisoformat(sample['sampled_at']), datetime.fromisoformat(tables['harvests'][0]['occurred_at']))


if __name__ == '__main__':
    unittest.main()
