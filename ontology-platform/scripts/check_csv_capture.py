import importlib.util
from pathlib import Path
import tempfile
import unittest


class CaptureTests(unittest.TestCase):
    def test_capture_destination_cannot_replace_evidence_or_leave_private_runtime(self):
        self.assertIsNotNone(importlib.util.find_spec('capture_csv_prior_graphs'),'Reproducible baseline capture is not implemented')
        from capture_csv_prior_graphs import capture_destination
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);destination=root/'.runtime/new-baseline'
            self.assertEqual(capture_destination(destination,root=root),destination.resolve())
            for path in (root/'docs/baseline',root/'.runtime'):
                with self.assertRaises(ValueError):capture_destination(path,root=root)
            destination.mkdir(parents=True);(destination/'report.json').write_text('{}')
            with self.assertRaises(ValueError):capture_destination(destination,root=root)


if __name__=='__main__':unittest.main()
