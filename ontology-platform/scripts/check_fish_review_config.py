"""Run sample CLI safety checks without connecting to a database."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from fish_review_config import SCHEMA, load_config, database_url, require_empty_schema
from prepare_fish_review_source import safe_member
import prepare_fish_review_source as preparation


class ReviewConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.value = {
            'contract': 'fish-review-config/1',
            'source_archive': '.runtime/source/source.zip',
            'extracted_root': '.runtime/source/extracted/output',
            'source_manifest': '.runtime/source/source-manifest.json',
            'env_file': '.runtime/services.env',
            'review_schema': SCHEMA,
            'output_dir': '.runtime/review-output',
        }

    def read(self):
        self.config.write_text(json.dumps(self.value), encoding='utf-8')
        return load_config(self.config, root=self.root)

    def test_plan_configuration_does_not_read_private_environment(self):
        config = self.read()
        self.assertFalse(config.env_file.exists())
        self.assertEqual(config.extracted_root, self.root / self.value['extracted_root'])

    def test_credentials_and_unknown_config_keys_rejected(self):
        for key in ('password', 'database_url', 'token', 'ownership'):
            with self.subTest(key=key):
                self.value[key] = 'not-a-real-secret'
                with self.assertRaises(ValueError):
                    self.read()
                del self.value[key]

    def test_other_schema_and_public_env_path_rejected(self):
        self.value['review_schema'] = 'public'
        with self.assertRaises(ValueError):
            self.read()
        self.value['review_schema'] = SCHEMA
        self.value['env_file'] = 'config/services.env'
        with self.assertRaises(ValueError):
            self.read()

    def test_archive_must_be_verified_manifest_sibling(self):
        self.value['source_archive'] = '.runtime/elsewhere/source.zip'
        with self.assertRaises(ValueError):
            self.read()

    def test_target_uses_only_explicit_private_env(self):
        config = self.read()
        config.env_file.parent.mkdir(parents=True)
        good = 'postgresql+psycopg://lzo_gis_owner:fixture@127.0.0.1:25449/lzo_gis'
        config.env_file.write_text('APP_ENV=test\nLZO_GIS_MIGRATION_DATABASE_URL=' + good + '\n')
        with patch.dict('os.environ', {'LZO_GIS_MIGRATION_DATABASE_URL': 'unsafe', 'APP_ENV': 'production'}):
            self.assertEqual(str(database_url(config)), good)

    def test_non_test_remote_other_owner_and_query_redirection_rejected(self):
        config = self.read()
        config.env_file.parent.mkdir(parents=True)
        good = 'postgresql+psycopg://lzo_gis_owner:fixture@127.0.0.1:25449/lzo_gis'
        for env, url in [('production', good), ('test', good.replace('127.0.0.1', 'db.example')),
                ('test', good.replace('lzo_gis_owner', 'postgres')),
                ('test', good.replace('/lzo_gis', '/production')),
                ('test', good + '?host=db.example')]:
            with self.subTest(env=env, url=url):
                config.env_file.write_text('APP_ENV=' + env + '\nLZO_GIS_MIGRATION_DATABASE_URL=' + url + '\n')
                with self.assertRaises(ValueError):
                    database_url(config)

    def test_existing_schema_refused_without_ddl(self):
        from unittest.mock import Mock
        connection = Mock()
        connection.execute.return_value.scalar_one.return_value = SCHEMA
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            require_empty_schema(connection)
        self.assertEqual(connection.execute.call_count, 1)
        self.assertIn('to_regnamespace', str(connection.execute.call_args.args[0]))

    def test_archive_member_paths_are_relative_canonical_and_bounded(self):
        self.assertEqual(str(safe_member('output/schemas/schema.json')), 'output/schemas/schema.json')
        for name in ('../outside', '/root/escape', 'C:/outside', 'output\\escape',
                     'output/../escape', 'output//hidden', './output/file', 'other/file'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_member(name)

    def source_fixture(self):
        config=self.read()
        config.source_archive.parent.mkdir(parents=True)
        content=b'{"fixture":true}'
        name='output/schemas/schema.json'
        with zipfile.ZipFile(config.source_archive,'w') as archive:
            archive.writestr(name,content)
        data=config.source_archive.read_bytes()
        sha=hashlib.sha256(data).hexdigest()
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        manifest={'archive_sha256':sha,'archive_git_blob':blob,'archive_bytes':len(data),
            'members':[{'path':name,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}]}
        reviewed=self.root/'datasets/fish/source-manifest.json'
        reviewed.parent.mkdir(parents=True)
        reviewed.write_text(json.dumps(manifest),encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.object(preparation,'ROOT',self.root).start()
        patch.object(preparation,'PINNED_SHA',sha).start()
        patch.object(preparation,'PINNED_BLOB',blob).start()
        return config

    def test_source_preparation_is_verified_and_idempotent(self):
        config=self.source_fixture()
        self.assertEqual(preparation.prepare_source(config)['status'],'prepared')
        self.assertEqual(preparation.prepare_source(config)['status'],'verified_existing')
        self.assertTrue(config.source_manifest.is_file())

    def test_source_preparation_never_overwrites_mismatched_extraction(self):
        config=self.source_fixture()
        preparation.prepare_source(config)
        path=config.extracted_root/'schemas/schema.json'
        path.write_bytes(b'changed fixture')
        with self.assertRaisesRegex(ValueError,'refusing overwrite'):
            preparation.prepare_source(config)
        self.assertEqual(path.read_bytes(),b'changed fixture')

    def test_bad_archive_is_rejected_before_any_extraction(self):
        config=self.source_fixture()
        config.source_archive.write_bytes(b'wrong archive')
        with self.assertRaisesRegex(ValueError,'pinned SHA256'):
            preparation.prepare_source(config)
        self.assertFalse(config.extracted_root.exists())
        self.assertFalse(config.source_manifest.exists())


if __name__ == '__main__':
    unittest.main()
