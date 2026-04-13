#!/usr/bin/env python3
"""
Stock Manager Save Server
提供以下接口:
  GET  /health              健康检查
  POST /save                保存 stocks.json（choose_stock 页面用）
  POST /download-stocks     执行 data/1.get_price_tushare.py
  GET  /load-config         读取任意 JSON 配置文件（run_agent 页面用）
  POST /save-config         保存任意 JSON 配置文件（run_agent 页面用）
  POST /run-agent           依次执行 mcp_services_start.py + main_client.py（SSE 流式输出）

使用方法:
    python docs/save_stocks_server.py
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import sys
import subprocess
import threading
import queue
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── 路径常量 ────────────────────────────────────────────────
DOCS_DIR    = Path(__file__).resolve().parent          # .../DiAi--FinancialDataAgent/docs
PROJECT_DIR = DOCS_DIR.parent                          # .../DiAi--FinancialDataAgent
STOCKS_FILE = DOCS_DIR / 'data' / 'stocks.json'

print(f"📍 Docs dir   : {DOCS_DIR}")
print(f"📍 Project dir: {PROJECT_DIR}")
print(f"📁 Stocks file: {STOCKS_FILE}")


class SaveHandler(BaseHTTPRequestHandler):

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

        elif path == '/load-config':
            # ?path=configs/astock_config_day.json
            rel = params.get('path', [None])[0]
            if not rel:
                self.send_error_response(400, 'Missing ?path= parameter')
                return
            self._handle_load_config(rel)

        else:
            self.send_error_response(404, f'Unknown endpoint: {path}')

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
            self._json_response(200, {'success': True, 'data': data})
            print(f'✓ load-config: {target}')
        except json.JSONDecodeError as e:
            self.send_error_response(400, f'JSON parse error: {e}')
        except Exception as e:
            self.send_error_response(500, str(e))

    # ────────────────────────────────────────────────────────
    # POST
    # ────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/save':
            self._handle_save_stocks()

        elif path == '/save-config':
            self._handle_save_config()

        elif path == '/download-stocks':
            self._handle_download_stocks()

        elif path == '/run-agent':
            self._handle_run_agent()

        else:
            self.send_error_response(404, f'Unknown endpoint: {path}')

    # ── /save ───────────────────────────────────────────────
    def _handle_save_stocks(self):
        try:
            body = self._read_body()
            data = json.loads(body)

            if not isinstance(data, dict):
                self.send_error_response(400, 'Invalid data format'); return
            for key, value in data.items():
                if not isinstance(value, list):
                    self.send_error_response(400, f"'{key}' must be a list"); return
                for item in value:
                    if not isinstance(item, str):
                        self.send_error_response(400, f"Items in '{key}' must be strings"); return

            with open(STOCKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._json_response(200, {'success': True, 'message': f'✓ Saved {len(data)} stock groups'})
            print(f'✓ /save: stocks.json ({len(data)} groups)')
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
        except Exception as e:
            self.send_error_response(500, str(e))

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

    # ── /download-stocks ────────────────────────────────────
    def _handle_download_stocks(self):
        script_path = DOCS_DIR / 'data' / '1.get_price_tushare.py'
        if not script_path.exists():
            self.send_error_response(404, f'Script not found: {script_path}'); return

        print(f'▶ /download-stocks: {script_path}')
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(DOCS_DIR / 'data'),
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                env=env, timeout=300
            )
            success = result.returncode == 0
            self._json_response(200, {
                'success':    success,
                'returncode': result.returncode,
                'stdout':     result.stdout or '',
                'stderr':     result.stderr or '',
                'message':    '✓ Download completed' if success
                              else f'✗ Script exited with code {result.returncode}'
            })
            print(f'{"✓" if success else "✗"} /download-stocks exit {result.returncode}')
        except subprocess.TimeoutExpired:
            self.send_error_response(408, 'Script timed out after 300 seconds')
        except Exception as e:
            self.send_error_response(500, str(e))

    # ── /run-agent (SSE) ────────────────────────────────────
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


def run_server(port=9999):
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, SaveHandler)

    print(f'\n{"="*55}')
    print(f'🚀  Stock & Agent Manager Server')
    print(f'{"="*55}')
    print(f'📌  http://127.0.0.1:{port}')
    print(f'')
    print(f'  GET  /health')
    print(f'  POST /save                 ← stocks.json')
    print(f'  POST /download-stocks      ← tushare 脚本')
    print(f'  GET  /load-config?path=…   ← 读配置文件')
    print(f'  POST /save-config          ← 写配置文件')
    print(f'  POST /run-agent            ← SSE 运行智能体')
    print(f'')
    print(f'🛑  Ctrl+C 停止\n')

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n⏹  Server stopped')
        httpd.server_close()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    run_server(port)