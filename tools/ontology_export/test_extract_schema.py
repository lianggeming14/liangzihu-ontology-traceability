"""Conservative parser behavior and source-span audit; no SQL is executed."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from extract_schema import Extractor,lex,statements


def catalog(sql):
    parser=Extractor();parser.file_sql=sql;parser.file_path='db/migrations/001_test.sql'
    for part in statements(lex(sql)):parser.process_statement(part)
    return parser.finalize()

def table(result,name):return next(t for t in result['tables'] if t['qualified_name']==name)
def col(result,tab,name):return next(c for c in table(result,tab)['columns'] if c['name']==name)


def test_quoted_function_body_comments_and_defaults_do_not_become_ddl():
    result=catalog("""-- CREATE TABLE ignored(x int);
    CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$
    BEGIN PERFORM 'CREATE TABLE ignored2(x int);'; END; $$;
    /* outer /* nested ; */ CREATE TABLE fake(x int); */
    CREATE TABLE real_data(id uuid PRIMARY KEY, note text DEFAULT 'a,b;CREATE TABLE x', amount numeric(12,3) NOT NULL);
    """)
    assert result['counts']['tables']==1 and result['counts']['columns']==3
    assert result['counts']['table_ddl_statements']==1
    assert col(result,'real_data','note')['default']=="'a,b;CREATE TABLE x'"
    assert col(result,'real_data','id')['nullable'] is False
    assert col(result,'real_data','amount')['sql_type']=='numeric(12,3)'
    assert not result['unparsed_ddl']


def test_inline_composite_fk_options_and_not_valid_constraints():
    result=catalog("""CREATE TABLE parents(a uuid PRIMARY KEY,b integer,UNIQUE(a,b));
CREATE TABLE children(id uuid PRIMARY KEY,p uuid DEFAULT NULL REFERENCES parents(a) ON DELETE SET DEFAULT NOT NULL,q integer,
CONSTRAINT compound FOREIGN KEY(p,q) REFERENCES parents(a,b) ON UPDATE CASCADE NOT VALID);
ALTER TABLE children VALIDATE CONSTRAINT compound;
""")
    fks=table(result,'children')['foreign_keys']
    assert fks[0]['on_delete']=='SET DEFAULT'
    assert col(result,'children','p')['nullable'] is False
    assert fks[1]['columns']==['p','q'] and fks[1]['referenced_columns']==['a','b']
    assert fks[1]['on_update']=='CASCADE' and fks[1]['not_valid'] is False
    assert not result['unparsed_ddl']


def test_add_drop_rename_type_default_and_nullability_are_applied_in_order():
    result=catalog("""CREATE TABLE sample(id uuid PRIMARY KEY,state text NOT NULL CHECK(state IN('old','new')));
CREATE UNIQUE INDEX sample_state_unique ON sample(state);
ALTER TABLE sample ADD COLUMN n numeric(10,2) DEFAULT 0, ADD COLUMN temp text;
ALTER TABLE sample ALTER COLUMN n TYPE double precision USING n::double precision;
ALTER TABLE sample ALTER COLUMN n SET NOT NULL, ALTER COLUMN state DROP NOT NULL;
ALTER TABLE sample ALTER COLUMN n SET DEFAULT 4, ALTER COLUMN n DROP DEFAULT;
ALTER TABLE sample RENAME COLUMN state TO phase;
ALTER TABLE sample DROP COLUMN temp;
""")
    assert not result['unparsed_ddl']
    assert col(result,'sample','phase')['enum_values']==['old','new']
    assert col(result,'sample','phase')['unique'] is True
    assert col(result,'sample','phase')['nullable'] is True
    assert col(result,'sample','n')['sql_type']=='double precision'
    assert col(result,'sample','n')['default'] is None and col(result,'sample','n')['nullable'] is False
    assert table(result,'sample')['dropped_columns'][0]['name']=='temp'
    assert result['counts']['table_ddl_statements']==7


def test_drop_auto_named_check_then_add_explicit_replacement_updates_enum():
    result=catalog("""CREATE TABLE image_reviews(id uuid PRIMARY KEY,state text CHECK(state IN('queued','done')));
