"""CSV cell, identity and relationship regressions; no database writes."""
import copy
from decimal import Decimal
import unittest
import importlib.util
import hashlib
from pathlib import Path
import tempfile


PACKAGE='a'*64
DEFINITIONS={'tables':{
    'farms':{'columns':{'id':{'type':'string'},'name':{'type':'string'}}},
    'ponds':{'columns':{'id':{'type':'string'},'farm_id':{'type':'string'},'depth_m':{'type':'number','unit':'m'}}},
    'events':{'columns':{'id':{'type':'string'},'pond_id':{'type':'string'},'quantity_kg':{'type':'number','unit':'kg'},'occurred_at':{'type':'string','format':'date-time'}}},
}}
RULES=[{'source_table':'ponds','field':'farm_id','target_table':'farms','kind':'scalar'},
    {'source_table':'events','field':'pond_id','target_table':'ponds','kind':'scalar'},
    {'source_table':'events','field':'related_ids','target_table':'events','kind':'delimited','separator':';'},
    {'source_table':'registry','field':'target_id','kind':'polymorphic','discriminator_field':'target_kind','cases':{'event':'events'}}]


def fixture():
    return {'farms':[{'id':'F01','name':'Farm'}],
        'ponds':[{'id':'001','farm_id':'F01','depth_m':''}],
        'events':[{'id':'E1','pond_id':'001','quantity_kg':'123456789012345678.123456789','occurred_at':'2025-01-01T00:00:00+08:00','related_ids':'E2; MISSING'},
                  {'id':'E2','pond_id':'001','quantity_kg':'0','occurred_at':'2025-01-02T00:00:00+08:00','related_ids':''}],
        'registry':[{'id':'R1','target_kind':'event','target_id':'E1'}],
        'source_registry':[{'id':'farms','table':'farms','origin_kind':'revised_rule_simulation'},
                           {'id':'ponds','table':'ponds','origin_kind':'revised_rule_simulation'},
                           {'id':'events','table':'events','origin_kind':'revised_rule_simulation'}]}


