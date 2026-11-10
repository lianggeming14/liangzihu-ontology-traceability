import copy
import importlib.util
import unittest


class ActivationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('activate_csv_batch'),'CSV activation is not implemented')
        import activate_csv_batch
        return activate_csv_batch

    def fixture(self):
        root='https://w3id.org/lzo/ontology/DomainEntity';parent='https://w3id.org/lzo/ontology/ReferenceRecord'
        base={'contract':'fish-rdf-review/1','root_iri':root,'rdf_graphs':['urn:old:'+str(i) for i in range(4)],
            'counts':{'instances':1,'classes':3,'source_classes':1,'triples':100,'relations':0,'resolved_relations':0},
            'concepts':[{'iri':root,'parent_iri':None,'children':[parent],'table':None,'instance_count':0},
                        {'iri':parent,'parent_iri':root,'children':['urn:old:class'],'table':None,'instance_count':0},
                        {'iri':'urn:old:class','parent_iri':parent,'children':[],'table':'legacy','instance_count':1}]}
        schema={'tables':{'grade_definitions':{'columns':{'id':{'type':'string'}}}}}
        report={'graph_iri':'urn:new:graph','triple_count':50,'termset_sha256':'a'*64,
            'model':{'instances':2,'relations':0,'resolved_relations':0,'raw_rows':2,'schema_fields':1,
                'tables':{'grade_definitions':{'rows':2}}}}
        return base,schema,report

    def test_merge_preserves_legacy_and_recalculates_all_parent_counts(self):
        module=self.module();base,schema,report=self.fixture();before=copy.deepcopy(base)
        result=module.merge_manifest(base,schema,report)
        self.assertEqual(base,before)
        self.assertEqual(result['counts']['instances'],3)
        self.assertEqual(result['counts']['source_classes'],2)
        self.assertEqual(result['counts']['triples'],150)
        self.assertEqual(result['legacy_counts']['instances'],1)
        self.assertEqual(len(result['rdf_graphs']),5)
        self.assertTrue(any(c['table']=='csv_grade_definitions' for c in result['concepts']))
        from fish_rdf_sample import role
        self.assertEqual(next(c for c in result['concepts'] if c['table']=='csv_grade_definitions')['role'],role('grade_definitions'))
        self.assertEqual(next(c for c in result['concepts'] if c['iri']==base['root_iri'])['total_instance_count'],3)

    def test_second_activation_reuses_batch_without_double_counting(self):
        module=self.module();base,schema,report=self.fixture()
        one=module.merge_manifest(base,schema,report);two=module.merge_manifest(one,schema,report)
        self.assertEqual(one['counts'],two['counts'])
        self.assertEqual(one['rdf_graphs'],two['rdf_graphs'])
        self.assertEqual(len(two['csv_batches']),1)


if __name__=='__main__':unittest.main()