ALTER TABLE image_reviews DROP CONSTRAINT image_reviews_state_check;
ALTER TABLE image_reviews ADD CONSTRAINT image_reviews_state_check CHECK(state IN('queued','running','complete'));
""")
    assert col(result,'image_reviews','state')['enum_values']==['queued','running','complete']
    assert len([c for c in table(result,'image_reviews')['constraints'] if c['kind']=='check'])==1


def test_create_enum_add_and_rename_values():
    result=catalog("""CREATE TYPE job_state AS ENUM ('queued','done');
ALTER TYPE job_state ADD VALUE 'running' BEFORE 'done';
ALTER TYPE job_state RENAME VALUE 'done' TO 'complete';
CREATE TABLE jobs(id integer PRIMARY KEY,state job_state NOT NULL);
""")
    assert not result['unparsed_ddl']
    assert col(result,'jobs','state')['enum_values']==['queued','running','complete']
    assert col(result,'jobs','state')['enum_origin']=='CREATE TYPE'


def test_unknown_and_missing_ddl_remain_in_audit():
    result=catalog("""CREATE TABLE things(id integer PRIMARY KEY);
ALTER TABLE things SET SCHEMA other;
ALTER TABLE missing ADD COLUMN foo text;
""")
    assert len(result['unparsed_ddl'])==2
    assert result['counts']['table_ddl_statements']==3
    assert result['coverage']['all_structural_ddl_parsed'] is False
    assert any('SET SCHEMA' in x['sql'] for x in result['unparsed_ddl'])


def test_source_line_url_and_conditional_check_not_falsely_enum():
    result=catalog("""-- first line
CREATE TABLE objects(
 id uuid PRIMARY KEY,
 kind text CHECK(kind IN ('farm','field')),
 parent_id uuid REFERENCES objects(id),
 CHECK(parent_id IS NOT NULL OR kind='farm')
);
""")
    assert col(result,'objects','kind')['enum_values']==['farm','field']
    source=col(result,'objects','kind')['source']
    assert source['line']==4 and source['url'].endswith('/001_test.sql#L4')
    assert result['coverage']['all_references_resolved'] is True


def test_partial_unique_index_is_not_global_unique():
    result=catalog("""CREATE TABLE claims(id uuid PRIMARY KEY,actor_id uuid,ended_at timestamptz);
CREATE UNIQUE INDEX active_claim ON claims(actor_id) WHERE ended_at IS NULL;
""")
    assert col(result,'claims','actor_id')['unique'] is False
    assert table(result,'claims')['indexes'][0]['where']=='ended_at IS NULL'


def test_if_exists_guards_and_drop_index_preserve_current_state():
    result=catalog("""CREATE TABLE t(id integer PRIMARY KEY,label text);
CREATE TABLE IF NOT EXISTS t(id integer);
ALTER TABLE t ADD COLUMN IF NOT EXISTS label text;
ALTER TABLE t DROP COLUMN IF EXISTS missing;
CREATE UNIQUE INDEX label_unique ON t(label);
DROP INDEX label_unique;
""")
    assert not result['unparsed_ddl']
    assert len(table(result,'t')['columns'])==2
    assert col(result,'t','label')['unique'] is False
    assert len(result['dropped_indexes'])==1


def test_schema_qualified_identifiers_and_cross_table_rename():
    result=catalog('CREATE TABLE public."Mixed"("Id" uuid PRIMARY KEY); CREATE TABLE child(parent uuid REFERENCES public."Mixed"("Id")); ALTER TABLE public."Mixed" RENAME COLUMN "Id" TO key; ALTER TABLE public."Mixed" RENAME TO renamed;')
    fk=table(result,'child')['foreign_keys'][0]
    assert fk['referenced_table']=='public.renamed' and fk['referenced_columns']==['key']
    assert not result['unparsed_ddl'] and not result['unresolved_references']


def test_array_geometry_and_vector_types_remain_exact_not_text():
    result=catalog('CREATE TABLE shapes(id uuid PRIMARY KEY,boundary geometry(Geometry,4326),refs uuid[] NOT NULL,embedding public.vector(512),data jsonb DEFAULT \'{}\');')
    assert [c['sql_type'] for c in table(result,'shapes')['columns']]==['uuid','geometry(Geometry,4326)','uuid[]','public.vector(512)','jsonb']
    assert len(table(result,'shapes')['foreign_keys'])==0
