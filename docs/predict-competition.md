# 预测竞赛：结构与原理

## 1. 功能目标

预测竞赛用于比较不同智能体对指数下一交易日走势的判断能力。当前测试对象为本地保存的全部指数，预测任务包含：

- 二分类：预测下一交易日上涨或下跌。
- 四分类：预测 K 线方向和强度。
- 开放性分析：给出价格、成交量等证据，以及大盘和板块影响分析。

网页展示已经生成并验证的测试结果与排行榜，不在浏览器中调用模型。

## 2. 文件结构

```text
predict/
├── __init__.py             模块标识
├── competition.py          数据切片、提示词、模型调用、结果保存
├── run_test.py             命令行测试入口
└── test_config.json        用户填写的预测日期、规则和模型配置

data/
└── predict/
    └── <智能体名称>/
        └── <预测日期>.json  测试结果

docs/
├── predict-competition.html       预测竞赛页面
├── assets/js/predict-competition.js 页面加载和展示逻辑
└── bs_server.py                   /predict-results 结果、验证和排行榜接口
```

指数原始数据来自：

```text
data/Astocks/indices/*.json
```

每个指数文件包含 `ts_code`、`name` 和按交易日排列的 `records`。

## 3. 测试流程

```mermaid
flowchart LR
    A[test_config.json] --> B[run_test.py]
    B --> C[读取 data/Astocks/indices]
    C --> D[按预测日截取此前 10 个交易日]
    D --> E[为每个指数生成独立提示词]
    E --> F[调用启用的模型]
    F --> G[校验并规范化 JSON]
    G --> H[data/predict/<agent>/<date>.json]
    H --> I[/predict-results]
    I --> J[预测竞赛页面]
```

执行时，每个启用模型都会遍历全部指数，并单独生成一项预测。某个指数历史不足指定回看天数时，该项会保存错误状态，不会使用不完整数据调用模型。

## 4. 防止未来数据泄漏

预测日期为 `target_date` 时，历史数据筛选条件是：

```python
trade_date < target_date
```

然后只取最后 `lookback_days` 条记录。因此：

- 不会把预测日的开、高、低、收、成交量传给模型。
- 不会把预测日之后的数据传给模型。
- 输出会记录 `as_of_date`，表示模型实际看到的最后交易日。
- 输出会记录完整 `lookback`，便于复核测试输入。

例如预测 `20260817`、回看 10 日时，当前数据会使用 `20260803` 至 `20260814`，不会读取 `20260817` 的结果。

## 5. 四分类定义

`test_config.json` 中的规则将四分类约定为：

| 类别 | 含义 | 涨跌幅区间 |
|---|---|---|
| `strong_down` | 强跌 | 小于等于 -1% |
| `down` | 下跌 | 大于 -1% 且小于 0% |
| `up` | 上涨 | 大于等于 0% 且小于 1% |
| `strong_up` | 强涨 | 大于等于 1% |

二分类字段只允许 `up` 或 `down`。如果模型没有正确返回二分类，程序会根据四分类自动推导。

## 6. 配置文件

配置文件为 [predict/test_config.json](../predict/test_config.json)：

```json
{
  "prediction_date": "20260817",
  "prediction_start_date": "",
  "prediction_end_date": "",
  "lookback_days": 10,
  "request_timeout_seconds": 90,
  "rules": "预测规则和需要模型遵守的限制",
  "models": [
    {
      "name": "agent_name",
      "basemodel": "model_id",
      "enabled": true,
      "openai_base_url": "https://provider.example/v1",
      "openai_api_key": "",
      "api_key_env": "YOUR_PROVIDER_API_KEY",
      "json_mode": false,
      "temperature": 0.2
    }
  ]
}
```

只有 `enabled: true` 的模型会执行。模型接口使用 OpenAI 兼容的 `/chat/completions` 协议。脚本会自动加载项目根目录 `.env`，并根据 `api_key_env` 读取密钥。例如：

```dotenv
DEEPSEEK_API_KEY=your-deepseek-key
MOONSHOT_API_KEY=your-moonshot-key
NVIDIA_API_KEY=your-nvidia-key
```

`.env` 不要提交到 Git。只有确认供应商支持结构化输出时才将 `json_mode` 设为 `true`；如果供应商不支持 `response_format`，保持 `false`。

### 预测一段日期

将单日字段留空，填写起止日期即可：

```json
{
  "prediction_date": "",
  "prediction_start_date": "20260801",
  "prediction_end_date": "20260817"
}
```

测试脚本会从指数数据中找出该区间内的实际交易日，并逐日运行预测。每个交易日都会写入独立文件，例如：

```text
data/predict/DeepSeek-Chat/20260801.json
data/predict/DeepSeek-Chat/20260803.json
...
data/predict/DeepSeek-Chat/20260817.json
```

每个预测日仍只使用该日期之前的 `lookback_days` 个交易日；不会因为执行的是一个日期范围而把未来数据传给模型。日期范围会产生多次模型调用，请根据模型费用和接口频率合理设置范围。

## 7. 模型输出格式

模型必须返回一个 JSON 对象：

```json
{
  "direction": "up",
  "candle_class": "strong_up",
  "confidence": 72,
  "expected_pct_change": 1.1,
  "rationale": "基于近十日价格、振幅和成交量的预测依据",
  "market_analysis": "对大盘和相关板块的走势分析"
}
```

程序会检查四分类值、规范化方向和置信度，并将标准化结果写入最终文件。

## 8. 结果文件结构

结果保存为：

```text
data/predict/<安全化智能体名称>/20260817.json
```

文件包含：

```json
{
  "agent_name": "agent_name",
  "prediction_date": "20260817",
  "generated_at": "UTC 时间",
  "lookback_days": 10,
  "data_policy": "数据隔离说明",
  "predictions": [
    {
      "ts_code": "000001.SH",
      "name": "上证指数",
      "as_of_date": "20260814",
      "lookback": [],
      "prediction": {
        "direction": "up",
        "candle_class": "up",
        "confidence": 60,
        "expected_pct_change": 0.3,
        "rationale": "...",
        "market_analysis": "..."
      }
    }
  ]
}
```

## 9. 页面展示原理

预测页面调用：

```text
GET /predict-results
```

服务端只读取 `data/predict/<智能体名称>/*.json`，不会读取 `test_config.json`，因此不会向前端暴露模型密钥。

页面提供：

- 按二分类正确率排序的智能体总体排行榜（跨全部预测日期累计）。
- 总体二分类和四分类准确率、已验证数量、待验证数量和预测批次。
- 点击智能体后，右侧默认展示该智能体最近预测日的表现。
- 通过预测日期下拉框切换该智能体的其他预测批次。
- 指数预测列表。
- 上涨/下跌二分类标签。
- 四分类 K 线标签。
- 置信度和预期涨跌幅。
- 当前指数的预测依据和大盘/板块分析。

没有运行测试时页面显示空状态，而不会伪造预测结果。

## 10. 运行方法

1. 编辑 `predict/test_config.json`，填写模型信息并启用至少一个模型。
2. 在项目根目录运行：

   ```powershell
   python predict/run_test.py
   ```

3. 启动页面服务：

   ```powershell
   cd docs
   python bs_server.py
   ```

4. 打开：

   ```text
   http://127.0.0.1:8888/predict-competition.html
   ```

测试脚本只负责生成离线结果；页面刷新后即可读取新文件。
