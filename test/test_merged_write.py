"""Regression tests for the optional merged.json output in get_Astocks_data.py."""
import importlib.util
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    import pandas as pd
except ImportError:  # pragma: no cover - run under the project's diaistock env
    pd = None


PROJECT = Path(__file__).resolve().parents[1]


def load_handler_module():
    spec = importlib.util.spec_from_file_location(
        'astocks_downloader', PROJECT / 'data' / 'get_Astocks_data.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(pd is None, 'pandas is required for the save() test')
class MergedWriteTests(unittest.TestCase):
    def setUp(self):
        self.module = load_handler_module()
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / 'test')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'stocks').mkdir(parents=True)
        self.constants = {
            'DATA_DIR': root,
            'STOCKS_DIR': root / 'stocks',
            'DAILY_DIR': root / 'daily',
            'MERGED_FILE': root / 'merged.json',
            'META_FILE': root / 'meta.json',
            'DATES_FILE': root / 'dates.json',
            'LATEST_FILE': root / 'latest.json',
        }
        patch.multiple(self.module, **self.constants).start()
        self.addCleanup(patch.stopall)
        self.handler = self.module.AstocksHandler.__new__(self.module.AstocksHandler)
        self.handler.start_date = '20261020'
        self.handler.end_date = '20261020'
        self.root = Path(self.temp.name)

    def frame(self):
        return pd.DataFrame([{
            'ts_code': '000001.SZ', 'trade_date': '20261020',
            'close': 10.0, 'vol': 100.0, 'amount': 1000.0,
        }])

    def test_default_skips_merged_but_writes_meta(self):
        with redirect_stdout(io.StringIO()):
            self.handler.save(self.frame(), ['000001.SZ'], {'000001.SZ': '平安银行'})
        self.assertFalse((self.root / 'merged.json').exists())
        meta = json.loads((self.root / 'meta.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['symbols'], ['000001.SZ'])
        self.assertEqual(meta['name_map']['000001.SZ'], '平安银行')
        self.assertEqual(meta['stock_count'], 1)

    def test_opt_in_writes_merged(self):
        self.handler.write_merged = True
        with redirect_stdout(io.StringIO()):
            self.handler.save(self.frame(), ['000001.SZ'], {'000001.SZ': '平安银行'})
        merged = json.loads((self.root / 'merged.json').read_text(encoding='utf-8'))
        self.assertEqual(merged['names']['000001.SZ'], '平安银行')
        self.assertIn('000001.SZ', merged['data'])


if __name__ == '__main__':
    unittest.main()
