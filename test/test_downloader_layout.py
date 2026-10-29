"""Offline downloader output tests; market APIs and optional dependencies are stubbed."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


PROJECT = Path(__file__).resolve().parents[1]


def load_downloader(filename):
    spec = importlib.util.spec_from_file_location(filename[:-3], PROJECT / 'data' / filename)
    module = importlib.util.module_from_spec(spec)
    # Loading the production modules must not need credentials, pandas or network.
    dependencies = {
        'pandas': SimpleNamespace(DataFrame=object),
        'tushare': SimpleNamespace(pro_api=MagicMock()),
        'dotenv': SimpleNamespace(load_dotenv=lambda: None),
    }
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


astocks = load_downloader('get_Astocks_data.py')
etfs = load_downloader('get_etf_data.py')
us = load_downloader('get_us_market_data.py')


class DownloaderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / 'test')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def read_json(self, name):
        return json.loads((self.root / name).read_text(encoding='utf-8'))

    def seed(self):
        for symbol, dates in [('ONE', ['20261019', '20261020']), ('HALTED', ['20261019'])]:
            self.write_json(self.root / 'stocks' / f'{symbol}.json', {
                'ts_code': symbol, 'name': f'{symbol} name',
                'records': [{'ts_code': symbol, 'trade_date': day, 'close': 10} for day in dates],
            })

    def assert_metadata(self):
        self.assertEqual(self.read_json('dates.json')['dates'], ['20261019', '20261020'])
        latest = self.read_json('latest.json')
        self.assertEqual(latest['date'], '20261020')
        self.assertEqual([row['ts_code'] for row in latest['data']], ['ONE'])
        self.assertEqual(latest['data'][0]['name'], 'ONE name')

    def run_layout(self, market, write_daily=False):
        if market == 'astocks':
            with patch.multiple(astocks, DATA_DIR=self.root, STOCKS_DIR=self.root / 'stocks',
                                DAILY_DIR=self.root / 'daily', DATES_FILE=self.root / 'dates.json',
                                LATEST_FILE=self.root / 'latest.json'):
                handler = astocks.AstocksHandler.__new__(astocks.AstocksHandler)
                handler.build_frontend_partitions(write_daily=write_daily)
        elif market == 'usstocks':
            us.rebuild_layout(self.root, write_daily=write_daily)
        else:
            self.run_etf(write_daily)

    def run_etf(self, write_daily):
        # One new day for ONE; HALTED is not downloaded but must remain in indexes.
        fund = MagicMock(ts_code='ONE')
        fund.get.return_value = 'ONE name'
        funds = MagicMock(empty=False)
        funds.drop_duplicates.return_value = funds
        funds.sort_values.return_value = funds
        funds.iterrows.return_value = [(0, fund)]
        funds.__len__.return_value = 1
        incoming = MagicMock(empty=False)
        incoming.sort_values.return_value = incoming
        incoming.to_dict.return_value = [{'ts_code': 'ONE', 'trade_date': '20261020', 'close': 11}]
        pro = MagicMock()
        pro.fund_basic.return_value = funds
        pro.fund_daily.return_value = incoming
        # Remove the last day to exercise actual incremental merge and request bounds.
        old = json.loads((self.root / 'stocks' / 'ONE.json').read_text(encoding='utf-8'))
        old['records'] = old['records'][:1]
        self.write_json(self.root / 'stocks' / 'ONE.json', old)
        argv = ['get_etf_data.py', '--token', 'offline-test', '--end', '20261020']
        if write_daily:
            argv.append('--write-daily')
        with patch.multiple(etfs, DATA_DIR=self.root, STOCKS_DIR=self.root / 'stocks',
                            DAILY_DIR=self.root / 'daily'), \
                patch.object(etfs.ts, 'pro_api', return_value=pro), \
                patch.object(etfs, 'fetch_etf_share', return_value={}), \
                patch.object(etfs, 'enrich_records', side_effect=lambda rows: rows), \
                patch.object(sys, 'argv', argv):
            etfs.main()
        self.assertEqual(pro.fund_daily.call_args.kwargs['start_date'], '20261020')
        self.assertEqual(len(self.read_json('stocks/ONE.json')['records']), 2)

    def check_layout(self, market, mode):
        self.seed()
        sentinel = self.root / 'daily' / '20261019.json'
        if mode == 'existing':
            sentinel.parent.mkdir()
            sentinel.write_bytes(b'legacy data must remain untouched')
            original_stat = sentinel.stat()
        with redirect_stdout(io.StringIO()):
            self.run_layout(market, write_daily=mode == 'opt_in')
        self.assert_metadata()
        if mode == 'fresh':
            self.assertFalse((self.root / 'daily').exists())
            self.assertFalse((self.root / '.daily_build').exists())
        elif mode == 'existing':
            self.assertEqual(sentinel.read_bytes(), b'legacy data must remain untouched')
            self.assertEqual(sentinel.stat().st_mtime_ns, original_stat.st_mtime_ns)
            self.assertEqual(list(sentinel.parent.iterdir()), [sentinel])
        else:
            self.assertEqual(self.read_json('daily/20261020.json')['data'], self.read_json('latest.json')['data'])
            self.assertEqual({row['ts_code'] for row in self.read_json('daily/20261019.json')['data']},
                             {'ONE', 'HALTED'})

    def test_astocks_default_does_not_create_daily(self):
        self.check_layout('astocks', 'fresh')

    def test_astocks_preserves_existing_daily(self):
        self.check_layout('astocks', 'existing')

    def test_astocks_daily_opt_in(self):
        self.check_layout('astocks', 'opt_in')

    def test_etf_default_does_not_create_daily(self):
        self.check_layout('etfs', 'fresh')

    def test_etf_preserves_existing_daily(self):
        self.check_layout('etfs', 'existing')

    def test_etf_daily_opt_in(self):
        self.check_layout('etfs', 'opt_in')

    def test_us_default_does_not_create_daily(self):
        self.check_layout('usstocks', 'fresh')

    def test_us_preserves_existing_daily(self):
        self.check_layout('usstocks', 'existing')

    def test_us_daily_opt_in(self):
        self.check_layout('usstocks', 'opt_in')


if __name__ == '__main__':
    unittest.main()
