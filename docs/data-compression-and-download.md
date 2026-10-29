# 数据压缩与下载调用说明

本文档汇总行情数据在存储压缩、下载逻辑与前端/后端调用三方面的工作，帮助理解当前的数据流与目录约定。

## 1. 目录结构

三个市场的行情数据统一存放在以下目录，不再使用旧的 `data/a_stock_data`：

```text
data/
├── Astocks/          # A 股
│   ├── stocks/<ts_code>.json     # 每只股票独立历史文件（含行情 + 技术/基本面因子）
│   ├── indices/<index>.json      # 常用指数
│   ├── factors/                  # 指数技术因子
│   ├── symbols/                  # 标的组定义
│   ├── meta.json                 # 元信息（股票列表、名称映射、日期范围）
│   ├── dates.json                # 全部交易日索引
│   └── latest.json               # 最新交易日快照
├── ETFs/            # 场内 ETF
│   ├── stocks/<ts_code>.json
│   ├── symbols/
│   ├── meta.json
│   ├── dates.json
│   └── latest.json
└── USstocks/        # 美股与美股指数
    ├── stocks/<symbol>.json
    ├── indices/<index>.json
    ├── symbols/
    ├── meta.json
    ├── dates.json
    └── latest.json
```

`daily/` 和 A 股的 `merged.json` 属于旧版兼容产物：默认不再生成，也不随下载更新；已有旧文件保留但已不再作为数据来源。

## 2. 数据压缩工作汇总

### 2.1 统一存储，去除重复

- 将模拟交易与预测行情统一到 `Astocks`、`ETFs`、`USstocks` 三个市场目录，避免同一股票在多处重复存放。
- 每只股票的历史行情以独立 JSON 保存，`name`、`ts_code` 等公共字段只保存在顶层一次；每条行情记录不再重复写入股票名称。
- 记录中的空值（`null`）和不必要的重复字段被移除，因子字段按需保留，不裁剪行情记录或指标。

### 2.2 聚合文件的名称收敛

- `merged.json` 曾把所有股票塞进一个文件，并把名称重复写在每条记录里。压缩后名称收敛到顶层 `names` 映射，`data` 仅保留 `ts_code -> records`。
- 该文件现在默认不再生成（约 131 MB），已删除；需要时可用 `--write-merged` 手动生成。

### 2.3 停止默认生成按日分片

- `daily/<YYYYMMDD>.json` 是按交易日把全市场重新铺一份的冗余结构，且全量重写耗时。现在三个下载脚本默认都不再生成或改写它。
- 保留 `--write-daily` 开关，仅在需要兼容旧工具时手动生成。

### 2.4 轻量索引保留

- 压缩后仍保留 `meta.json`、`dates.json`、`latest.json` 作为轻量索引：前者供名称映射与标的清单，后两者供日期轴与最新行情快照，避免每次加载都扫描全市场文件。

### 2.5 前端改读单股文件

- 行情展示与大盘页面改为直接读取 `stocks/` 下的单股文件（`/market-snapshot` 接口），不再依赖 `daily/` 或 `merged.json`。

### 2.6 压缩工具

- `data/compact_market_data.py` 用于对既有 JSON 做无损压缩（去空值、去重复名称），支持 `--dry-run` 先估算、`--apply` 再执行，不删除行情记录和指标。

## 3. 数据下载逻辑

所有脚本位于 `data/`，默认从项目 `.env` 读取 `TUSHARE_TOKEN`。

| 脚本 | 作用 | 默认输出 |
| --- | --- | --- |
| `get_Astocks_data.py` | 下载全部 A 股日线、每日基本面并自算技术因子 | `Astocks/stocks/`、`meta.json`、`dates.json`、`latest.json` |
| `get_Astocks_indices.py` | 增量下载常用 A 股指数 | `Astocks/indices/` |
| `get_Astocks_index_factors.py` | 计算指数技术因子 | `Astocks/factors/` |
| `get_etf_data.py` | 增量下载场内 ETF 行情与份额 | `ETFs/stocks/`、索引与标的清单 |
| `get_us_market_data.py` | 统一下载美股个股与指数，多数据源自动兜底 | `USstocks/stocks/`、`indices/`、索引与标的清单 |

### 3.1 增量逻辑

- A 股：`--incremental` 按每只股票本地的最后交易日继续向后拉取，新标的按给定起始日期拉取。
- ETF：脚本内部读取每只 ETF 的本地最后交易日，只请求后续日期。
- 美股：按每个标的的本地最后交易日继续拉取。
- 全局更新入口默认起始日期为 `20260701`，三个下载器均从该日期向后增量到当日。

### 3.2 关键参数

- A 股：`--start`、`--end`、`--incremental`、`--symbols`、`--write-daily`、`--write-merged`、`--build-partitions`。
- ETF：`--start`、`--end`、`--symbols`、`--limit`、`--retries`、`--write-daily`。
- 美股：`--start`、`--end`、`--stocks`、`--indices`、`--symbols-file`、`--providers`、`--write-daily`。

### 3.3 旧版产物开关

三个脚本默认都不再生成 `daily/`，A 股还默认不再生成 `merged.json`。仅在需要兼容旧工具时加对应开关：

```bash
python data/get_Astocks_data.py --incremental --write-daily
python data/get_etf_data.py --write-daily
python data/get_us_market_data.py --write-daily
python data/get_Astocks_data.py --write-merged
```

## 4. 后端与前端调用

后端统一由 `docs/bs_server.py` 提供，主要路由：

| 路由 | 作用 |
| --- | --- |
| `/market-snapshot` | 按市场/分组/日期读取 `stocks/` 单股文件，返回快照（当前行情展示主数据源） |
| `/market-factors` | 聚合单股文件中的数值字段作为市场因子 |
| `/update-market-data` | SSE 流式触发全市场增量更新 |
| `/quick-download-data` | 从已有标的中选择或输入代码，快速下载指定标的 |
| `/symbol-groups`、`/symbol-group` | 读取/新增编辑三市场标的组 |
| `/market-indices`、`/market-index` | 指数列表与单指数行情 |

前端大盘页面通过 `docs/assets/js/market-display.js` 调用 `/market-snapshot`，数据来自单股文件，带版本号缓存以避免重复读取历史文件。

## 5. 模拟交易与预测的数据来源

模拟交易 Agent 读取的是独立于市场行情的聚合文件，由 `docs/config.yaml` 中的 `price_data_file` 指定，例如 `a_stock_data/sse_50_day/merged.jsonl` 或 `agent_data_astock/.../merged.jsonl`，与 `Astocks`、`ETFs`、`USstocks` 的行情文件相互独立。
