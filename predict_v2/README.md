# predict_v2

`predict_v2` 是一个面向股票、指数和 ETF 的点时预测流程。Python 负责数据校验、特征计算和结果结构化，LLM 负责解释信号关系，并且必须通过 `submit_prediction` 工具提交预测结果。

## 配置说明

配置文件为 `config.json`，主要字段如下：

- `mode`：`dry_run` 只生成输入，`validate` 校验数据但不调用模型，`predict` 正式调用模型并保存结果。
- `prediction_date`：单日预测日期。非空时优先于日期范围配置。
- `prediction_start_date` / `prediction_end_date`：当 `prediction_date` 为空时启用日期范围模式。程序只运行配置标的共同拥有的真实交易日。
- `prediction_cutoff_datetime`：可选的 ISO 时间戳截止时间，仅支持单日模式；范围模式必须为 `null`。未设置时，默认使用预测日北京时间 00:00。
- `asset_type`：`stock`、`index` 或 `etf`，决定读取 `data_paths` 中的哪个目录。
- `symbols`：标的代码数组，例如 `000001.SZ`、`000001.SH`。
- `history_days`：每个预测日使用的历史交易日数量，范围为 60 到 250。
- `compact_days`：发送给 LLM 的紧凑收益率序列长度，范围为 10 到 20。
- `data_paths`：股票、指数和 ETF 的本地 JSON 数据目录。
- `output_dir`：预测结果根目录，最终路径为 `data/predict/<model.name>/<date>.json`。
- `prompt_profile`：从 `prompt.json` 中选择提示词策略，例如 `balanced`、`conservative` 或 `technical_only`。
- `news.mode`：默认 `tavily_live`，实时预测和历史回测均重新联网搜索，不读取或写入本地新闻缓存；`disabled` 可显式禁用新闻。
- `news.env_file`：密钥环境文件，相对项目根目录解析，默认 `.env`。新闻调用和密钥池代码完全位于 `predict_v2/tool_layer`，不依赖 `predict` 的模块或 `api.json`。
- `news.max_results` / `max_content_chars`：发送给 LLM 的新闻条数和单条正文长度上限。
- `model.name`：结果目录和展示名称。建议每个实验使用唯一名称，避免覆盖结果。
- `model.basemodel`：发送给 OpenAI-compatible API 的实际模型 ID。
- `model.openai_base_url`：兼容接口地址，必须使用 HTTPS。
- `model.api_key_env`：API 密钥对应的环境变量名，密钥不写入配置文件。
- `model.temperature`：采样温度，预测任务建议设置为 0 到 0.2。
- `model.timeout_seconds` / `max_retries`：请求超时时间和最大重试次数。
- `logging.level` / `directory`：日志级别和 JSONL 日志目录。

## 新闻 API 池

将 `predict_v2/.env.example` 中的变量追加到项目根目录 `.env`，填写自己的密钥；不要覆盖原有模型密钥。示例文件不包含真实密钥，程序也不会自动复制 `predict` 的密钥文件。

```dotenv
TAVILY_API_KEY_1=your-first-key
TAVILY_API_KEY_2=your-second-key
TAVILY_API_KEY_3=your-third-key
```

- 保留对单密钥 `TAVILY_API_KEY` 的兼容；也可以通过 `news.tavily_api_key_env` 更改基础变量名，编号变量使用相同名称加 `_1`、`_2` 等后缀。
- 同名进程环境变量优先于 `.env`；空值忽略，重复密钥去重。编号按数字排序，每次请求轮换起始密钥，适用于同一工具实例的连续调用。
- 鉴权失败、限流、额度不足、服务端错误、网络错误或无效响应时切换下一个密钥；每次搜索每个密钥最多尝试一次。其他 HTTP 错误立即返回脱敏错误，全部密钥失败则报错，不使用本地数据或把错误伪装成空新闻。
- `.env` 解析支持空行、注释、`export KEY=value`、单/双引号和行尾注释；不执行 shell、不展开变量，不支持多行值。重启进程以应用密钥轮换配置变更。
- `.env` 已由项目 `.gitignore` 忽略。不要将密钥放进 JSON 配置、提交到版本库或粘贴到日志中；本工具不输出密钥或服务端错误正文。`.env` 仍是明文文件，应限制其文件访问权限。

## 新闻时间隔离

1. 每次预测使用 `prediction_cutoff_datetime`；未配置时使用预测日北京时间 00:00。
2. 实时搜索将有效截止时间（预测截止时间与当前请求时间的较早值）的 UTC 日期作为 `end_date` 传递给搜索服务，回测也重新联网查询；不使用相对于今天的 `time_range`。
3. 返回结果还须通过精确时间过滤：只接受带时区、且 `published_at <= 有效截止时间` 的新闻。支持 ISO 和完整 RFC 日期时间；缺失时间、只有日期、无时区或无法解析的结果均拒绝。
4. 若结果提供更新时间，晚于截止时间、早于发布时间或无法解析的更新时间也会导致拒绝。回测抓取时间可以晚于截止时间，但不会放宽发布时间限制。
5. 不使用服务端综合答案、原始网页正文或图片。默认截止时间下，预测日期及之后发布的新闻不进入 LLM 上下文；自定义截止时间则比较具体时刻。被拒绝的记录仅保留在审计中，不进入模型输入。
6. **限制**：实时搜索返回当前索引中的摘要，发布时间过滤不能证明正文在历史截止时刻没有被修改。缺乏可靠历史版本或更新时间时，无法保证正文版本层面的零未来泄漏；要求严格历史版本复现的实验应将新闻设为 `disabled`。新闻结果中的 `policy` 也会向模型标明此限制。
7. 预测结果中保留的新闻上下文及审计仅用于解释、追踪，不作为后续新闻搜索的数据源。

## 日期范围回测

配置示例：

```json
{
  "prediction_date": "",
  "prediction_start_date": "20260803",
  "prediction_end_date": "20260810"
}
```

也可以通过命令行覆盖日期配置：

```powershell
python -m predict_v2.main --mode dry_run --start 20260803 --end 20260810
python -m predict_v2.main --mode predict --start 20260803 --end 20260810
```

每个交易日独立执行完整流程：重新截取历史数据、计算收益率特征、隔离新闻、调用 LLM 并保存单独结果。正式运行前，程序会检查整个日期范围内是否存在结果文件；只要发现冲突，就不会发起 API 请求。

例如模型名称为 `glm-5.3-v2` 时，结果文件为：

```text
data/predict/glm-5.3-v2/20260803.json
data/predict/glm-5.3-v2/20260804.json
...
```

## 运行

先在项目根目录的 `.env` 中配置模型 API 密钥，然后执行：

```powershell
cd E:\python-project\DiAi-Trader
python -m predict_v2.main --mode dry_run
python -m predict_v2.main --mode validate
python -m predict_v2.main --mode predict
```

运行测试：

```powershell
python -m unittest discover -s predict_v2/tests -v
python -m compileall -q predict_v2
```

结果 JSON 不保存完整历史 OHLCV 和完整 Prompt，只保存数据覆盖范围、收益率特征、交易信号、新闻上下文及审计信息、Prompt 哈希、模型工具调用、实际结果和兼容旧展示所需的字段。
