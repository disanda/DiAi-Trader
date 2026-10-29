#!/usr/bin/env python3
"""
Stock Manager Save Server
提供以下接口:
  GET  /health              健康检查
  GET  /symbol-groups       读取 A 股、ETF、美股标的组
  POST /symbol-group        新增或编辑标的组
  POST /quick-download-data 下载指定标的并生成完整市场数据结构
  GET  /load-config         读取任意 JSON 配置文件（run_agent 页面用）
  POST /save-config         保存任意 JSON 配置文件（run_agent 页面用）
  POST /run-agent           依次执行 mcp_services_start.py + main_client.py（SSE 流式输出）

使用方法:
    python docs/save_stocks_server.py
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import sys
import subprocess
import threading
import queue
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Windows terminals may use GBK and reject existing icon characters in logs.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(errors='replace')

# ── 路径常量 ────────────────────────────────────────────────
DOCS_DIR    = Path(__file__).resolve().parent          # .../DiAi--FinancialDataAgent/docs
PROJECT_DIR = DOCS_DIR.parent                          # .../DiAi--FinancialDataAgent
ASTOCKS_SYMBOLS_DIR  = PROJECT_DIR / 'data' / 'Astocks' / 'symbols'
ASTOCKS_STOCKS_DIR   = PROJECT_DIR / 'data' / 'Astocks' / 'stocks'
ASTOCKS_INDICES_DIR  = PROJECT_DIR / 'data' / 'Astocks' / 'indices'
ASTOCKS_FACTORS_DIR  = PROJECT_DIR / 'data' / 'Astocks' / 'factors'
ETFS_DATA_DIR        = PROJECT_DIR / 'data' / 'ETFs'
USSTOCKS_DATA_DIR    = PROJECT_DIR / 'data' / 'USstocks'
PREDICT_OUTPUT_DIR   = PROJECT_DIR / 'data' / 'predict'
MARKET_FACTORS_CACHE = None
SYMBOL_GROUPS_CACHE = None
SYMBOL_NAMES_CACHE = None
MARKET_SNAPSHOT_CACHE = {}
QUICK_DOWNLOAD_LOCK  = threading.Lock()
# 自定义提示词单文件路径
STRATEGY_PROMPT_FILE = PROJECT_DIR / 'agent' / 'custom_prompt' / 'trading_strategy_prompt.json'
JOURNAL_PROMPT_FILE  = PROJECT_DIR / 'agent' / 'custom_prompt' / 'daily_journal_prompt.json'
PREDICTION_STYLE_PROMPT_FILE = PROJECT_DIR / 'predict_v2' / 'prompt.json'

print(f"📍 Docs dir   : {DOCS_DIR}")
print(f"📍 Project dir: {PROJECT_DIR}")

MARKETS = {
    'astocks': {
        'label': 'A 股', 'root': PROJECT_DIR / 'data' / 'Astocks',
        'asset_type': 'Astocks', 'data_base': 'data/Astocks',
    },
    'etfs': {
        'label': 'ETF', 'root': ETFS_DATA_DIR,
        'asset_type': 'ETFs', 'data_base': 'data/ETFs',
    },
    'usstocks': {
        'label': '美股', 'root': USSTOCKS_DATA_DIR,
        'asset_type': 'USstocks', 'data_base': 'data/USstocks',
    },
}


class SaveHandler(SimpleHTTPRequestHandler):

    # ────────────────────────────────────────────────────────
    # CORS 公共头
    # ────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def send_error_response(self, code, message):
        self._json_response(code, {'success': False, 'error': message})

    # ────────────────────────────────────────────────────────
    # OPTIONS（CORS 预检）
    # ────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ────────────────────────────────────────────────────────
    # GET
    # ────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        if path == '/health':
            self._json_response(200, {'status': 'ok'})

        elif path == '/load-prompts':
            self._handle_load_prompts(params)

        elif path == '/load-config':
            # ?path=configs/astock_config_day.json
            rel = params.get('path', [None])[0]
            if not rel:
                self.send_error_response(400, 'Missing ?path= parameter')
                return
            self._handle_load_config(rel)

        elif path == '/launch-settings':
            self._handle_launch_settings()

        elif path in ('/symbol-groups', '/astocks-symbol-groups'):
            self._handle_astocks_symbol_groups()

        elif path == '/symbol-names':
            self._handle_symbol_names()

        elif path == '/astocks-snapshot':
            self._handle_astocks_snapshot(params)

        elif path == '/market-snapshot':
            self._handle_market_snapshot(params)

        elif path == '/astocks-indices':
            self._handle_astocks_indices()

        elif path == '/market-indices':
            self._handle_market_indices(params)

        elif path == '/astocks-index':
            self._handle_astocks_index(params)

        elif path == '/market-index':
            self._handle_market_index(params)

        elif path == '/astocks-factor-index':
            self._handle_astocks_factor_index(params)

        elif path == '/astocks-factor':
            self._handle_astocks_factor(params)

        elif path == '/market-factors':
            self._handle_market_factors()

        elif path == '/predict-results':
            self._handle_predict_results(params)

        else:
            super().do_GET()

    def _symbol_groups_dir(self):
        """Use the project data directory requested by the user, with docs as fallback."""
        root = ASTOCKS_SYMBOLS_DIR
        fallback = DOCS_DIR / 'data' / 'Astocks' / 'symbols'
        return root if root.exists() else fallback

    @staticmethod
    def _market_name_signature(root):
        """Track only the compact files used to build the symbol-name index."""
        paths = (root / 'meta.json', root / 'latest.json', root / 'indices')
        return tuple(
            (str(path), path.stat().st_mtime_ns if path.exists() else 0)
            for path in paths
        )

    @staticmethod
    def _load_market_names(root):
        """Load names from compact market indexes without scanning every stock file."""
        result = {}

        meta_path = root / 'meta.json'
        if meta_path.exists():
            try:
                payload = json.loads(meta_path.read_text(encoding='utf-8-sig'))
                for code, name in (payload.get('name_map') or {}).items():
                    if code and name:
                        result[str(code).strip().upper()] = str(name).strip()
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        latest_path = root / 'latest.json'
        if latest_path.exists():
            try:
                payload = json.loads(latest_path.read_text(encoding='utf-8-sig'))
                records = payload.get('data') or payload.get('records') or []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    code = record.get('ts_code') or record.get('symbol') or record.get('code')
                    name = record.get('name') or record.get('display_name')
                    if code and name:
                        result[str(code).strip().upper()] = str(name).strip()
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        # Index files are few and are not always included in latest.json.
        indices_dir = root / 'indices'
        if indices_dir.exists():
            for path in indices_dir.glob('*.json'):
                try:
                    payload = json.loads(path.read_text(encoding='utf-8-sig'))
                    records = payload.get('records') or []
                    name = payload.get('name') or (records[-1].get('name') if records else '')
                    if name:
                        result[path.stem.upper()] = str(name).strip()
                except (OSError, ValueError, json.JSONDecodeError, AttributeError):
                    continue

        return result

    def _load_symbol_names(self):
        global SYMBOL_NAMES_CACHE
        signature = tuple(
            (market, self._market_name_signature(config['root']))
            for market, config in MARKETS.items()
        )
        if SYMBOL_NAMES_CACHE and SYMBOL_NAMES_CACHE.get('signature') == signature:
            return SYMBOL_NAMES_CACHE['names']

        names = {}
        for config in MARKETS.values():
            names.update(self._load_market_names(config['root']))
        SYMBOL_NAMES_CACHE = {'signature': signature, 'names': names}
        return names

    def _handle_astocks_symbol_groups(self):
        global SYMBOL_GROUPS_CACHE
        signature = tuple(
            (
                market,
                (config['root'] / 'symbols').stat().st_mtime_ns
                if (config['root'] / 'symbols').exists() else 0,
                self._market_name_signature(config['root']),
            )
            for market, config in MARKETS.items()
        )
        if SYMBOL_GROUPS_CACHE and SYMBOL_GROUPS_CACHE.get('signature') == signature:
            self._json_response(200, SYMBOL_GROUPS_CACHE['payload'])
            return
        groups = []
        for market, config in MARKETS.items():
            directory = config['root'] / 'symbols'
            if not directory.exists():
                continue
            for path in sorted(directory.glob('*.json')):
                try:
                    name, symbols = self._read_symbol_group(path)
                    stat = path.stat()
                    groups.append({
                        'id': f'{market}:{path.stem}', 'key': path.stem,
                        'name': name, 'symbols': symbols, 'market': market,
                        'market_label': config['label'],
                        'asset_type': config['asset_type'],
                        'data_base': config['data_base'],
                        'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(timespec='seconds'),
                        'updated_at': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                    })
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        payload = {
            'success': True, 'groups': groups,
            'markets': [{'id': key, 'name': value['label']} for key, value in MARKETS.items()],
            'names': self._load_symbol_names(),
        }
        SYMBOL_GROUPS_CACHE = {'signature': signature, 'payload': payload}
        self._json_response(200, payload)

    def _handle_symbol_names(self):
        """Return the latest known display name for every local symbol."""
        self._json_response(200, {'success': True, 'names': self._load_symbol_names()})

    def _read_symbol_group(self, path):
        with path.open('r', encoding='utf-8') as f:
            payload = json.load(f)
        blocks = payload if isinstance(payload, list) else [payload]
        name = path.stem
        values = []
        for index, block in enumerate(blocks):
            if isinstance(block, str):
                values.append(block)
            elif isinstance(block, dict):
                if index == 0:
                    name = block.get('symbolname') or name
                values.extend(block.get('symbols') or block.get('ts_codes') or [])
        return str(name), sorted({str(value).strip().upper() for value in values if str(value).strip()})

    def _handle_astocks_snapshot(self, params):
        # Preserve the old as-of behavior and legacy etf:<group> spelling.
        group = str((params.get('group') or ['__all__'])[0])
        market = group.split(':', 1)[0] if ':' in group else 'astocks'
        market = {'etf': 'etfs'}.get(market, market)
        self._handle_market_snapshot({**params, 'market': [market], 'mode': ['asof']})

    def _handle_market_snapshot(self, params):
        """Build a latest or historical snapshot from canonical stocks/ files."""
        market = str((params.get('market') or ['astocks'])[0]).lower()
        config = MARKETS.get(market)
        if not config:
            self.send_error_response(400, 'invalid market')
            return
        group_id = str((params.get('group') or ['__all__'])[0])
        if ':' in group_id:
            prefix, group_id = group_id.split(':', 1)
            prefix = {'etf': 'etfs'}.get(prefix, prefix)
            if prefix != market:
                self.send_error_response(400, 'group does not belong to market')
                return
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', group_id) or group_id in {'.', '..'}:
            self.send_error_response(400, 'invalid group')
            return
        requested_date = str((params.get('date') or [''])[0]).replace('-', '')
        if requested_date:
            try:
                if not re.fullmatch(r'\d{8}', requested_date):
                    raise ValueError('invalid date')
                datetime.strptime(requested_date, '%Y%m%d')
            except ValueError:
                self.send_error_response(400, 'date must be YYYYMMDD or YYYY-MM-DD')
                return
        mode = str((params.get('mode') or ['exact'])[0])
        if mode not in {'exact', 'asof'}:
            self.send_error_response(400, 'mode must be exact or asof')
            return
        asset_dir = config['root'] / 'stocks'
        if not asset_dir.is_dir():
            self.send_error_response(404, 'stocks directory not found')
            return
        symbol_filter = None
        group_signature = None
        if group_id not in {'', '__all__'}:
            group_file = config['root'] / 'symbols' / f'{group_id}.json'
            if not group_file.exists():
                self.send_error_response(404, f'Group not found: {group_id}')
                return
            try:
                _, symbols = self._read_symbol_group(group_file)
                group_signature = group_file.stat().st_mtime_ns
            except (OSError, ValueError, TypeError):
                self.send_error_response(500, 'Cannot read symbol group')
                return
            symbol_filter = set(symbols)

        # Check file versions without parsing histories again on a cache hit.
        files, file_versions = [], []
        with os.scandir(asset_dir) as entries:
            for entry in entries:
                if not entry.name.endswith('.json') or not entry.is_file():
                    continue
                if symbol_filter is not None and Path(entry.name).stem.upper() not in symbol_filter:
                    continue
                try:
                    stat = entry.stat()
                    files.append(Path(entry.path))
                    file_versions.append((entry.name, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    continue
        meta_path = config['root'] / 'meta.json'
        meta_version = meta_path.stat().st_mtime_ns if meta_path.exists() else 0
        signature = (tuple(sorted(file_versions)), group_signature, meta_version)
        cache_key = (market, group_id, requested_date, mode)
        cached = MARKET_SNAPSHOT_CACHE.get(cache_key)
        if cached and cached['signature'] == signature:
            self._json_response(200, cached['payload'])
            return

        rows, dates, skipped = [], set(), []
        # Names come from the stock payload first; meta is a small fallback only.
        names = {}
        try:
            names = json.loads(meta_path.read_text(encoding='utf-8-sig')).get('name_map') or {}
        except (OSError, ValueError, AttributeError):
            pass
        for path in sorted(files):
            symbol = path.stem.upper()
            if symbol_filter is not None and symbol not in symbol_filter:
                continue
            try:
                item = json.loads(path.read_text(encoding='utf-8-sig'))
                selected = None
                selected_date = ''
                for record in item.get('records') or []:
                    trade_date = str(record.get('trade_date') or record.get('date') or '').replace('-', '')
                    if not trade_date:
                        continue
                    dates.add(trade_date)
                    matches = (not requested_date or trade_date == requested_date
                               or (mode == 'asof' and trade_date <= requested_date))
                    if matches and trade_date >= selected_date:
                        selected = record
                        selected_date = trade_date
                if selected is None:
                    continue
                row = dict(selected)
                row['name'] = row.get('name') or item.get('name') or names.get(symbol) or symbol
                row['trade_date'] = selected_date
                row['ts_code'] = symbol
                rows.append(row)
            except (OSError, ValueError, AttributeError, TypeError):
                skipped.append(path.name)
                continue
        if mode == 'exact' and not requested_date and dates:
            latest_date = max(dates)
            rows = [row for row in rows if row['trade_date'] == latest_date]
        actual_date = max((str(row.get('trade_date') or row.get('date') or '').replace('-', '') for row in rows), default='')
        updated_ns = max((version[1] for version in file_versions), default=0)
        payload = {'success': True, 'market': market, 'group': group_id,
                   'source': 'stocks', 'mode': mode,
                   'date': actual_date if mode == 'asof' else requested_date or actual_date,
                   'actual_date': actual_date,
                   'dates': sorted(dates), 'data': rows, 'stock_count': len(files),
                   'skipped_files': skipped,
                   'updated_at': datetime.fromtimestamp(updated_ns / 1e9).isoformat(timespec='seconds') if updated_ns else None}
        # A bounded result cache, never a copy of all per-symbol histories.
        if len(MARKET_SNAPSHOT_CACHE) >= 12:
            MARKET_SNAPSHOT_CACHE.pop(next(iter(MARKET_SNAPSHOT_CACHE)))
        MARKET_SNAPSHOT_CACHE[cache_key] = {'signature': signature, 'payload': payload}
        self._json_response(200, payload)

    def _handle_astocks_indices(self):
        self._handle_market_indices({'market': ['astocks']})

    def _handle_market_indices(self, params):
        market = str((params.get('market') or ['astocks'])[0]).lower()
        config = MARKETS.get(market)
        if not config:
            self.send_error_response(400, 'invalid market')
            return
        indices_dir = config['root'] / 'indices'
        items = []
        for path in sorted(indices_dir.glob('*.json')):
            try:
                with path.open('r', encoding='utf-8') as f:
                    payload = json.load(f)
                records = payload.get('records') or []
                if records:
                    items.append({'ts_code': payload.get('ts_code', path.stem), 'name': payload.get('name', path.stem), **records[-1]})
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        self._json_response(200, {'success': True, 'data': items})

    def _handle_astocks_index(self, params):
        self._handle_market_index({'market': ['astocks'], 'symbol': params.get('symbol', [''])})

    def _handle_market_index(self, params):
        market = str((params.get('market') or ['astocks'])[0]).lower()
        config = MARKETS.get(market)
        if not config:
            self.send_error_response(400, 'invalid market')
            return
        symbol = params.get('symbol', [''])[0]
        if not symbol or any(char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for char in symbol):
            self.send_error_response(400, 'Invalid index symbol')
            return
        path = config['root'] / 'indices' / f'{symbol}.json'
        if not path.exists():
            self.send_error_response(404, f'Index not found: {symbol}')
            return
        try:
            with path.open('r', encoding='utf-8') as f:
                self._json_response(200, {'success': True, 'data': json.load(f)})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.send_error_response(500, str(exc))

    def _handle_astocks_factor_index(self, params):
        """List saved index factor series and their available dates."""
        items = []
        if ASTOCKS_FACTORS_DIR.exists():
            for directory in sorted(ASTOCKS_FACTORS_DIR.iterdir()):
                if not directory.is_dir() or any(ch not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for ch in directory.name):
                    continue
                dates = sorted(path.stem for path in directory.glob('*.json') if path.stem.isdigit())
                if not dates:
                    continue
                name = directory.name
                index_path = ASTOCKS_INDICES_DIR / f'{directory.name}.json'
                if index_path.exists():
                    try:
                        with index_path.open('r', encoding='utf-8') as handle:
                            name = json.load(handle).get('name') or name
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
                first_path = directory / f'{dates[-1]}.json'
                try:
                    with first_path.open('r', encoding='utf-8') as handle:
                        payload = json.load(handle)
                    name = payload.get('name') or name
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                items.append({'ts_code': directory.name, 'name': name, 'dates': dates})
        self._json_response(200, {'success': True, 'data': items})

    def _handle_astocks_factor(self, params):
        symbol = params.get('symbol', [''])[0]
        requested_date = params.get('date', [''])[0]
        valid = lambda value: value and all(ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for ch in value)
        if not valid(symbol) or (requested_date and not requested_date.isdigit()):
            self.send_error_response(400, 'Invalid symbol or date')
            return
        directory = ASTOCKS_FACTORS_DIR / symbol
        if not directory.exists():
            self.send_error_response(404, f'Factors not found: {symbol}')
            return
        dates = sorted(path.stem for path in directory.glob('*.json') if path.stem.isdigit())
        actual_date = requested_date if requested_date in dates else (dates[-1] if dates else '')
        if not actual_date:
            self.send_error_response(404, f'No factor dates found: {symbol}')
            return
        path = directory / f'{actual_date}.json'
        try:
            with path.open('r', encoding='utf-8') as handle:
                payload = json.load(handle)
            self._json_response(200, {'success': True, 'data': payload, 'dates': dates})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.send_error_response(500, str(exc))

    def _handle_market_factors(self):
        global MARKET_FACTORS_CACHE
        root = MARKETS['astocks']['root']
        files = sorted((root / 'stocks').glob('*.json'))
        macro_file = root / 'market_factors_macro.json'
        signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                          for path in files + ([macro_file] if macro_file.exists() else []))
        if MARKET_FACTORS_CACHE is not None and MARKET_FACTORS_CACHE['signature'] == signature:
            self._json_response(200, {'success': True, 'data': MARKET_FACTORS_CACHE['points']})
            return
        points = []
        macro = {}
        if macro_file.exists():
            try:
                with macro_file.open('r', encoding='utf-8') as f:
                    macro = json.load(f)
            except (OSError, ValueError, json.JSONDecodeError):
                macro = {}
        # Keep only the two numeric inputs, not all histories, while aggregating.
        by_date = {}
        for path in files:
            try:
                item = json.loads(path.read_text(encoding='utf-8-sig'))
                for row in item.get('records') or []:
                    day = str(row.get('trade_date') or row.get('date') or '').replace('-', '')
                    if day:
                        by_date.setdefault(day, []).append((float(row.get('amount') or 0), float(row.get('total_mv') or 0)))
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        for day, values in sorted(by_date.items()):
            values.sort(key=lambda item: item[0])
            total_amount = sum(amount for amount, _ in values)
            total_mv = sum(mv for _, mv in values)
            top_n = max(1, int(len(values) * 0.05))
            crowding = sum(amount for amount, _ in values[-top_n:]) / total_amount if total_amount else None
            extra = macro.get(day, {}) if isinstance(macro, dict) else {}
            points.append({'date': day, 'turnover_ratio': total_amount / (total_mv * 10) if total_mv else None, 'crowding': crowding, 'margin_ratio': extra.get('margin_ratio'), 'deposit_ratio': extra.get('deposit_ratio')})
        MARKET_FACTORS_CACHE = {'signature': signature, 'points': points}
        self._json_response(200, {'success': True, 'data': points})

    def _handle_predict_results(self, params):
        """List locally generated competition results; never exposes model config."""
        requested_agent = params.get('agent', [''])[0]
        requested_date = params.get('date', [''])[0]
        items = []
        indices = self._load_prediction_indices()
        if not PREDICT_OUTPUT_DIR.exists():
            self._json_response(200, {'success': True, 'data': items})
            return
        for agent_dir in sorted(PREDICT_OUTPUT_DIR.iterdir()):
            if not agent_dir.is_dir() or (requested_agent and agent_dir.name != requested_agent):
                continue
            for path in sorted(agent_dir.glob('*.json'), reverse=True):
                if requested_date and path.stem != requested_date:
                    continue
                try:
                    with path.open('r', encoding='utf-8') as handle:
                        payload = json.load(handle)
                    predictions = [self._verify_prediction(item, payload.get('prediction_date', path.stem), indices)
                                   for item in (payload.get('predictions') or [])]
                    items.append({
                        'agent_id': agent_dir.name,
                        'agent_name': payload.get('agent_name', agent_dir.name),
                        'prediction_date': payload.get('prediction_date', path.stem),
                        'generated_at': payload.get('generated_at'),
                        'lookback_days': payload.get('lookback_days'),
                        'predictions': predictions,
                    })
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        leaderboard = self._build_prediction_leaderboard(items)
        self._json_response(200, {'success': True, 'data': items, 'leaderboard': leaderboard})

    def _load_prediction_indices(self):
        result = {}
        for path in ASTOCKS_INDICES_DIR.glob('*.json'):
            try:
                with path.open('r', encoding='utf-8') as handle:
                    payload = json.load(handle)
                result[str(payload.get('ts_code', path.stem))] = payload
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return result

    @staticmethod
    def _classify_pct(value):
        if value <= -1: return 'strong_down'
        if value < 0: return 'down'
        if value < 1: return 'up'
        return 'strong_up'

    def _verify_prediction(self, item, prediction_date, indices):
        """Attach actual target-day data without changing the saved prediction file."""
        if not item.get('prediction') or item.get('error'):
            return item
        actual = item.get('actual')
        if actual is None:
            index = indices.get(str(item.get('ts_code')))
            for row in (index or {}).get('records', []):
                if str(row.get('trade_date', '')) == str(prediction_date):
                    try:
                        pct = float(row.get('pct_chg'))
                    except (TypeError, ValueError):
                        break
                    actual = {
                        'trade_date': str(prediction_date), 'pct_chg': pct,
                        'direction': 'up' if pct >= 0 else 'down',
                        'candle_class': self._classify_pct(pct),
                        'open': row.get('open'), 'high': row.get('high'),
                        'low': row.get('low'), 'close': row.get('close'),
                    }
                    break
        verification = None
        if actual:
            prediction = item['prediction']
            verification = {
                'direction_correct': prediction.get('direction') == actual.get('direction'),
                'candle_correct': prediction.get('candle_class') == actual.get('candle_class'),
            }
        return {**item, 'actual': actual, 'verification': verification}

    @staticmethod
    def _build_prediction_leaderboard(items):
        grouped = {}
        for run in items:
            key = run.get('agent_id') or run.get('agent_name')
            entry = grouped.setdefault(key, {
                'agent_id': key, 'agent_name': run.get('agent_name'), 'run_count': 0,
                'prediction_dates': [], 'total_predictions': 0, 'verified_predictions': 0,
                'pending_predictions': 0, 'direction_correct': 0, 'candle_correct': 0,
            })
            entry['run_count'] += 1
            date = run.get('prediction_date')
            if date and date not in entry['prediction_dates']:
                entry['prediction_dates'].append(date)
            rows = [item for item in run.get('predictions', []) if item.get('prediction')]
            verified = [item for item in rows if item.get('verification') is not None]
            entry['total_predictions'] += len(rows)
            entry['verified_predictions'] += len(verified)
            entry['pending_predictions'] += len(rows) - len(verified)
            entry['direction_correct'] += sum(1 for item in verified if item['verification'].get('direction_correct'))
            entry['candle_correct'] += sum(1 for item in verified if item['verification'].get('candle_correct'))
        board = []
        for entry in grouped.values():
            verified_count = entry['verified_predictions']
            entry['prediction_dates'].sort()
            entry['latest_prediction_date'] = entry['prediction_dates'][-1] if entry['prediction_dates'] else None
            entry['direction_accuracy'] = round(entry['direction_correct'] / verified_count * 100, 2) if verified_count else None
            entry['candle_accuracy'] = round(entry['candle_correct'] / verified_count * 100, 2) if verified_count else None
            board.append(entry)
        board.sort(key=lambda item: (item['direction_accuracy'] is not None, item['direction_accuracy'] or -1,
                                     item['candle_accuracy'] or -1), reverse=True)
        for index, item in enumerate(board, 1):
            item['rank'] = index
        return board

    def _handle_save_symbol_group(self):
        global SYMBOL_GROUPS_CACHE, MARKET_SNAPSHOT_CACHE
        try:
            payload = json.loads(self._read_body())
            market = str(payload.get('market', '')).strip().lower()
            group_id = str(payload.get('id') or payload.get('key') or '').strip()
            name = str(payload.get('name', '')).strip()
            symbols = payload.get('symbols', [])
            if market not in MARKETS:
                self.send_error_response(400, 'market must be astocks, etfs or usstocks')
                return
            if not group_id or not name or not isinstance(symbols, list) or not all(isinstance(v, str) for v in symbols):
                self.send_error_response(400, 'market, id, name and symbols[] are required')
                return
            if any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.' for ch in group_id):
                self.send_error_response(400, 'Invalid group id')
                return
            directory = MARKETS[market]['root'] / 'symbols'
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f'{group_id}.json'
            clean = sorted({v.strip().upper() for v in symbols if v.strip()})
            if not clean:
                self.send_error_response(400, 'symbols cannot be empty')
                return
            with target.open('w', encoding='utf-8') as f:
                json.dump({'symbolname': name, 'symbols': clean}, f, ensure_ascii=False, indent=2)
            SYMBOL_GROUPS_CACHE = None
            MARKET_SNAPSHOT_CACHE.clear()
            self._json_response(200, {
                'success': True, 'id': f'{market}:{group_id}', 'key': group_id,
                'market': market, 'name': name, 'symbols': clean,
            })
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as exc:
            self.send_error_response(500, str(exc))

    def _handle_load_config(self, rel_path):
        """
        rel_path 是相对于 PROJECT_DIR 的路径，
        例如 'configs/astock_config_day.json'
        """
        target = (PROJECT_DIR / rel_path).resolve()

        # 简单安全检查：不允许跑出项目目录
        try:
            target.relative_to(PROJECT_DIR)
        except ValueError:
            self.send_error_response(403, 'Path traversal not allowed')
            return

        if not target.exists():
            self.send_error_response(404, f'File not found: {rel_path}')
            print(f'✗ load-config: file not found: {target}')
            return

        try:
            with open(target, 'r', encoding='utf-8') as f:
                data = json.load(f)
            known_configs = {
                (PROJECT_DIR / 'configs' / 'astock_config_day.json').resolve(): 'trading',
                (PROJECT_DIR / 'predict_v2' / 'config.json').resolve(): 'prediction',
            }
            section = known_configs.get(target)
            if section and isinstance(data, dict):
                changed = False
                for index, model in enumerate(data.get('models') or []):
                    had_legacy_key = 'openai_api_key' in model
                    model.pop('openai_api_key', None)
                    env_key = self._launch_secret_env(section, model, index)
                    if had_legacy_key:
                        changed = True
                    model['api_key_env'] = env_key
                    model['has_api_key'] = bool(os.getenv(env_key))
                if changed:
                    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            self._json_response(200, {'success': True, 'data': data})
            print(f'✓ load-config: {target}')
        except json.JSONDecodeError as e:
            self.send_error_response(400, f'JSON parse error: {e}')
        except Exception as e:
            self.send_error_response(500, str(e))

    def _handle_load_prompts(self, params):
        """
        GET /load-prompts?type=strategy|journal
        读取单个 JSON 文件，返回其中的 prompts 数组。
        文件格式：{ "prompts": [{ "id": 1, "title": "...", "content": "...", "active": false }] }
        若文件不存在则返回空数组。
        """
        prompt_type = params.get('type', ['strategy'])[0]
        targets = {'strategy': STRATEGY_PROMPT_FILE, 'journal': JOURNAL_PROMPT_FILE, 'prediction_style': PREDICTION_STYLE_PROMPT_FILE}
        if prompt_type in ('system_trading', 'system_prediction'):
            content = self._system_prompt_text(prompt_type)
            self._json_response(200, {'success': True, 'readonly': True, 'prompts': [{'id': prompt_type, 'title': '系统提示词', 'content': content}]})
            return
        target = targets.get(prompt_type, STRATEGY_PROMPT_FILE)

        if not target.exists():
            self._json_response(200, {'success': True, 'prompts': []})
            return

        try:
            with open(target, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if prompt_type == 'prediction_style':
                prompts = [{'id': key, 'title': value.get('name', key), 'content': value.get('instruction', ''), '_profile_key': key}
                           for key, value in data.items() if isinstance(value, dict)]
            else:
                prompts = data.get('prompts', [])
            self._json_response(200, {'success': True, 'prompts': prompts})
            print(f'✓ /load-prompts [{prompt_type}]: {target}')
        except json.JSONDecodeError as e:
            self.send_error_response(400, f'JSON parse error: {e}')
        except Exception as e:
            self.send_error_response(500, str(e))

    # ────────────────────────────────────────────────────────
    # POST
    # ────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        print(f'POST {path}')

        if path == '/save-config':
            self._handle_save_config()

        elif path == '/launch-settings':
            self._handle_save_launch_settings()

        elif path == '/save-prompt':
            self._handle_save_prompt()

        elif path == '/quick-download-data':
            self._handle_quick_download_data()

        elif path in ('/update-market-data', '/update-astocks', '/update-sci2k'):
            self._handle_update_astocks()

        elif path in ('/symbol-group', '/save-astocks-symbol-group'):
            self._handle_save_symbol_group()

        elif path == '/run-agent':
            self._handle_run_agent()

        elif path == '/run-prediction':
            self._handle_run_prediction()

        else:
            self.send_error_response(404, f'Unknown endpoint: {path}')

    # ── /save-config ────────────────────────────────────────
    def _handle_save_config(self):
        """
        Body: { "path": "configs/astock_config_day.json", "data": {...} }
        path 相对于 PROJECT_DIR
        """
        try:
            body    = self._read_body()
            payload = json.loads(body)
            rel     = payload.get('path')
            data    = payload.get('data')

            if not rel or data is None:
                self.send_error_response(400, 'Missing "path" or "data"'); return

            target = (PROJECT_DIR / rel).resolve()
            try:
                target.relative_to(PROJECT_DIR)
            except ValueError:
                self.send_error_response(403, 'Path traversal not allowed'); return

            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._json_response(200, {'success': True, 'message': f'✓ Saved {rel}'})
            print(f'✓ /save-config: {target}')
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))

    def _system_prompt_text(self, prompt_type):
        if prompt_type == 'system_prediction':
            path = PROJECT_DIR / 'predict_v2' / 'predict_layer' / 'prompts.py'
            marker = 'SYSTEM_PROMPT'
        else:
            path = PROJECT_DIR / 'agent' / 'agent_prompt' / 'agent_prompt_astock.py'
            marker = 'agent_system_prompt_astock'
        try:
            text = path.read_text(encoding='utf-8')
            return text[:12000]
        except OSError:
            return f'{marker}（只读）'

    def _launch_secret_env(self, section, model, index):
        explicit = str(model.get('api_key_env') or '').strip()
        if explicit:
            return explicit
        label = str(model.get('signature') or model.get('name') or f'model_{index}').upper()
        slug = re.sub(r'[^A-Z0-9]+', '_', label).strip('_')[:48] or f'MODEL_{index}'
        return f'DIAI_SIM_{slug}_{index}_API_KEY' if section == 'trading' else f'DIAI_PREDICT_{slug}_{index}_API_KEY'

    @staticmethod
    def _valid_launch_env_name(value):
        return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(value or '').strip()))

    def _handle_launch_settings(self):
        """Load simulation/prediction settings while never returning API secrets."""
        targets = {
            'trading': PROJECT_DIR / 'configs' / 'astock_config_day.json',
            'prediction': PROJECT_DIR / 'predict_v2' / 'config.json',
        }
        try:
            from dotenv import load_dotenv
            load_dotenv(PROJECT_DIR / '.env', override=False)
            payload = {}
            for section, target in targets.items():
                data = json.loads(target.read_text(encoding='utf-8'))
                # predict_v2 uses a single `model` object; the UI edits a uniform models list.
                if section == 'prediction' and not data.get('models') and isinstance(data.get('model'), dict):
                    data['models'] = [data['model']]
                changed = False
                for index, model in enumerate(data.get('models') or []):
                    had_legacy_key = 'openai_api_key' in model
                    model.pop('openai_api_key', None)
                    env_key = self._launch_secret_env(section, model, index)
                    if not self._valid_launch_env_name(env_key):
                        env_key = self._launch_secret_env(section, {'signature': model.get('signature'), 'name': model.get('name')}, index)
                    if had_legacy_key:
                        changed = True
                    model['api_key_env'] = env_key
                    model['has_api_key'] = bool(os.getenv(env_key))
                if changed:
                    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                payload[section] = data
            def prompt_items(path):
                source = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
                return [{'id': str(item.get('id')), 'title': item.get('title', '未命名提示词')}
                        for item in source.get('prompts', [])]
            profiles = json.loads(PREDICTION_STYLE_PROMPT_FILE.read_text(encoding='utf-8')) if PREDICTION_STYLE_PROMPT_FILE.exists() else {}
            payload['prompt_options'] = {
                'strategy': prompt_items(STRATEGY_PROMPT_FILE),
                'journal': prompt_items(JOURNAL_PROMPT_FILE),
                'prediction_style': [{'id': key, 'title': value.get('name', key)} for key, value in profiles.items()],
            }
            if 'prompt_selection' not in payload['trading']:
                def legacy_selected(path):
                    source = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
                    return [str(item.get('id')) for item in source.get('prompts', []) if item.get('active')]
                payload['trading']['prompt_selection'] = {
                    'strategy': legacy_selected(STRATEGY_PROMPT_FILE),
                    'journal': legacy_selected(JOURNAL_PROMPT_FILE),
                }
            self._json_response(200, {'success': True, 'data': payload})
        except Exception as exc:
            self.send_error_response(500, str(exc))

    def _handle_save_launch_settings(self):
        """Save model settings and environment-variable names; never handle secret values."""
        try:
            payload = json.loads(self._read_body())
            section = payload.get('section')
            data = payload.get('data')
            if section not in ('trading', 'prediction') or not isinstance(data, dict):
                self.send_error_response(400, 'section and settings object are required')
                return
            target = (PROJECT_DIR / ('configs/astock_config_day.json' if section == 'trading' else 'predict_v2/config.json')).resolve()
            target.relative_to(PROJECT_DIR)
            # Secrets are intentionally out of band. The user fills them in .env.
            if payload.get('secrets'):
                self.send_error_response(400, 'Do not submit secret values; fill the referenced environment variables in .env')
                return
            models = data.get('models') or []
            for index, model in enumerate(models):
                env_key = self._launch_secret_env(section, model, index)
                if not self._valid_launch_env_name(env_key):
                    self.send_error_response(400, f'Invalid API-key environment variable name: {env_key}')
                    return
            clean = json.loads(json.dumps(data))
            if section == 'prediction':
                models = clean.get('models') or []
                clean['model'] = models[0] if models else clean.get('model', {})
                clean.pop('models', None)
                clean['model'].pop('openai_api_key', None)
                clean['model'].pop('has_api_key', None)
                clean['model']['api_key_env'] = self._launch_secret_env(section, clean['model'], 0)
            for index, model in enumerate(clean.get('models') or []):
                model.pop('openai_api_key', None)
                model.pop('has_api_key', None)
                model['api_key_env'] = self._launch_secret_env(section, model, index)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            self._json_response(200, {'success': True, 'message': 'Settings saved; fill the referenced environment variables in .env'})
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as exc:
            self.send_error_response(500, str(exc))

    # ── /save-prompt ────────────────────────────────────────
    def _handle_save_prompt(self):
        """
        POST /save-prompt
        Body: { "type": "strategy"|"journal", "prompts": [...] }
        将完整的 prompts 数组写入对应的单个 JSON 文件。
        """
        try:
            body        = self._read_body()
            payload     = json.loads(body)
            prompt_type = payload.get('type', 'strategy')
            prompts     = payload.get('prompts')

            if not isinstance(prompts, list):
                self.send_error_response(400, '"prompts" must be a list'); return

            if prompt_type in ('system_trading', 'system_prediction'):
                self.send_error_response(403, 'System prompts are read-only'); return
            if prompt_type in ('strategy', 'journal'):
                for item in prompts:
                    if isinstance(item, dict):
                        item.pop('active', None)
            target = {'strategy': STRATEGY_PROMPT_FILE, 'journal': JOURNAL_PROMPT_FILE, 'prediction_style': PREDICTION_STYLE_PROMPT_FILE}.get(prompt_type, STRATEGY_PROMPT_FILE)
            target.parent.mkdir(parents=True, exist_ok=True)

            with open(target, 'w', encoding='utf-8') as f:
                if prompt_type == 'prediction_style':
                    profiles = {}
                    for item in prompts:
                        key = str(item.get('_profile_key') or item.get('id') or item.get('title') or 'custom').strip()
                        profiles[key] = {'name': item.get('title', key), 'instruction': item.get('content', '')}
                    json.dump(profiles, f, indent=2, ensure_ascii=False)
                else:
                    json.dump({'prompts': prompts}, f, indent=2, ensure_ascii=False)

            self._json_response(200, {'success': True, 'message': f'✓ Saved {target.name}'})
            print(f'✓ /save-prompt [{prompt_type}]: {target}')
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))

    # ── /update-astocks (legacy /update-sci2k alias) ───────
    def _handle_update_astocks(self):
        """
        POST /update-market-data
        Body: { "start_date": "20260701" }   (可选，缺省从 2026-07-01 开始)
        调用 data/get_Astocks_data.py，更新全部 A 股数据至今日。
        通过 SSE 实时推送输出。
        """
        import time
        try:
            body    = self._read_body()
            payload = json.loads(body) if body.strip() else {}
        except Exception:
            payload = {}

        from datetime import date
        today      = date.today().strftime('%Y%m%d')
        # Global updates intentionally start from 2026-07-01. Each downloader
        # still advances per symbol from its local latest date when incremental.
        start_date = str(payload.get('start_date') or '20260701').replace('-', '')

        script = PROJECT_DIR / 'data' / 'get_Astocks_data.py'
        if not script.exists():
            self.send_error_response(404, f'Script not found: {script}'); return

        # SSE 流式输出
        self.send_response(200)
        self.send_header('Content-Type',  'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

        def sse(obj):
            try:
                self.wfile.write(('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

        sse({'type': 'stage', 'message': f'开始增量更新全部市场数据 {start_date} → {today}'})

        env = {
            **os.environ,
            'PYTHONIOENCODING': 'utf-8',
            'ASTOCKS_DATA_DIR': str(PROJECT_DIR / 'data' / 'Astocks'),
        }
        cmd = [sys.executable, str(script), '--start', start_date, '--end', today, '--incremental']

        try:
            results = {}
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', env=env
            )
            q = queue.Queue()
            def _read(pipe, kind):
                for line in pipe: q.put((kind, line.rstrip()))
                q.put((kind, None))
            threading.Thread(target=_read, args=(proc.stdout, 'stdout'), daemon=True).start()
            threading.Thread(target=_read, args=(proc.stderr, 'stderr'), daemon=True).start()

            done = 0
            while done < 2:
                kind, line = q.get()
                if line is None: done += 1
                else:
                    sse({'type': kind, 'line': line})
                    print(f'  [astocks/{kind}] {line}')

            proc.wait()
            results['A 股'] = proc.returncode
            index_script = PROJECT_DIR / 'data' / 'get_Astocks_indices.py'
            if index_script.exists():
                sse({'type': 'stage', 'message': 'Updating common indices'})
                index_proc = subprocess.Popen(
                    [sys.executable, str(index_script), '--end', today], cwd=str(PROJECT_DIR),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', env=env
                )
                for line in index_proc.stdout:
                    sse({'type': 'line', 'line': line.rstrip()})
                index_proc.wait()
                results['A 股指数'] = index_proc.returncode
                if index_proc.returncode == 0:
                    sse({'type': 'success', 'message': 'Index data update complete'})
                else:
                    sse({'type': 'error', 'message': f'Index update exit code {index_proc.returncode}'})
            etf_script = PROJECT_DIR / 'data' / 'get_etf_data.py'
            if etf_script.exists():
                sse({'type': 'stage', 'message': 'Updating listed ETF data'})
                etf_proc = subprocess.Popen(
                    [sys.executable, str(etf_script), '--start', start_date, '--end', today],
                    cwd=str(PROJECT_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', env=env
                )
                for line in etf_proc.stdout:
                    sse({'type': 'line', 'line': line.rstrip()})
                etf_proc.wait()
                results['ETF'] = etf_proc.returncode
                if etf_proc.returncode == 0:
                    sse({'type': 'success', 'message': 'ETF data update complete'})
                else:
                    sse({'type': 'error', 'message': f'ETF update exit code {etf_proc.returncode}'})
            us_script = PROJECT_DIR / 'data' / 'get_us_market_data.py'
            if us_script.exists() and (USSTOCKS_DATA_DIR / 'symbols').exists():
                sse({'type': 'stage', 'message': 'Updating U.S. stocks and indexes'})
                us_proc = subprocess.Popen(
                    [sys.executable, str(us_script), '--start', start_date, '--end', today],
                    cwd=str(PROJECT_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', env=env
                )
                for line in us_proc.stdout:
                    sse({'type': 'line', 'line': line.rstrip()})
                us_proc.wait()
                results['美股'] = us_proc.returncode
                if us_proc.returncode == 0:
                    sse({'type': 'success', 'message': 'U.S. market data update complete'})
                else:
                    sse({'type': 'error', 'message': f'U.S. market update exit code {us_proc.returncode}'})
            failed = [name for name, code in results.items() if code != 0]
            if not failed:
                sse({'type': 'success', 'message': '✓ 全部市场数据更新完成'})
            else:
                sse({'type': 'error', 'message': f'✗ 全局更新部分失败：{"、".join(failed)}；其他市场已正常保存'})
        except Exception as e:
            sse({'type': 'error', 'message': f'执行失败: {e}'})

        try:
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except Exception:
            pass
        print('✓ /update-astocks 完成')

    # ── /quick-download-data ────────────────────────────────
    def _handle_quick_download_data(self):
        """Run one of the fixed market-data downloaders and stream its output."""
        try:
            payload = json.loads(self._read_body())
            if not isinstance(payload, dict):
                raise ValueError('请求内容必须是 JSON 对象')
            cmd, label, output_dir = self._build_quick_download_command(payload)
            post_commands = self._build_quick_download_post_commands(payload)
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
            return
        except ValueError as exc:
            self.send_error_response(400, str(exc))
            return

        if not QUICK_DOWNLOAD_LOCK.acquire(blocking=False):
            self.send_error_response(409, '已有数据下载任务正在运行，请稍后再试')
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

        def sse(obj):
            try:
                self.wfile.write(('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        sse({'type': 'stage', 'message': f'开始下载 {label}', 'output_dir': output_dir})
        print(f'▶ /quick-download-data: {label}')

        def run_command(command, stage):
            sse({'type': 'stage', 'message': stage})
            proc = subprocess.Popen(
                command,
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
            )
            lines = queue.Queue()

            def read_pipe(pipe, kind):
                try:
                    for line in pipe:
                        lines.put((kind, line.rstrip()))
                finally:
                    lines.put((kind, None))

            threading.Thread(target=read_pipe, args=(proc.stdout, 'stdout'), daemon=True).start()
            threading.Thread(target=read_pipe, args=(proc.stderr, 'stderr'), daemon=True).start()
            finished_pipes = 0
            while finished_pipes < 2:
                kind, line = lines.get()
                if line is None:
                    finished_pipes += 1
                    continue
                sse({'type': kind, 'line': line})
                print(f'  [quick-download/{kind}] {line}')
            proc.wait()
            return proc.returncode

        try:
            returncode = run_command(cmd, f'下载原始行情：{label}')
            if returncode != 0:
                sse({'type': 'error', 'message': f'下载脚本退出码：{returncode}'})
            else:
                for stage, post_command in post_commands:
                    returncode = run_command(post_command, stage)
                    if returncode != 0:
                        sse({'type': 'error', 'message': f'{stage}失败，脚本退出码：{returncode}'})
                        break
                if returncode == 0:
                    sse({'type': 'success', 'message': f'下载及完整结构编排完成，数据已保存至 {output_dir}'})
        except Exception as exc:
            sse({'type': 'error', 'message': f'执行失败：{exc}'})
        finally:
            QUICK_DOWNLOAD_LOCK.release()
            try:
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except Exception:
                pass

    @staticmethod
    def _build_quick_download_command(payload):
        asset_type = str(payload.get('asset_type', '')).strip()
        definitions = {
            'astock-index': ('A股指数', PROJECT_DIR / 'data' / 'get_Astocks_indices.py', 'data/Astocks/indices'),
            'astock': ('A股股票', PROJECT_DIR / 'data' / 'get_Astocks_data.py', 'data/Astocks'),
            'etf': ('场内 ETF', PROJECT_DIR / 'data' / 'get_etf_data.py', 'data/ETFs'),
            'us-market': ('美股股票和指数', PROJECT_DIR / 'data' / 'get_us_market_data.py', 'data/USstocks'),
        }
        if asset_type not in definitions:
            raise ValueError('不支持的数据类型')

        raw_symbols = payload.get('symbols')
        if isinstance(raw_symbols, str):
            symbols = re.split(r'[\s,，;；]+', raw_symbols.strip())
        elif isinstance(raw_symbols, list):
            symbols = raw_symbols
        else:
            symbols = []
        symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        if not symbols:
            raise ValueError('请至少输入一个标的代码')
        if len(symbols) > 500:
            raise ValueError('单次最多下载 500 个标的')
        if any(len(symbol) > 32 or not re.fullmatch(r'[A-Z0-9.^_-]+', symbol) for symbol in symbols):
            raise ValueError('标的代码只能包含字母、数字、点、连字符、下划线或 ^')

        start_date = str(payload.get('start_date', '')).replace('-', '')
        end_date = str(payload.get('end_date', '')).replace('-', '')
        try:
            start = datetime.strptime(start_date, '%Y%m%d')
            end = datetime.strptime(end_date, '%Y%m%d')
        except ValueError:
            raise ValueError('开始日期和结束日期必须是有效日期')
        if start > end:
            raise ValueError('开始日期不能晚于结束日期')

        label, script, output_dir = definitions[asset_type]
        if not script.exists():
            raise ValueError(f'下载脚本不存在：{script.name}')
        cmd = [
            sys.executable,
            str(script),
            '--start', start_date,
            '--end', end_date,
            '--symbols', *symbols,
        ]
        return cmd, f'{label}（{len(symbols)} 个标的，{start_date} → {end_date}）', output_dir

    @staticmethod
    def _build_quick_download_post_commands(payload):
        asset_type = str(payload.get('asset_type', '')).strip()
        start_date = str(payload.get('start_date', '')).replace('-', '')
        end_date = str(payload.get('end_date', '')).replace('-', '')
        definitions = {
            'astock-index': (PROJECT_DIR / 'data' / 'Astocks', 'A_STOCK_INDEX', 'indices'),
            'astock': (PROJECT_DIR / 'data' / 'Astocks', 'A_STOCK', 'stocks'),
            'etf': (PROJECT_DIR / 'data' / 'ETFs', 'ETF', 'stocks'),
            'us-market': (PROJECT_DIR / 'data' / 'USstocks', 'US_MARKET', 'stocks'),
        }
        if asset_type == 'us-market':
            # The unified downloader already writes stocks, indices and
            # aggregate metadata; running the single-source layout builder
            # would discard the index partition.
            return []
        if asset_type not in definitions:
            raise ValueError('数据类型无效')
        root, asset_name, source = definitions[asset_type]
        commands = []
        if asset_type == 'astock-index':
            factor_script = PROJECT_DIR / 'data' / 'get_Astocks_index_factors.py'
            if not factor_script.exists():
                raise ValueError(f'指数因子脚本不存在：{factor_script.name}')
            commands.append((
                '计算指数技术因子',
                [sys.executable, str(factor_script), '--indices-root', str(root / 'indices'),
                 '--output-root', str(root / 'factors'), '--start', start_date, '--end', end_date, '--only-new'],
            ))
        return commands

    # ── /run-agent (SSE) ────────────────────────────────────
    def _handle_run_prediction(self):
        """Run predict_v2 against the saved prediction config and stream logs."""
        script = PROJECT_DIR / 'predict_v2' / 'main.py'
        config = PROJECT_DIR / 'predict_v2' / 'config.json'
        if not script.exists() or not config.exists():
            self.send_error_response(404, 'predict_v2 配置或入口脚本不存在')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

        def sse(obj):
            try:
                self.wfile.write(('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        cmd = [sys.executable, str(script), '--config', str(config), '--mode', 'predict']
        sse({'type': 'stage', 'message': '开始运行 predict_v2 预测任务'})
        try:
            proc = subprocess.Popen(cmd, cwd=str(PROJECT_DIR), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                    errors='replace', env=env)
            for line in proc.stdout:
                sse({'type': 'line', 'line': line.rstrip()})
            proc.wait()
            if proc.returncode == 0:
                sse({'type': 'success', 'message': 'predict_v2 预测完成'})
            else:
                sse({'type': 'error', 'message': f'predict_v2 退出码 {proc.returncode}'})
        except Exception as exc:
            sse({'type': 'error', 'message': f'预测任务启动失败: {exc}'})
        try:
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except Exception:
            pass

    def _handle_run_agent(self):
        """
        Body: { "config_path": "configs/astock_config_day.json" }
        依次运行:
          1. python mcp_services_start.py   (PROJECT_DIR 下)
          2. python main_client.py <config_path>
        通过 SSE 实时推送输出。
        """
        try:
            body        = self._read_body()
            payload     = json.loads(body)
            config_path = payload.get('config_path', 'configs/astock_config_day.json')
        except Exception:
            self.send_error_response(400, 'Invalid JSON body'); return

        mcp_script    = PROJECT_DIR / 'mcp_services_start.py'
        client_script = PROJECT_DIR / 'main_client.py'

        for s in [mcp_script, client_script]:
            if not s.exists():
                self.send_error_response(404, f'Script not found: {s}'); return

        # ── 开始 SSE 响应 ──
        self.send_response(200)
        self.send_header('Content-Type',  'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

        def sse(obj):
            """发送一条 SSE 事件"""
            try:
                line = 'data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n'
                self.wfile.write(line.encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

        def run_script_sse(label, cmd, cwd):
            """运行子进程，逐行通过 SSE 推送"""
            sse({'type': 'stage', 'message': label})
            print(f'▶ {label}')
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(cwd),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', env=env
                )

                # 两个线程分别读 stdout / stderr，放进同一个队列
                q = queue.Queue()
                def _read(pipe, kind):
                    for line in pipe:
                        q.put((kind, line.rstrip()))
                    q.put((kind, None))  # 结束哨兵

                t1 = threading.Thread(target=_read, args=(proc.stdout, 'stdout'), daemon=True)
                t2 = threading.Thread(target=_read, args=(proc.stderr, 'stderr'), daemon=True)
                t1.start(); t2.start()

                done_count = 0
                while done_count < 2:
                    kind, line = q.get()
                    if line is None:
                        done_count += 1
                    else:
                        sse({'type': kind, 'line': line})
                        print(f'  [{kind}] {line}')

                proc.wait()
                return proc.returncode

            except Exception as e:
                sse({'type': 'error', 'message': f'{label} 启动失败: {e}'})
                return -1

        # 步骤 1：mcp_services_start.py
        # mcp_services_start.py 是常驻进程，只等待约 5 秒的启动日志，然后继续。
        # 使用线程读取输出，兼容 Windows（select.select 在 Windows 不支持 pipe）。
        sse({'type': 'stage', 'message': '步骤 1/2: 启动 MCP 服务 (mcp_services_start.py)'})
        print('▶ 步骤 1/2: mcp_services_start.py')
        try:
            import time
            mcp_proc = subprocess.Popen(
                [sys.executable, str(mcp_script)],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', env=env
            )

            # 用队列 + 线程收集启动日志，Windows/Linux 均兼容
            mcp_q = queue.Queue()
            def _mcp_read(pipe, kind):
                try:
                    for line in pipe:
                        mcp_q.put((kind, line.rstrip()))
                except Exception:
                    pass
                finally:
                    mcp_q.put((kind, None))

            threading.Thread(target=_mcp_read, args=(mcp_proc.stdout, 'stdout'), daemon=True).start()
            threading.Thread(target=_mcp_read, args=(mcp_proc.stderr, 'stderr'), daemon=True).start()

            # 收集 5 秒内的输出
            deadline = time.time() + 5
            done_pipes = 0
            while time.time() < deadline and done_pipes < 2:
                try:
                    kind, line = mcp_q.get(timeout=max(0.05, deadline - time.time()))
                    if line is None:
                        done_pipes += 1
                    else:
                        sse({'type': kind, 'line': line})
                        print(f'  [mcp/{kind}] {line}')
                except queue.Empty:
                    pass
                if mcp_proc.poll() is not None:
                    while True:
                        try:
                            kind, line = mcp_q.get_nowait()
                            if line:
                                sse({'type': kind, 'line': line})
                        except queue.Empty:
                            break
                    break

            sse({'type': 'success', 'message': 'MCP 服务已在后台启动，继续下一步…'})
        except Exception as e:
            sse({'type': 'error', 'message': f'MCP 服务启动失败: {e}'})

        # 步骤 2：main_client.py
        sse({'type': 'stage', 'message': f'步骤 2/2: 运行智能体 (main_client.py {config_path})'})
        rc = run_script_sse(
            f'main_client.py {config_path}',
            [sys.executable, str(client_script), config_path],
            PROJECT_DIR
        )

        if rc == 0:
            sse({'type': 'success', 'message': '✓ 智能体运行完成 (exit 0)'})
        else:
            sse({'type': 'error', 'message': f'✗ main_client.py 退出码 {rc}'})

        # SSE 结束信号
        try:
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except Exception:
            pass
        print('✓ /run-agent 完成')

    # ────────────────────────────────────────────────────────
    # 工具
    # ────────────────────────────────────────────────────────
    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8')

    def log_message(self, format, *args):
        print(f'  {format % args}')


def run_server(port=8888):
    os.chdir(DOCS_DIR)
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, SaveHandler)

    print(f'\n{"="*55}')
    print(f'🚀  Stock & Agent Manager Server')
    print(f'{"="*55}')
    print(f'📌  http://127.0.0.1:{port}')
    print(f'')
    print(f'  GET  /health')
    print(f'  GET  /symbol-groups        ← 三市场标的组')
    print(f'  POST /symbol-group         ← 新增或编辑标的组')
    print(f'  POST /quick-download-data  ← 按标的快速下载行情')
    print(f'  GET  /load-config?path=…   ← 读配置文件')
    print(f'  GET  /load-prompts?type=…  ← 读提示词文件 (strategy|journal)')
    print(f'  POST /save-prompt          ← 写提示词文件')
    print(f'  POST /save-config          ← 写配置文件')
    print(f'  POST /update-market-data   ← SSE 增量更新全部市场数据')
    print(f'  POST /run-agent            ← SSE 运行智能体')
    print(f'')
    print(f'🛑  Ctrl+C 停止\n')

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n⏹  Server stopped')
        httpd.server_close()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    run_server(port)
