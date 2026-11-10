"""Check the published review entry/configuration without databases or secrets."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import hashlib
from collections import Counter
import json
import re
import shutil
import tempfile

ROOT=Path(__file__).resolve().parents[1]

CSV_PACKAGE='a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524'
CSV_GRAPH_PREFIX='urn:lzo:csv-batch:v1:'+CSV_PACKAGE+':graph:'
LEGACY_MANIFEST_SHA256='d4cafec97c4185b793397287a8e08a7bdc35aab1a83d94d539f89157e2303901'
LEGACY_MAP_SHA256='b36837fde1bd2dfc03d09bc37e07f0eb2edffafec6be6fe624eaf95d8e115a94'
# SHA256 of all 84 previously published class shards, captured before CSV activation.
LEGACY_SHARD_SHA256={
    "attachment_links": "dfe90e5a93cc3907cbc87d1d6a7d19e2e233fd7de51115e712b2cd518f50cd07",
    "attachments": "6b6fd303a58b1cd683484624ab523bf227b8a2f6824b7d46eb4b11cc9c1c3710",
    "case_observations": "d564c79281473eba8f280218c7eaba35a488eeff9b880bedc6fb8efb12578d67",
    "cash_allocations": "f3a89a112267d41b9d689a68b3f4ee7b9a4c154f5c84570acbb8a75711a7581c",
    "cash_transactions": "65e6c614a60547f6137ae2a89d38ed8fb45bc046abb33abc19b4bd40854c3c94",
    "cohorts": "e72d1011a5f6b90d98758a063449731a7a415eab6e5edf4738f9ebdf20f26be7",
    "control_commands": "45c6e1440460558e20a6a5828e550d61654176a9f26bd7427ce4d8ee4ed51438",
    "cost_allocations": "3cee4eb25e164a4c10fcfaa26bb93eb2d1f80e626d3e950060aca34f457e5f10",
    "cost_entries": "dcb74eeecd81c36681793659a4013f961286464367e2df443d6464a031f6ba69",
    "device_calibrations": "8e02b2fbc6de9efb78b941cd9c952adddeb22344a77d02e400729664d3d25886",
    "device_installations": "bbe1487a4ce6d43268b25a4901703eaafbe1aef1b8c9becf2737347d7cef656b",
    "device_maintenance": "308c0e25aa25cbd0e842425890ee691599544df2caae7664f99a16adeb73e946",
    "device_operations": "4eb4678b6cf1fa72ff78f819218ad2e2d76a170d9285fd8afc654e0a70810c4a",
    "devices": "53ec847eb0b5f0096d65f4ddf6e8839c7a9a97885d3dee382d9b4f8751e3f4ec",
    "diagnostic_tests": "81dc09fd9a42c3a54de56a463ff519c4f1b5881b57a35c2084c1df9c16401a9b",
    "dictionaries": "6673a004dd64a1a13aa3f0c068785bdee0bacfa848d0e00144019c68c59a7355",
    "disposal_events": "76bcc7281707c66f5834f1c2a92c84d6181fed84aff433bc40a616df178a3849",
    "document_versions": "964f475d59695e95f214602395d609b98abecc259e049263b38113c5cea017c4",
    "documents": "afda7af8e519ec0c0fbfc82a462b3caa6fe1d168680d16927280f0590c853974",
    "drawing_documentstatement": "105a3017526b575113a3ad4b495dabf27c03b96ea8da13ba0f191e8cd45cf1e2",
    "drawing_engineeringasset": "a0053f56bb0fd284aaa79a946e40a229bca8ac3aa56c3d3672715e7e91d5d45f",
    "drawing_engineeringitem": "365579f2c1a1c113fa9deb3e736978becaa98eab678c8ab3ab63e7729b6b3cc5",
    "drawing_field": "31c354db177d5b838ebb1340154c74ac24f230d350737eb26a189c69c7517c95",
    "drawing_measurement": "6e3b8b387de712467c9684972cf5967214b81c21094d8e4ffc4bffd5fefdcde6",
    "drawing_pond": "1a988d2351f841c61361885cea45a6eaa2183b64b729ef3d361db2535c34fc28",
    "drawing_project": "6d181e0a5977ef13428adbf5dd9f7d9081646d4d2ff0b589dd61cbf3ded89152",
    "drawing_region": "227bf56d617462b53a729ab100840939182e2f3b235b245027b24814d38254bd",
    "drawing_sourcedrawing": "e7360c074987cd45ec3a808a6c505222a1cd8c7c84ef9fbf18b9ec3584eb105b",
    "event_registry": "5bfe9368c2c5516bbf6fa6a44ea96ed09d133701f1455045500bc37d34fcb5c7",
    "farms": "acb8d16155bb82b836f7a963faac0174ae16541b3b7c5e148e9b1ebf833d27d7",
    "feeding_events": "da60a1241ef84ef148841aca43b3a1f7d6e380891d4f2f3fb86f93f3be869819",
    "fish_daily_balance": "7d065068165839714310064ad2684fdf186c00717f7a99bfd52b7694dedfc154",
    "growth_grade_items": "95cc4b46452dcd0a9f9b7340e54345b822b79343457a644f6546e2dd84b30b98",
    "growth_individuals": "2998dbfe0f24da88f44f763ba034cae4059c99313f360d9a25eaf7c2b9802260",
    "growth_samples": "8004e9cdfbd1dd68f3e4d16aa71e65d6f8490bd415bcfadb33d52d866ed34d19",
    "harvest_grade_items": "2217bcf294e95d6a184c9ec5cb524b4ef0c6ba98f09dd18495990ce3a075c011",
    "harvest_sale_allocations": "2a3f4c48e55aa3b7d266333bf4039f8b91124e3e6c9ed4f4a450607732c22771",
    "harvests": "094e447d0f7fde3d146fe405d2bc73a691c274fd2b82b287fb83296dfee8eab2",
    "health_cases": "cf21d068198530cb1fddd0bb446fbc65407a4d9cf5fbc959a097e3b1e44489ac",
    "inventory_lot_status": "f3302b12075cfd29fafd56e31a65207a56888c36464d741874c47ba41a10fbf4",
    "inventory_movements": "9eab012ace20b70756496af912ab79e9d1d704ee8a156ee0e96703b898b586e0",
    "map_bare": "8fc55e61fdbdae5defbe30df5eb19408ac5703b6b29ba21ed1a7f870d15b2c8e",
    "map_channel": "fad4e35a1e4e52ee486edd099499c56a7080a4813f866bbdb822419c1f9b9ee0",
    "map_facility": "a433912a24731878d09c2db8fb1c6cbbe22be9d17514c862c54af22a4220a58c",
    "map_field": "24c87c2eb51ca88f11cd6d180d389851e429df26fd581b88e0e4dd787bb39a69",
    "map_lake": "b08feae704c9bbffb4597f29e9aae7577667901c8cf0440710dd355af559e10b",
    "map_layer": "10e6cff044c0abc142a3705cca9064f31728d3bb59b98fd4c20feb6e24fd900a",
    "map_pond": "5658dc6f12e02343af014f4ae9c80039060806a2b93c038febf71d5b9642f75a",
    "map_road": "812d4a9bc28dba25d1adf85d3bc9938aabafb551279b53f191f6a0f359e9d981",
    "map_settlement": "e88073f48b929417cd4d51d58dc8a215b20b159c42c638bfdc97f52f95ac53f3",
    "map_unresolved_label": "fb0cd502d33842d5a1fd7eb4aad26599a0c1d4812c7b5044cdebf08b70a3c1f3",
    "map_woodland": "e95cf9bb48e7d69f3c22d12bd1596ed945732188fce304706cd56dd350b85462",
    "media_annotations": "c7cff5de922f7958566899d2d9766a5650501e036263d05fb0c1edd44f4716f3",
    "mortality_events": "a52424ccf085c66d7a3ce1eb3526167a6629363d110fb07604cc16391b794a64",
    "opening_balances": "6111a310d57221acaa46f9a3091d57515661516ac693c8f1a33a1ec4b97cb2a4",
    "partners": "953ad1a208cb6a00af4f09f63b155a729d9aa3d4111597fa51af1717acbe910a",
    "patrol_events": "03c74c19cece3458e02746679bb9805b50d7133cd649ae35d1f6dc034bbdbe33",
    "persons": "a9ee9feceea794a2d2bc281c6e63fd1b91fbb9f8b21950b480820944851887fc",
    "pond_cohort_occupancy": "f16420d8a04963c20255f1a9293e29c6abf2db9e9f8c50d1b014961e33de5b84",
    "pond_maintenance": "ed817807257d60d08caac3cad5ec5a9aa88b85740f1b833622da0fe04611c9d8",
    "pond_preparations": "6cb03744715b837f4864441e4617821273d581fbb5f5351e9f123567e1e7e9af",
    "ponds": "a6704ea02b959588b96678a1996499e045609cc387b7264a55ab18836f01e063",
    "price_observations": "10010055a805eb5fa80642d2c57a78489977fc8c74a87beba9f0620f10aaf784",
    "production_plans": "afc0da44ce45f8692f06e563b0b59f1b3f5e5816f6fa12e7d9b036f73ea0aef2",
    "products": "66ba1ab60461343458a92e9bf8835ed7cc6e36b2f48bacbb29c0647de7c35a20",
    "purchase_items": "1e0478376f5d33e716356faa55453a249f83f091314d456c5c884940f38a3544",
    "purchases": "204e56cfaf34104a0ec2f61dfa3be0ca0313798c7464e425028700a0366f1134",
    "record_provenance": "55bd15da787433fe60dc4fdafac9e968f8e390350b12887cff13723fb5e04c54",
    "sale_items": "91de0e00573bc47e49a2d140de39e34434cb33be40ea7ec9b613619cb97f1da3",
    "sales": "d9cf6cf7dd0dedca1dfca6c6ea932144217c32c76cd31a361cb59abeb069faf0",
    "settlement_deductions": "82973881b709b2302c90b53bcd562f7a03464235fe37f545a2958cfa89e8b210",
    "settlements": "f7343f3484985cc8ddac40fe741d13e6aea8c4bf192887b854a29db2607e206e",
    "sources": "86501d1ef2808a251be4d8ba2b4459e926ece0656035ac4575f45f84c7fb3be3",
    "spatial_layer_registry": "270ce6c043857cc8641a45755264371da7d9b67fdc6e730ef2707c92a14057ec",
    "species": "c449ffec7c982f155f274f9997e74d43337c6cd065470ee8b10c2069682f7ae5",
    "stocking_events": "63aa520afc0b4296639a1bb2dfeea951d46dc72a2d309b74583d3369622660a1",
    "transfer_allocations": "5e804f918304ab23d1445100c7b163fc83126119d41c176617a6fcb832821ba2",
    "transfer_events": "c29894840204690cb5db83ac7aa89730435f262665619fc2cef8bdb1e0a679c1",
    "treatment_events": "669885adb34ad6d0bee3e1d00161fc2097ead9bc622d33dc1793984f4ec644dd",
    "water_observations": "dfdd2fe43e82616dd36bf8b077fc04609c8ebf7321f561b7334535c613f3503e",
    "water_operations": "17be285aa02b0493897ffe9e5a2d047345615b25993601618e58b81d2d4041de",
    "water_samples": "18452818ec555923b9394c0e3729f4000d7ac990e840de22f4daf27b7107ae64",
    "water_test_results": "1219c92d9a18864e59e8f2719066490317769f84884052031737ed4df9627842",
    "weather_observations": "93772398d3145f445ee89f96d562a398d95271ac6f9cee89a15807872a69e769"
}


def _load(path):
    assert path.is_file(),f'Missing recorded evidence: {path.name}'
    return json.loads(path.read_text(encoding='utf-8'))


def _sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _checked_snapshot(data,relative,entry):
    """Check the complete public byte inventory without decoding source records."""
    pattern=(r'(?:classes/csv_[a-z0-9_]+\.json\.gz|details/csv_[a-z0-9_]+/\d{5}\.json\.gz|'
             r'relations/csv_[a-z0-9_]+/[a-f0-9-]{36}/(?:incoming|outgoing)-\d{5}\.json\.gz)')
    assert isinstance(relative,str) and re.fullmatch(pattern,relative),f'Unsafe CSV snapshot path: {relative}'
    path=(data/relative).resolve()
    assert path.is_relative_to(data.resolve()) and path.is_file(),f'Missing CSV snapshot: {relative}'
    assert type(entry['bytes']) is int and 0<entry['bytes']<20*1024*1024
    assert re.fullmatch(r'[0-9a-f]{64}',entry['sha256'])
    assert path.stat().st_size==entry['bytes'] and _sha(path)==entry['sha256'],f'CSV snapshot bytes differ: {relative}'


def csv_check(root,manifest,navigation,legacy_graphs,*,pending_browser=False):
    """Cross-check shipped full-batch evidence; never contact PostgreSQL or Jena."""
    directory=root/'docs/csv-batch';review=root/'docs/fish/ontology-review';data=review/'data'
    source=_load(directory/'source-manifest.json')
    quality=_load(directory/'quality-audit.json')
    rules=_load(directory/'relation-map.json')
    model=_load(directory/'model-readback.json')
    dictionary=_load(directory/'field-dictionary.json')
    pg=_load(directory/'pg-readback.json')
    structure=_load(directory/'schema-structure.json')
    rdf=_load(directory/'rdf-readback.json')
    shacl=_load(directory/'shacl-readback.json')
    prior=_load(directory/'prior-graphs-readback.json')
    bounded=_load(directory/'navigation-files.json')
    activation=_load(directory/'activation-readback.json')
    assert source['archive_sha256']==CSV_PACKAGE
    assert source['archive_git_blob']=='af355c9199304fc7dd37634cdf5d5984feed08be'
    assert source['source_commit']=='cb9353499b6ede33fa60b3c67e18a983e362ab16'
    assert source['archive_bytes']==2578429 and source['csv_status']=='passed'
    assert source['csv_file_count']==66 and source['row_count']==153862
    assert source['bad_rows']==source['blank_rows']==0 and source['encodings']=={'utf-8-sig':66}
    assert len(source['members'])==source['file_count']==133 and source['metadata_file_count']==67
    inputs={Path(item['path']).stem:item for item in source['members'] if item.get('is_csv') is True}
    assert len(inputs)==66 and sum(item['row_count'] for item in inputs.values())==153862
    assert all(item['member_role']=='csv' and item['header_valid'] and item['bad_rows']==0
               and item['row_count_complete'] and item['status']=='valid_csv' for item in inputs.values())
    assert sum(item.get('member_role')=='metadata' and item.get('is_csv') is False for item in source['members'])==67
    assert all(re.fullmatch(r'[0-9a-f]{64}',item['sha256']) for item in source['members'])
    assert quality['summary']['table_count']==66 and quality['summary']['row_count']==153862
    assert quality['summary']['issue_counts']=={}
    assert quality['provenance']['source_archive_sha256']==CSV_PACKAGE
    assert len(rules['relations'])==quality['summary']['relationship_definitions']==345
    assert dict(Counter(rule['kind'] for rule in rules['relations']))==quality['summary']['relationship_kind_counts']
    assert model['raw_rows']==model['instances']==153862 and model['source_tables']==66
    assert model['schema_fields']==1397 and model['relations']==810934 and model['resolved_relations']==810891
    assert all(model[name]==0 for name in ('duplicate_rows','conflicting_rows','quarantined_rows','invalid_typed_cells'))
    assert len(dictionary['tables'])==66 and set(dictionary['tables'])==set(model['tables'])==set(inputs)
    assert sum(len(spec['columns']) for spec in dictionary['tables'].values())==1397
    for table,spec in dictionary['tables'].items():
        assert list(spec['columns'])==inputs[table]['header'] and spec['path']==inputs[table]['path']
        assert model['tables'][table]['rows']==inputs[table]['row_count']
        assert model['tables'][table]['fields']==len(spec['columns'])
    cells=sum(item['rows']*item['fields'] for item in model['tables'].values())
    assert cells==3539134

    assert pg['contract']=='csv-batch-pg-readback/1' and pg['status']=='passed'
    assert pg['package_sha256']==CSV_PACKAGE and pg['schema']=='csv_batch_a4d78be79a83'
    assert pg['schema_structure_matches'] and pg['tables_checked']==72
    assert pg['raw_rows_checked']==pg['nodes_checked']==153862
    assert pg['original_cells_checked']==pg['business_cells_checked']==cells
    assert pg['relations_checked']==810934 and pg['resolved_relations']==810891 and pg['unresolved_relations']==43
    assert pg['unresolved_targets_remain_null'] is True and pg['formal_adoption'] is False
    assert pg['source_read_only'] is True and pg['database_write_performed'] is False
    assert pg['identity']['complete'] is True and pg['identity']['formal_adoption'] is False
    assert pg['identity']['logical_schema_sha256']==_digest(dictionary)
    assert pg['identity']['relation_rules_sha256']==_digest(rules['relations'])
    assert re.fullmatch(r'[0-9a-f]{64}',pg['physical_schema_sha256'])
    labels={item['label']:item for item in pg['checks']}
    expected_labels={'batch_metadata','source_tables','field_dictionary','raw_records','ontology_nodes','ontology_relations'}
    expected_labels|={'data_'+table for table in dictionary['tables']}
    assert len(pg['checks'])==len(labels)==72 and set(labels)==expected_labels
    for item in labels.values():
        assert item['status']=='passed' and item['mismatch_rows']==0 and item['mismatch_ordinals']==[]
        assert item['expected_rows']==item['actual_rows']==item['rows_checked']
        assert item['expected_sha256']==item['actual_sha256'] and re.fullmatch(r'[0-9a-f]{64}',item['actual_sha256'])
    for label,count in [('raw_records',153862),('ontology_nodes',153862),('ontology_relations',810934),
                         ('source_tables',66),('field_dictionary',1397),('batch_metadata',1)]:
        assert labels[label]['actual_rows']==count
    for table,info in model['tables'].items():assert labels['data_'+table]['actual_rows']==info['rows']
    assert structure['schema']==pg['schema'] and structure['business_tables']==66 and structure['support_tables']==6
    assert structure['field_dictionary_entries']==1397 and structure['confirmed_scalar_foreign_keys']==261
    assert {item['name'] for item in structure['tables']}==expected_labels
    ddl=(directory/'schema.sql').read_text(encoding='utf-8')
    assert len(re.findall(r'CREATE TABLE ',ddl))==72
    assert not re.search(r'\b(?:DROP|TRUNCATE)\b',ddl,re.I)
    assert not re.search(r'\bNUMERIC\s*\(',ddl,re.I)
    assert all(statement+';' in ddl for statement in structure['statements'])

    assert rdf['contract']=='csv-rdf-readback/1' and rdf['status']=='passed'
    assert rdf['package_sha256']==CSV_PACKAGE and rdf['formal_adoption'] is False
    assert rdf['full_terms_equal'] is True and rdf['unexpected_or_missing_terms']==0
    assert rdf['triple_count']==21333891 and rdf['older_graph_counts_unchanged'] is True
    assert re.fullmatch(r'[0-9a-f]{64}',rdf['termset_sha256']) and re.fullmatch(r'[0-9a-f]{64}',rdf['nt_sha256'])
    assert rdf['graph_iri']==CSV_GRAPH_PREFIX+rdf['termset_sha256']
    assert rdf['sparql']=={'instances':153862,'source_records':153862,'relations':810934,
                           'resolved_relations':810891,'missing_inverse':0,'orphan_targets':0}
    assert rdf['model']==model and rdf['raw_payload_public'] is False
    assert shacl['status']=='passed' and shacl['instances_validated']==153862 and shacl['violations']==0
    assert shacl['datatype_constraints']==1397 and len(shacl['classes'])==66
    assert sum(item['instances'] for item in shacl['classes'])==153862
    assert all(item['conforms'] is True and item['violations']==0 for item in shacl['classes'])
    assert rdf['shacl']=={'status':'passed','instances_validated':153862,'datatype_constraints':1397,'violations':0}

    assert prior['contract']=='csv-prior-graphs-readback/1' and prior['status']=='passed' and prior['mode']=='read_only'
    assert prior['csv_source_archive_sha256']==CSV_PACKAGE and prior['rdf_literal_normalization'] is False
    assert prior['errors']==[] and prior['inventory_stable_during_readback'] is True
    assert prior['baseline']['old_graph_count']==977 and prior['baseline']['old_non_review_graph_count']==971
    assert prior['baseline']['postgres']['transaction_read_only']=='on'
    assert prior['baseline']['postgres']['review_raw_records']==20606
    protected={item['graph_iri']:item for item in prior['graphs']}
    assert len(protected)==4 and set(protected)==set(legacy_graphs)
    expected_prior=[(2183946,'e291446443a45ec8f50220b1cf3c5121d87ba16cf7f85a8e38266d9a92b4a49c'),
                    (18546,'82c01f101995be69e546590279fac9473374825914133050826f0d97bdceb662'),
                    (125954,'64de82d74cbb9e010a68569213657107de50b21e46b5db74f1f895b5718aa281'),
                    (392523,'410840247d55e49e5d6ca67ccf8f9a1e365090c28b96f8bcdfdc911880bf36db')]
    assert sorted((item['expected_triples'],item['expected_rdf_termset_sha256']) for item in protected.values())==sorted(expected_prior)
    for item in protected.values():
        assert item['status']=='passed'
        assert item['expected_triples']==item['sparql_count']==item['parsed_triples']==item['unique_triples']
        assert item['expected_rdf_termset_sha256']==item['rdf_termset_sha256']
    for inventory in (prior['inventory_before'],prior['inventory_after']):
        assert inventory['old_graph_count']==977 and inventory['old_graph_counts_unchanged'] is True
        assert inventory['additional_graph_count']==1
        assert inventory['additional_graphs']==[{'graph_iri':rdf['graph_iri'],'triple_count':21333891}]

    assert bounded['contract']=='csv-bounded-navigation/1'
    assert bounded['class_shards']==66 and bounded['instances']==153862
    assert bounded['detail_chunk_size']==500 and bounded['relation_chunk_size']==4800 and bounded['raw_payload_public'] is False
    files=bounded['files']
    assert len([name for name in files if name.startswith('classes/')])==66
    assert len([name for name in files if name.startswith('details/')])==bounded['detail_chunks']
    assert len([name for name in files if name.startswith('relations/')])==bounded['relation_chunks']
    for name,entry in files.items():_checked_snapshot(data,name,entry)
    actual_paths={path.relative_to(data).as_posix() for folder in ('classes','details','relations')
                  for path in (data/folder).rglob('*.json.gz')
                  if folder!='classes' or path.name.startswith('csv_')}
    assert actual_paths==set(files),'CSV published file inventory differs'
    assert sum(item['bytes'] for item in files.values())==bounded['total_compressed_bytes']
    assert max(item['bytes'] for item in files.values())==bounded['maximum_compressed_bytes']<20*1024*1024
    assert rdf['public_navigation']=={key:value for key,value in bounded.items() if key!='files'}
    expected_hashes={name:entry['sha256'] for name,entry in files.items()}
    csv_class_hashes={'classes/'+name+'.json.gz':sha for name,sha in navigation['shard_sha256'].items() if name.startswith('csv_')}
    assert csv_class_hashes=={name:sha for name,sha in expected_hashes.items() if name.startswith('classes/')}
    assert navigation['detail_sha256']=={name:sha for name,sha in expected_hashes.items() if name.startswith('details/')}
    assert navigation['relation_sha256']=={name:sha for name,sha in expected_hashes.items() if name.startswith('relations/')}
    assert navigation['detail_file_count']==bounded['detail_chunks'] and navigation['detail_instances_checked']==153862
    assert navigation['relation_file_count']==bounded['relation_chunks']
    assert activation['contract']=='csv-navigation-activation/1' and activation['status']=='passed'
    assert activation['package_sha256']==CSV_PACKAGE and activation['graph_iri']==rdf['graph_iri']
    assert activation['prior_manifest_sha256']==LEGACY_MANIFEST_SHA256
    assert activation['published_data_files']==len(files) and activation['published_compressed_bytes']==bounded['total_compressed_bytes']
    assert activation['old_class_shards_rewritten'] is False and activation['manifest_activated_last'] is True
    assert activation['counts']==manifest['counts'] and activation['formal_adoption'] is False
    assert manifest['active_csv_batch']==CSV_PACKAGE and len(manifest['csv_batches'])==1
    batch=manifest['csv_batches'][0]
    assert batch['package_sha256']==CSV_PACKAGE and batch['graph_iri']==rdf['graph_iri']
    assert batch['termset_sha256']==rdf['termset_sha256'] and batch['instances']==153862
    assert batch['source_tables']==66 and batch['schema_fields']==1397 and batch['relations']==810934
    assert batch['formal_adoption'] is False and batch['raw_payload_public'] is False
    if not pending_browser:
        browser=_load(review/'csv-browser-report.json')
        assert browser['contract']=='fish-csv-browser-readback/1' and browser['status']=='passed'
        assert browser['javascript_errors']==[] and browser['database_writes'] is False
        browser_keys=('hierarchy_and_summary_only','exact_detail_and_properties','source_provenance',
            'relation_navigation_back_and_cache','chunk_boundary_400_to_401','final_page',
            'csv_rdf_snapshot_pagination','legacy_map_object_and_relations','mobile_csv_no_overflow')
        assert all(browser['checks'].get(key) for key in browser_keys)
        maps=_load(review/'data/map-features.json')
        expected_layers=[{'id':layer['id'],'features':len(layer['features'])} for layer in maps['layers']]
        assert len(expected_layers)==6 and browser['checks']['legacy_map_layers']==expected_layers
        assert browser['data_nature']['field_acceptance'] is False and browser['screenshots']
        for image in browser['screenshots']:
            assert re.fullmatch(r'screenshots/[a-z0-9-]+\.png',image) and (review/image).is_file()
    return shacl,rdf


def ontology_check(root=ROOT,*,pending_browser=False):
    """Check shipped evidence/snapshots; do not claim a fresh live-service run."""
    from verify_fish_rdf_navigation import verify
    from rdflib import Graph, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, OWL

    directory=root/'docs/fish/ontology-review'
    required=('README.md','index.html','assets.css','assets.js','model.mjs','model.test.mjs',
        'data/manifest.json','data/map-features.json','rdf-readback.json','shacl-readback.json',
        'navigation-readback.json','vocabulary.ttl','shapes.ttl','live-api-readback.json',
        'browser-report.json','independent-review.json')
    if not pending_browser:required+=('csv-browser-report.json',)
    for name in required:assert (directory/name).is_file(),f'Missing ontology review entry: {name}'
    manifest=_load(directory/'data/manifest.json')
    report=_load(directory/'rdf-readback.json')
    shacl=_load(directory/'shacl-readback.json')
    stored=_load(directory/'navigation-readback.json')
    browser=_load(directory/'browser-report.json')
    independent=_load(directory/'independent-review.json')
    live=_load(directory/'live-api-readback.json')
    assert manifest['contract']=='fish-rdf-review/1'
    assert browser['status']==independent['status']==live['status']=='passed'
    assert browser['javascript_errors']==[]
    assert live['triple_count']==2720969 and live['database_mutations']==0
    assert independent['unresolved_critical_findings']==independent['unresolved_important_findings']==0
    for image in browser['screenshots']:
        assert re.fullmatch(r'screenshots/[a-z0-9-]+\.png',image) and (directory/image).is_file()
    assert (root/'scripts/check_ontology_review_browser.mjs').is_file()
    assert manifest['jena_verified'] is True and manifest['fuseki_readback'] is True
    assert manifest['formal_adoption'] is False and report['formal_adoption'] is False
    legacy_graphs=manifest['legacy_graphs'];legacy=manifest['legacy_counts']
    assert len(legacy_graphs)==len(set(legacy_graphs))==4
    for family in ('sample','map','demo','drawing'):
        assert sum(graph.startswith(f'urn:lzo:fish-review:{family}:v1:graph:') for graph in legacy_graphs)==1
    expected={'instances':27135,'relations':79069,'resolved_relations':79002,'classes':112,
        'source_classes':84,'triples':2720969,'map_objects':284,'map_layers':6,
        'demo_assignments':10495,'demo_activity_links':10475,'demo_profile_links':20,
        'drawing_instances':6297,'drawing_measurements':3202,'drawing_relations':10279,'drawing_map_bridges':163}
    for name,value in expected.items():assert legacy[name]==value,f'Legacy ontology count differs: {name}'
    merged=dict(expected,instances=180997,relations=890003,resolved_relations=889893,
                classes=178,source_classes=150,triples=24054860,csv_instances=153862,csv_rows=153862,csv_tables=66,csv_fields=1397)
    for name,value in merged.items():assert manifest['counts'][name]==value,f'Merged ontology count differs: {name}'
    assert len(manifest['concepts'])==178 and len(manifest['rdf_graphs'])==len(set(manifest['rdf_graphs']))==5
    assert report['navigation']==legacy and report['rdf_graphs']==legacy_graphs==live['graphs']
    assert report['status']==stored['status']==shacl['status']=='passed'
    assert stored['rdf_graphs']==manifest['rdf_graphs']
    graph_checks=[report,report['map_and_demo']['map'],report['map_and_demo']['demo'],report['drawing']]
    assert {item['graph_iri'] for item in graph_checks}==set(legacy_graphs)
    assert sum(item['triple_count'] for item in graph_checks)==expected['triples']
    for item in graph_checks:
        assert item['all_triples_readback']=='passed' and item['unexpected_or_missing_triples']==0
        assert item['preexisting_graphs_unchanged'] is True
        assert item['sparql'].get('missing_inverse',0)==item['sparql'].get('orphan_targets',0)==0
    assert report['drawing']['sparql']['evidence_bridges']==163 and report['drawing']['sparql']['measurements']==3202
    assert report['raw_payload_public'] is False and report['raw_retained_in_local_rdf'] is True
    assert shacl['instances_validated']==20548 and shacl['datatype_constraints']==1354 and shacl['violations']==0
    assert len(shacl['classes'])==64 and sum(item['instances'] for item in shacl['classes'])==20548
    assert all(item['conforms'] is True and item['violations']==0 for item in shacl['classes'])
    assert report['shacl']['status']=='passed' and report['shacl']['violations']==0
    assert _sha(directory/'data/map-features.json')==LEGACY_MAP_SHA256
    assert set(report['public_shards']['by_table'])==set(LEGACY_SHARD_SHA256)
    legacy_sizes=[]
    for table,sha in LEGACY_SHARD_SHA256.items():
        path=directory/'data/classes'/(table+'.json.gz')
        assert _sha(path)==sha,f'Legacy class shard changed: {table}'
        assert path.stat().st_size==report['public_shards']['by_table'][table]['compressed']
        legacy_sizes.append(path.stat().st_size)
    assert report['public_shards']['files']==84
    assert sum(legacy_sizes)==report['public_shards']['total_compressed_bytes']
    assert max(legacy_sizes)==report['public_shards']['maximum_compressed_bytes']
    # The verifier writes only its report. Its complete data tree is copied to
    # temporary storage so repository checks cannot alter published evidence.
    with tempfile.TemporaryDirectory(prefix='ontology-repository-check-') as temporary:
        target=Path(temporary)
        shutil.copytree(directory/'data',target/'data')
        with redirect_stdout(io.StringIO()):actual=verify(target)
    for name,value in actual.items():
        if name!='checked_at':assert stored.get(name)==value,f'Stored navigation evidence differs: {name}'
    assert actual['instances_checked']==180997 and actual['concepts_checked']==178
    assert actual['shard_count']==150 and actual['dangling_links']==actual['type_mismatches']==0
    assert actual['resolved_links_checked_both_directions']==889893 and actual['unresolved_records_preserved']==110
    assert actual['demo_links_checked_both_directions']==10495 and actual['maximum_compressed_bytes']<20*1024*1024
    assert {table:sha for table,sha in actual['shard_sha256'].items() if not table.startswith('csv_')}==LEGACY_SHARD_SHA256
    csv_shacl,csv_rdf=csv_check(root,manifest,actual,legacy_graphs,pending_browser=pending_browser)
    assert set(manifest['rdf_graphs'])==set(legacy_graphs)|{csv_rdf['graph_iri']}
    vocabulary=Graph().parse(directory/'vocabulary.ttl',format='turtle')
    shapes=Graph().parse(directory/'shapes.ttl',format='turtle')
    sh=Namespace('http://www.w3.org/ns/shacl#')
    for concept in manifest['concepts']:
        subject=URIRef(concept['iri'])
        assert (subject,RDF.type,OWL.Class) in vocabulary,f'Undeclared ontology class: {subject}'
        if concept['parent_iri']:assert (subject,RDFS.subClassOf,URIRef(concept['parent_iri'])) in vocabulary
    assert {str(subject) for subject in vocabulary.transitive_subjects(RDFS.subClassOf,URIRef(manifest['root_iri']))}=={c['iri'] for c in manifest['concepts']}
    assert len(set(shapes.subjects(RDF.type,sh.NodeShape)))==130
    assert len(list(shapes.triples((None,sh.datatype,None))))==2751==shacl['datatype_constraints']+csv_shacl['datatype_constraints']
    assert len(list(shapes.triples((None,sh['class'],None))))==shacl['relation_class_constraints']+csv_shacl['relation_class_constraints']
    assert {str(value) for value in shapes.objects(None,sh.targetClass)}=={item['class_iri'] for item in shacl['classes']+csv_shacl['classes']}
    assert len(list((directory/'data/classes').glob('*.json.gz')))==150
    for name in ('index.html','assets.js','model.mjs'):
        content=(directory/name).read_text(encoding='utf-8')
        targets=re.findall(r'''(?:src|href)=["']([^"']+)["']''',content) if name.endswith('.html') else []
        targets+=re.findall(r'''from\s+["'](\./[^"']+)["']''',content)
        targets+=re.findall(r'''(?:json|fetch)\(["'](data/[^"']+\.(?:json|svg))["']\)''',content)
        for link in targets:
            if link.startswith(('#','https:','http:')):continue
            path=(directory/link.split('#')[0]).resolve()
            assert path.is_relative_to(directory.resolve()) and path.is_file(),f'Broken ontology UI reference: {link}'
    for document in (root.parent/'README.md',root/'README.md'):
        assert 'docs/fish/ontology-review/' in document.read_text(encoding='utf-8'),f'Missing current RDF entry: {document.name}'
    assert 'serve_ontology_review.py' in (directory/'README.md').read_text(encoding='utf-8')
    return {'named_graphs':5,'concepts':178,'instances':180997,'gzip_shards':150,
        'source_links_verified':889893,'demo_links_verified':10495,'csv_rows':153862,'live_services_contacted':False}


def check(*,pending_browser=False):
    if not __debug__:raise ValueError('Repository checks require assertions enabled; do not use -O')
    repository=ROOT.parent
    files=['README.md','ontology-platform/README.md','ontology-platform/config/fish-review.example.json',
        'ontology-platform/scripts/requirements-fish-review.txt','ontology-platform/scripts/build_fish_review_sample.py',
        'ontology-platform/scripts/verify_fish_review_sample.py','ontology-platform/docs/fish/review-sample/README.md',
        'ontology-platform/docs/fish/review-sample/index.html','ontology-platform/docs/fish/review-sample/readback.json',
        'ontology-platform/docs/fish/review-sample/schema.sql','ontology-platform/docs/fish/review-sample/preview.png']
    for path in files:assert (repository/path).is_file(),f'Missing published entry: {path}'
    readme=(repository/'README.md').read_text(encoding='utf-8')
    assert 'lianggeming14/liangzihu-ontology-traceability' in readme
    for target in re.findall(r'\]\(([^)]+)\)',readme):
        if target.startswith(('https:','http:','#')):continue
        assert (repository/target.split('#')[0]).is_file(),f'Broken root README link: {target}'
    report=json.loads((ROOT/'docs/fish/review-sample/readback.json').read_text(encoding='utf-8'))
    assert report['seed_rows']==(report['full_input_rows']+9)//10
    assert report['seed_rows']+report['dependency_rows']==report['total_sample_rows']
    assert len(report['tables'])==report['business_tables']==64
    assert sum(len(t['columns']) for t in report['tables'])==report['schema_fields']==1346
    assert sum(t['raw_rows'] for t in report['tables'])==report['total_sample_rows']
    checks=report['checks']
    assert checks['raw_field_mismatches']==checks['invalid_gis_geometries']==checks['resolved_edges_without_target']==0
    assert checks['independent_source_readback']==checks['independent_typed_readback']=='passed'
    assert sum(checks['graph_node_roles'].values())==checks['ontology_nodes']
    assert len(report['ponds'])==6 and checks['gis_features']==126
    page=(ROOT/'docs/fish/review-sample/index.html').read_text(encoding='utf-8')
    assert '__REVIEW_DATA__' not in page
    ddl=(ROOT/'docs/fish/review-sample/schema.sql').read_text(encoding='utf-8')
    assert len(re.findall(r'CREATE TABLE ',ddl))==70
    assert 'ADD COLUMN geom geometry(Geometry,4326)' in ddl
    config=json.loads((ROOT/'config/fish-review.example.json').read_text(encoding='utf-8'))
    serialized=json.dumps(config).lower()
    assert not any(word in serialized for word in ('postgresql://','postgresql+psycopg://','password','access_token'))
    assert not list(repository.glob('snapshot-*.zip')),'Obsolete snapshot transports remain'
    for name in ('.document-build','.document-build-v1.1'):
        assert not list((repository/name).glob('contact-*.png'))
        assert not list((repository/name).glob('preview-pages/*.png'))
    cleanup=json.loads((ROOT/'docs/operations/repository-cleanup.json').read_text(encoding='utf-8'))
    for item in cleanup['remove']:
        assert not (repository/item['path']).exists(),f"Reviewed removal still present: {item['path']}"
    ontology=ontology_check(pending_browser=pending_browser)
    print(json.dumps({'status':'pending_browser' if pending_browser else 'passed',
        'csv_browser_evidence_checked':not pending_browser,'published_entries':len(files),'business_tables':64,'source_fields':1346,
        'sample_total':report['total_sample_rows'],'database_connections':0,'ontology':ontology,
        'verification_scope':'published artifacts and offline tests; existing service evidence is not rerun in CI'},ensure_ascii=False))


if __name__=='__main__':check()
