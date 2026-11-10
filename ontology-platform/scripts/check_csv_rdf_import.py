import importlib.util
from pathlib import Path
import hashlib
import tempfile
import unittest
from rdflib import URIRef,Literal
from fish_rdf_sample import triple_digest


class RDFImportTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('build_csv_rdf'),'CSV graph importer is not implemented')
        import build_csv_rdf
        return build_csv_rdf

    def test_only_pinned_batch_namespace_and_local_dataset_can_be_written(self):
        module=self.module();graph=module.NS+'graph:'+'a'*64
        module.check_target(module.ENDPOINT,graph)
        for endpoint,target in [('https://example.com/data',graph),(module.ENDPOINT,'urn:lzo:fish-review:sample:v1:graph:'+'a'*64),
                (module.ENDPOINT,graph+'> INSERT DATA {}'),('http://127.0.0.1:23049/other',graph)]:
            with self.assertRaises(ValueError):module.check_target(endpoint,target)

    def test_bounded_upload_chunks_keep_every_complete_line(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.nt';body=b'<urn:a> <urn:p> "1" .\n<urn:b> <urn:p> "2" .\n<urn:c> <urn:p> "3" .\n';path.write_bytes(body)
            pieces=list(module.nt_chunks(path,max_lines=2))
            self.assertEqual(len(pieces),2)
            self.assertEqual(b''.join(pieces),body)

    def test_readback_rejects_changed_or_repeated_terms(self):
        module=self.module();s,p=URIRef('urn:s'),URIRef('urn:p');o=Literal('1')
        expected={triple_digest(s,p,o)};sink=module.TermSink(expected)
        with self.assertRaises(ValueError):sink.triple(s,p,Literal('2'))
        sink.triple(s,p,o)
        self.assertEqual(sink.count,1);self.assertFalse(expected)
        with self.assertRaises(ValueError):sink.triple(s,p,o)

    def test_same_length_corrupted_digest_cache_is_rejected_before_graph_io(self):
        module=self.module();self.assertTrue(hasattr(module,'read_inventory'),'Digest cache checksum is not verified early')
        values=sorted([hashlib.sha256(b'a').digest(),hashlib.sha256(b'b').digest()]);body=b''.join(values)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'digests.bin';path.write_bytes(body)
            expected_sha=hashlib.sha256(body).hexdigest()
            self.assertEqual(module.read_inventory(path,2,expected_sha),set(values))
            path.write_bytes(bytes([body[0]^1])+body[1:])
            with self.assertRaises(ValueError):module.read_inventory(path,2,expected_sha)


if __name__=='__main__':unittest.main()
