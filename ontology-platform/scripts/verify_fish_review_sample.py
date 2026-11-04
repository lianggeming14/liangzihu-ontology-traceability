"""Independent source/typed/graph/GIS readback of the isolated review schema."""
from build_fish_review_sample import *


def verify(config=None):
    if not __debug__:
        raise ValueError('Verification requires Python assertions enabled; do not use -O')
    config=config or load_config()
    audit,requirements,chosen,reasons,seed,outgoing=prepare_sample(config)
    output=config.output_dir
    report=json.loads((output/'readback.json').read_text(encoding='utf-8'))
    assert report['package_sha256']==audit.summary['package_sha256']
    assert report['seed_rows']==seed and report['total_sample_rows']==len(chosen)
    assert report['formal_adoption'] is False
    engine=create_engine(database_url(config),connect_args={'hostaddr':'127.0.0.1','connect_timeout':10},hide_parameters=True)
    mismatches=0;typed_cells=0
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        actual=connection.execute(text(f'SELECT * FROM {SCHEMA}.raw_records')).mappings().all()
        assert len(actual)==len(chosen)
        for row in actual:
            expected=chosen[row['table_name'],row['row_number']]
            mismatches+=int(row['payload']!=expected.payload or row['normalized']!=expected.normalized
                or row['status']!=expected.status or row['issues']!=expected.issues
                or row['source_pk']!=expected.pk or row['package_sha256']!=audit.summary['package_sha256']
                or row['sample_reason']!=reasons[expected.table,expected.row_number])
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
        valid=[row for row in chosen.values() if row.status in ('accepted','needs_review')]
        assert sum(roles.values())==len(valid),'Ontology node count differs'
        relation_count=connection.execute(text(f'SELECT count(*) FROM {SCHEMA}.ontology_relations')).scalar_one()
        assert relation_count==sum(len(outgoing[row.table,row.row_number]) for row in valid),'Ontology relation count differs'
        gis_count=connection.execute(text(f'SELECT count(*) FROM {SCHEMA}.gis_features')).scalar_one()
        assert gis_count==requirements['feature_count'],'GIS feature count differs'
        constraints=connection.execute(text('''SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON c.connamespace=n.oid
            WHERE n.nspname=:schema AND c.contype='f' AND c.convalidated'''),{'schema':SCHEMA}).scalar_one()
    report['checks'].update(raw_field_mismatches=mismatches,typed_cells_verified=typed_cells,
        independent_source_readback='passed',independent_typed_readback='passed',
        raw_readback_count=len(actual),ontology_nodes=sum(roles.values()),ontology_relations=relation_count,
        gis_features=gis_count,invalid_gis_geometries=invalid,resolved_edges_without_target=broken,
        graph_node_roles=roles,validated_foreign_keys_including_graph=constraints)
    report['review_schema']=SCHEMA
    report['verified_at']=datetime.now(timezone.utc).isoformat()
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        for item in report['tables']:
            item['relation_examples']=[dict(row) for row in connection.execute(text(f'''SELECT n.source_pk,e.field_name,e.target_table,e.target_pk,e.resolution
                FROM {SCHEMA}.ontology_relations e JOIN {SCHEMA}.ontology_nodes n ON e.from_node=n.node_id
                WHERE n.table_name=:table ORDER BY e.edge_id LIMIT 12'''),{'table':item['name']}).mappings()]
    (output/'readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    render(report,output)
    engine.dispose()
    print(json.dumps(report['checks'],ensure_ascii=False))


if __name__=='__main__':
    try:
        # Share exactly the same configuration and safety guards as --verify.
        main(['--verify',*sys.argv[1:]])
    except Exception as error:
        message=str(error) if isinstance(error,(ValueError,FileNotFoundError)) else type(error).__name__
        raise SystemExit('Fish review verification failed: '+message) from None
