### 新增k线视图切换
#### 时间: 2026-4-28
  
   #### 功能简述:
 1. 点击按钮切换对应市场下k线数据
 2. 使用鼠标滚轮可对k线图进行放缩
 3. 光标悬浮在k线图上将显示某日具体数据

   #### 代码实现:
  1. 新增`candle-chart.js`封装k线功能
  2. 修改`asset-chart.js`绑定k线切换按钮监听

   #### 代码细节:
  1. 触发逻辑:  `asset-chart.js .setupEventListeners()`
     ```
     点击「基准K线」按钮调用 toggleBetweenCharts()
     下拉框切换市场时调用 loadDataAndRefresh() + refreshKlineForNewMarket()
     ```

  2. 判断函数: `candle-chart.js .toggleBetweenCharts()`
     ```
     该函数通过检查assetChartContainer.classList.contains('hidden') 来判断当前模式,
     切到K线时先强制 void klinesChartContainer.offsetHeight 触发重排使容器获得真实尺寸，再判断 klinesChart 是否为 null 决定走初始化还是直接刷新。
     ```

  3. 初始化: `initKlineChart()`
     ```
     先读 #klinesChart 的 offsetWidth/H，若为 0（容器处于 hidden 状态时 offsetWidth 就是 0）则 fallback 到父容器尺寸，最终 fallback 到 1200×500。然后调用 LightweightCharts.createChart() 并把实例存进全局变量 klinesChart。
     ```

  4. 数据加载: `loadAndDisplayKline()`
     ```
     路径拼接逻辑：dataLoader.getMarketConfig() 
     → 读 benchmark_file 字段
     → 拼成 {baseDataPath}/{benchmarkFile} 
     → fetch 
     → response.json() 
     → 提取 "Time Series (Daily)" 键和其他包含 time series 的键名
     ```

  5. 格式转换: `convertToOHLC()`
     ```
     对 timeSeries 的所有日期 key 排序，逐条提取价格
     缺失时都 fallback 到 close，保证不会产生 NaN
     最终返回 [{time: 'YYYY-MM-DD', open, high, low, close}] 数组
     ```

  6. 渲染:
     ```
     使用全局的 candlestickSeriesInstance 保存系列引用
     每次调用前先 removeSeries(旧实例)，再 addCandlestickSeries
     然后 setData(ohlcData) + fitContent() 自适应视图
     同时注册一个 window.resize 处理器调用 applyOptions({width, height})
     ```
  7. ToolTip:
     ```
     subscribeCrosshairMove() 监听十字线移动，
     通过 ohlcData.find(item => item.time === param.time) 找到当前数据点，计算坐标 clientX = rect.left + param.point.x，
     再交给 updateKlineTooltip() 渲染开高低收 + 涨跌幅，并做四边视口边界检测避免 tooltip 超出屏幕
     ```

            