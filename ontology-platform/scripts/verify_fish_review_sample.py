"""Independent source/typed/graph/GIS readback of the isolated review schema."""
from build_fish_review_sample import *
from sqlalchemy import inspect


def verify():
    base=ROOT/'.runtime/source-imports/wuchangfish-l1-2025-01/1eb0bab8f86f'
    audit=load_package(base/'extracted/output',base/'source-manifest.json')
    report=json.loads((OUT/'readback.json').read_text(encoding='utf-8'))
    assert report['package_sha256']==audit.summary['package_sha256']
    required=json.loads((ROOT/'docs/fish/gis-required-identities.json').read_text(encoding='utf-8'))['identities']
    chosen,_,seed,_=choose(audit,required)
    settings=runtime_settings()
    review_target(settings,json.loads((ROOT/'.runtime/fish-l1-acceptance/ownership.json').read_text()),report['package_sha256'])
    engine=create_engine(settings.gis_migration_database_url)
    mismatches=0;typed_cells=0
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        actual=connection.execute(text(f'SELECT * FROM {SCHEMA}.raw_records')).mappings().all()
        assert len(actual)==len(chosen)
        for row in actual:
            expected=chosen[row['table_name'],row['row_number']]
            mismatches+=int(row['payload']!=expected.payload or row['normalized']!=expected.normalized
                or row['status']!=expected.status or row['issues']!=expected.issues)
        assert not mismatches,'Source readback differs'
        for name,spec in audit.schema['tables'].items():
            result=connection.execute(text(f'SELECT * FROM {SCHEMA}.data_{name}')).mappings().all()
            expected={r.pk:r for r in chosen.values() if r.table==name and r.status in ('accepted','needs_review')}
            assert len(result)==len(expected)
            for row in result:
                source=expected[row['id']]
                for field,desc in spec['columns'].items():
                    assert row[field]==typed(source.normalized.get(field),desc),(name,field)
                    typed_cells+=1
        broken=connection.execute(text(f'''SELECT count(*) FROM {SCHEMA}.ontology_relations e
            LEFT JOIN {SCHEMA}.ontology_nodes n ON n.node_id=e.to_node
            WHERE e.resolution='resolved' AND n.node_id IS NULL''')).scalar_one()
        assert broken==0
        invalid=connection.execute(text(f'SELECT count(*) FROM {SCHEMA}.gis_features WHERE NOT ST_IsValid(geom)')).scalar_one()
        assert invalid==0
        roles=dict(connection.execute(text(f'SELECT role,count(*) FROM {SCHEMA}.ontology_nodes GROUP BY role')).all())
        constraints=connection.execute(text('''SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON c.connamespace=n.oid
            WHERE n.nspname=:schema AND c.contype='f' AND c.convalidated'''),{'schema':SCHEMA}).scalar_one()
    report['checks'].update(raw_field_mismatches=mismatches,typed_cells_verified=typed_cells,
        independent_source_readback='passed',independent_typed_readback='passed',
        graph_node_roles=roles,validated_foreign_keys_including_graph=constraints)
    report['review_schema']=SCHEMA
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        for item in report['tables']:
            item['relation_examples']=[dict(row) for row in connection.execute(text(f'''SELECT n.source_pk,e.field_name,e.target_table,e.target_pk,e.resolution
                FROM {SCHEMA}.ontology_relations e JOIN {SCHEMA}.ontology_nodes n ON e.from_node=n.node_id
                WHERE n.table_name=:table ORDER BY e.edge_id LIMIT 12'''),{'table':item['name']}).mappings()]
    (OUT/'readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    render(report)
    engine.dispose()
    print(json.dumps(report['checks'],ensure_ascii=False))


if __name__=='__main__':verify()