class CSVModelTests(unittest.TestCase):
    def model(self):
        self.assertIsNotNone(importlib.util.find_spec('csv_batch_model'),'CSV batch mapper is not implemented')
        import csv_batch_model
        return csv_batch_model

    def build(self,tables=None,package=PACKAGE):
        return self.model().build_snapshot(tables or fixture(),DEFINITIONS,RULES,package)

    def test_decimal_text_identifier_and_empty_are_not_conflated(self):
        snapshot,report=self.build()
        nodes={(x['table_name'],x['source_pk']):x for x in snapshot['nodes']}
        self.assertEqual(nodes['ponds','001']['properties']['id'],'001')
        self.assertIsNone(nodes['ponds','001']['properties']['depth_m'])
        self.assertEqual(Decimal(nodes['events','E1']['properties']['quantity_kg']),Decimal('123456789012345678.123456789'))
        self.assertEqual(Decimal(nodes['events','E2']['properties']['quantity_kg']),Decimal(0))
        self.assertEqual(report['raw_rows'],len(snapshot['raw']))

    def test_bad_numeric_and_date_preserve_raw_and_become_visible_issues(self):
        tables=fixture();tables['events'][0].update(quantity_kg='NaN',occurred_at='2025-02-30T00:00:00+08:00')
        snapshot,report=self.build(tables)
        raw=next(x for x in snapshot['raw'] if x['table_name']=='events' and x['source_pk']=='E1')
        node=next(x for x in snapshot['nodes'] if x['table_name']=='events' and x['source_pk']=='E1')
        self.assertEqual(raw['payload']['quantity_kg'],'NaN')
        self.assertEqual(raw['status'],'needs_review')
        self.assertEqual(len(raw['issues']),2)
        self.assertIsNone(node['properties']['quantity_kg'])
        self.assertIsNone(node['properties']['occurred_at'])

    def test_source_and_two_batches_do_not_share_canonical_identity(self):
        before=fixture();original=copy.deepcopy(before)
        one,_=self.build(before);two,_=self.build(before,'b'*64)
        self.assertEqual(before,original)
        self.assertFalse({x['node_id'] for x in one['nodes']}&{x['node_id'] for x in two['nodes']})
        self.assertEqual(next(x for x in one['nodes'] if x['table_name']=='ponds')['nature'],'synthetic')

    def test_reference_lists_and_polymorphic_targets_preserve_resolution(self):
        snapshot,report=self.build()
        edges=snapshot['relations']
        self.assertTrue(any(x['field_name']=='target_id' and x['target_table']=='events' and x['resolution']=='resolved' for x in edges))
        related=[x for x in edges if x['field_name']=='related_ids']
        self.assertEqual([x['target_pk'] for x in related],['E2','MISSING'])
        self.assertEqual([x['list_index'] for x in related],[0,1])
        self.assertIsNone(related[1]['to_node'])
        self.assertEqual(related[1]['resolution'],'unresolved')

    def test_identical_duplicates_keep_both_sources_and_one_business_node(self):
        tables=fixture();tables['ponds'].append(dict(tables['ponds'][0]))
        snapshot,report=self.build(tables)
        self.assertEqual(sum(x['table_name']=='ponds' for x in snapshot['raw']),2)
        self.assertEqual(sum(x['table_name']=='ponds' for x in snapshot['nodes']),1)
        self.assertEqual(report['duplicate_rows'],1)

    def test_conflicting_duplicate_key_does_not_pick_a_silent_winner(self):
        tables=fixture();tables['ponds'].append({**tables['ponds'][0],'depth_m':'2'})
        snapshot,report=self.build(tables)
        self.assertFalse(any(x['table_name']=='ponds' for x in snapshot['nodes']))
        self.assertEqual(report['conflicting_rows'],2)
        self.assertTrue(all(x['to_node'] is None for x in snapshot['relations'] if x['target_table']=='ponds'))

    def test_new_fields_infer_types_without_turning_codes_into_numbers(self):
        model=self.model();infer_definition,normalize_cell=model.infer_definition,model.normalize_cell
        self.assertEqual(infer_definition('id',['0001'])['type'],'string')
        self.assertEqual(infer_definition('version',['1'])['type'],'string')
        self.assertEqual(infer_definition('upper_inclusive',['true','false'])['type'],'boolean')
        self.assertEqual(normalize_cell('TRUE',{'type':'boolean'}),True)
        with self.assertRaises(ValueError):normalize_cell('1',{'type':'boolean'})

    def test_weather_false_synthetic_flag_does_not_claim_field_measurement(self):
        tables=fixture();tables['weather_observations']=[{'id':'W1','is_synthetic':'false'}]
        tables['source_registry'].append({'id':'weather_observations','table':'weather_observations','origin_kind':'weather_reanalysis'})
        snapshot,_=self.build(tables)
        node=next(x for x in snapshot['nodes'] if x['table_name']=='weather_observations')
        self.assertEqual(node['nature'],'imported_unverified')

    def test_source_manifest_csv_role_and_file_digest_control_reading(self):
        model=self.model()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'csv').mkdir()
            body='id,depth_m\n001,\n'.encode('utf-8-sig');(root/'csv/ponds.csv').write_bytes(body)
            item={'path':'csv/ponds.csv','member_role':'csv','is_csv':True,'bytes':len(body),
                'sha256':hashlib.sha256(body).hexdigest(),'encoding':'utf-8-sig','header':['id','depth_m'],'row_count':1}
            manifest={'csv_file_count':1,'members':[item]}
            tables,metadata=model.read_tables(root,manifest)
            self.assertEqual(tables['ponds'],[{'id':'001','depth_m':''}])
            self.assertEqual(metadata['ponds']['line_ends'],[2])
            (root/'csv/ponds.csv').write_bytes(body+b'002,1\n')
            with self.assertRaises(ValueError):model.read_tables(root,manifest)


if __name__=='__main__':unittest.main()
