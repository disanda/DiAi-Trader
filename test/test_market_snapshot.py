"""Offline regression tests for stocks-backed market APIs (no market downloads)."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'bs_server.py'
SPEC = importlib.util.spec_from_file_location('snapshot_server_test', SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class MarketSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        markets = {name: {'root': base / name} for name in ('astocks', 'etfs', 'usstocks')}
        self.market_patch = patch.dict(server.MARKETS, markets, clear=True)
        self.market_patch.start()
        self.addCleanup(self.market_patch.stop)
        for config in markets.values():
            (config['root'] / 'stocks').mkdir(parents=True)
            (config['root'] / 'symbols').mkdir()
        server.MARKET_SNAPSHOT_CACHE.clear()
        server.MARKET_FACTORS_CACHE = None
        self.handler = server.SaveHandler.__new__(server.SaveHandler)
        self.handler._json_response = self.capture
        self.handler.send_error_response = self.capture_error
        self.status, self.payload = None, None
        self.write_stock('ONE', [
            {'trade_date': '20261019', 'close': 10, 'amount': 100, 'total_mv': 10},
            {'trade_date': '20261020', 'close': 11, 'amount': 200, 'total_mv': 20},
        ])
        self.write_stock('HALTED', [
            {'trade_date': '20261019', 'close': 20, 'amount': 300, 'total_mv': 30},
        ])

    def capture(self, status, payload):
        self.status, self.payload = status, payload

    def capture_error(self, status, message):
        self.status, self.payload = status, {'error': message}

    def write_json(self, path, data):
        path.write_text(json.dumps(data), encoding='utf-8')
        # Guarantee version changes even with coarse filesystem timestamp clocks.
        old_ns = path.stat().st_mtime_ns
        os.utime(path, ns=(old_ns, old_ns + 1_000_000))
        return path

    def write_stock(self, symbol, records, market='astocks', name='Example'):
        path = server.MARKETS[market]['root'] / 'stocks' / f'{symbol}.json'
        return self.write_json(path, {'ts_code': symbol, 'name': name, 'records': records})

    def request(self, **params):
        self.handler._handle_market_snapshot({key: [value] for key, value in params.items()})
        return self.payload

    def test_latest_exact_matches_daily_membership(self):
        result = self.request()
        self.assertEqual(self.status, 200)
        self.assertEqual(result['source'], 'stocks')
        self.assertEqual(result['date'], '20261020')
        self.assertEqual([r['ts_code'] for r in result['data']], ['ONE'])
        self.assertEqual(result['dates'], ['20261019', '20261020'])
        self.assertEqual(result['stock_count'], 2)
        self.assertEqual(result['data'][0]['name'], 'Example')
        # The fixture has no daily/, meta.json, dates.json or latest.json.

    def test_historical_exact_and_absent_day(self):
        result = self.request(date='2026-10-19')
        self.assertEqual(len(result['data']), 2)
        self.assertEqual({row['trade_date'] for row in result['data']}, {'20261019'})
        result = self.request(date='20261018')
        self.assertEqual(result['data'], [])
        self.assertEqual(result['date'], '20261018')

    def test_legacy_asof_preserved(self):
        self.handler._handle_astocks_snapshot({'date': ['20261021']})
        self.assertEqual(self.status, 200)
        self.assertEqual(len(self.payload['data']), 2)
        self.assertEqual(self.payload['date'], '20261020')

    def test_unsorted_records_pick_latest_not_last(self):
        self.write_stock('ONE', [
            {'date': '2026-10-20', 'close': 11}, {'date': '2026-10-19', 'close': 10}
        ])
        self.assertEqual(self.request()['data'][0]['close'], 11)

    def test_three_markets_and_qualified_groups(self):
        for market in server.MARKETS:
            self.write_stock('LOCAL', [{'trade_date': '20261020', 'close': 3}], market)
            self.write_json(server.MARKETS[market]['root'] / 'symbols' / 'sample.json',
                            {'symbolname': 'Sample', 'symbols': ['LOCAL', 'NOT_DOWNLOADED']})
            result = self.request(market=market, group=f'{market}:sample')
            self.assertEqual([r['ts_code'] for r in result['data']], ['LOCAL'])
        self.handler._handle_astocks_snapshot({'group': ['etf:sample']})
        self.assertEqual(self.payload['market'], 'etfs')

    def test_cache_does_not_read_histories_again(self):
        first = self.request()
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected disk read')):
            self.assertEqual(self.request(), first)

    def test_cache_refreshes_on_stock_change_addition_and_removal(self):
        self.request()
        path = self.write_stock('ONE', [{'trade_date': '20261021', 'close': 12}])
        self.assertEqual(self.request()['date'], '20261021')
        new_path = self.write_stock('NEW', [{'trade_date': '20261021', 'close': 30}])
        self.assertEqual(len(self.request()['data']), 2)
        new_path.unlink()
        self.assertEqual(len(self.request()['data']), 1)
        path.unlink()
        self.assertEqual(self.request()['date'], '20261019')

    def test_cache_refreshes_on_group_edit(self):
        path = server.MARKETS['astocks']['root'] / 'symbols' / 'sample.json'
        self.write_json(path, {'symbols': ['ONE']})
        self.assertEqual(self.request(group='sample')['date'], '20261020')
        self.write_json(path, {'symbols': ['HALTED']})
        self.assertEqual(self.request(group='sample')['date'], '20261019')

    def test_cache_is_bounded(self):
        for day in range(1, 28):
            self.request(date=f'202610{day:02d}')
        self.assertLessEqual(len(server.MARKET_SNAPSHOT_CACHE), 12)

    def test_invalid_request_parameters(self):
        for params in ({'market': 'unknown'}, {'group': '../secret'},
                       {'group': '..'}, {'date': '20260230'}, {'date': 'bad'},
                       {'group': 'etfs:sample'}, {'mode': 'unknown'}):
            self.request(**params)
            self.assertEqual(self.status, 400, params)

    def test_missing_group_or_stocks(self):
        self.request(group='missing')
        self.assertEqual(self.status, 404)
        (server.MARKETS['etfs']['root'] / 'stocks').rmdir()
        self.request(market='etfs')
        self.assertEqual(self.status, 404)

    def test_corrupt_file_reported_without_breaking_snapshot(self):
        path = server.MARKETS['astocks']['root'] / 'stocks' / 'CORRUPT.json'
        path.write_text('invalid json', encoding='utf-8')
        result = self.request()
        self.assertEqual(result['skipped_files'], ['CORRUPT.json'])
        self.assertEqual(len(result['data']), 1)

    def test_factors_use_stocks_and_invalidate_cache(self):
        root = server.MARKETS['astocks']['root']
        macro = root / 'market_factors_macro.json'
        self.write_json(macro, {'20261019': {'margin_ratio': 0.25}})
        self.handler._handle_market_factors()
        first, last = self.payload['data']
        self.assertEqual(first['date'], '20261019')
        self.assertEqual(first['turnover_ratio'], 1)
        self.assertEqual(first['crowding'], 0.75)
        self.assertEqual(first['margin_ratio'], 0.25)
        self.assertEqual(last['crowding'], 1)
        self.write_stock('HALTED', [{'trade_date': '20261019', 'amount': 100, 'total_mv': 10}])
        self.handler._handle_market_factors()
        self.assertEqual(self.payload['data'][0]['crowding'], 0.5)
        self.write_json(macro, {'20261019': {'margin_ratio': 0.5}})
        self.handler._handle_market_factors()
        self.assertEqual(self.payload['data'][0]['margin_ratio'], 0.5)


if __name__ == '__main__':
    unittest.main()
