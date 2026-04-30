// K线图表相关全局变量
let klinesChart = null;
let currentBenchmarkTimeSeries = null;
let klinesChartTooltip = null;
let candlestickSeriesInstance = null;

/**
 * 初始化 K线图表（Lightweight Charts）
 * 功能：创建 Lightweight Charts 实例并配置初始参数
 */
function initKlineChart() {
    console.log('[initKlineChart] 开始初始化 K线图表...');
    
    // 检查 Lightweight Charts 库是否已加载
    if (typeof LightweightCharts === 'undefined') {
        console.error('[initKlineChart] Lightweight Charts 库未加载');
        return false;
    }
    console.log('[initKlineChart] LightweightCharts 库已加载:', typeof LightweightCharts);

    const klinesContainer = document.getElementById('klinesChart');
    console.log('[initKlineChart] 容器元素:', klinesContainer);
    if (!klinesContainer) {
        console.error('[initKlineChart] 找不到 K线图表容器');
        return false;
    }

    // 检查容器大小 - 这很关键！
    let width = klinesContainer.offsetWidth;
    let height = klinesContainer.offsetHeight;
    console.log('[initKlineChart] 容器 offsetWidth:', width, 'offsetHeight:', height);
    
    // 如果容器尺寸为0，尝试从父容器获取
    if (width === 0 || height === 0) {
        const parentContainer = document.getElementById('klinesChartContainer');
        if (parentContainer) {
            width = parentContainer.offsetWidth || 1200;
            height = parentContainer.offsetHeight || 500;
            console.log('[initKlineChart] 使用父容器尺寸:', width, 'x', height);
        } else {
            // 如果都获取不到，使用默认值
            width = 1200;
            height = 500;
            console.log('[initKlineChart] 使用默认尺寸:', width, 'x', height);
        }
    }
    
    try {
        // 创建 Lightweight Charts 实例 - 必须显式指定宽高！
        klinesChart = LightweightCharts.createChart(klinesContainer, {
            width: width,
            height: height,
            layout: {
                textColor: '#e4e8ed',
                background: {color: '#1a2239'},
                fontFamily: 'system-ui, -apple-system, sans-serif'
            },
            timeScale: {
                timeVisible: false,
                secondsVisible: false,
                rightOffset: 12
            },
            rightPriceScale: {
                textColor: '#a0aec0',
            }
        });
        console.log('[initKlineChart] K线图表实例创建成功，尺寸:', width, 'x', height);
        return true;
    } catch (error) {
        console.error('[initKlineChart] 创建图表失败:', error);
        klinesChart = null;
        return false;
    }
}

/**
 * 创建或获取 K线图表的 Tooltip 元素
 * 功能：返回或创建用于显示K线详情的浮动提示框
 * @returns {HTMLElement} Tooltip 元素
 */
function getOrCreateKlineTooltip() {
    if (klinesChartTooltip) {
        return klinesChartTooltip;
    }

    const tooltip = document.createElement('div');
    tooltip.id = 'kline-tooltip';
    tooltip.style.cssText = `
        position: absolute;
        pointer-events: none;
        z-index: 100;
        background: rgba(26, 34, 57, 0.95);
        border: 1px solid rgba(100, 200, 255, 0.3);
        border-radius: 8px;
        padding: 12px;
        font-size: 12px;
        color: #e4e8ed;
        font-family: 'Courier New', monospace;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
        display: none;
        min-width: 180px;
        backdrop-filter: blur(4px);
    `;

    document.body.appendChild(tooltip);
    klinesChartTooltip = tooltip;
    return tooltip;
}

/**
 * 更新 K线 Tooltip 的位置和内容
 * @param {number} clientX - 鼠标 X 坐标
 * @param {number} clientY - 鼠标 Y 坐标
 * @param {Object} ohlcData - K线数据 {open, high, low, close, time}
 */
function updateKlineTooltip(clientX, clientY, ohlcData) {
    const tooltip = getOrCreateKlineTooltip();

    if (!ohlcData) {
        tooltip.style.display = 'none';
        return;
    }

    // 格式化价格
    const formatPrice = (price) => {
        return parseFloat(price).toFixed(2);
    };

    // 确定涨跌信息
    const change = ohlcData.close - ohlcData.open;
    const changePercent = ((change / ohlcData.open) * 100).toFixed(2);
    const changeColor = change >= 0 ? '#FF4444' : '#00B050'; // A股红涨绿跌
    const changeSymbol = change >= 0 ? '▲' : '▼';

    let html = `
        <div style="font-weight: bold; margin-bottom: 8px; color: #00d4ff;">
            ${ohlcData.time}
        </div>
        <div style="display: grid; gap: 4px;">
            <div>开盘 <span style="float: right; color: #6dd8ff;">${formatPrice(ohlcData.open)}</span></div>
            <div>最高 <span style="float: right; color: #F5C400;">${formatPrice(ohlcData.high)}</span></div>
            <div>最低 <span style="float: right; color: #f0dc8b;">${formatPrice(ohlcData.low)}</span></div>
            <div>收盘 <span style="float: right; color: #c19dff;">${formatPrice(ohlcData.close)}</span></div>
            <div style="border-top: 1px solid rgba(100, 200, 255, 0.2); padding-top: 4px; margin-top: 4px;">
                <span style="color: ${changeColor};">${changeSymbol} ${Math.abs(change).toFixed(2)}</span>
                <span style="float: right; color: ${changeColor};">(${changeSymbol}${Math.abs(changePercent)}%)</span>
            </div>
        </div>
    `;

    tooltip.innerHTML = html;
    tooltip.style.display = 'block';

    // 智能定位：避免超出视口
    const tooltipWidth = 180;
    const tooltipHeight = tooltip.offsetHeight;
    const padding = 10;

    let x = clientX + 15;
    let y = clientY - tooltipHeight - 15;

    // 检查右边界
    if (x + tooltipWidth + padding > window.innerWidth) {
        x = clientX - tooltipWidth - 15;
    }

    // 检查下边界
    if (y < padding) {
        y = clientY + 15;
    }

    // 检查左边界
    if (x < padding) {
        x = padding;
    }

    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
}

/**
 * 隐藏 K线 Tooltip
 */
function hideKlineTooltip() {
    if (klinesChartTooltip) {
        klinesChartTooltip.style.display = 'none';
    }
}

/**
 * 将时间序列数据转换为 OHLC 格式
 * 功能：从历史价格中提取每个日期的开高低收价
 * @param {Object} timeSeries - 时间序列数据 {日期: {价格字段}}
 * @returns {Array} OHLC 数据数组
 */
function convertToOHLC(timeSeries) {
    if (!timeSeries || Object.keys(timeSeries).length === 0) {
        console.warn('时间序列数据为空');
        return [];
    }

    const ohlcData = [];
    const dates = Object.keys(timeSeries).sort();

    for (const dateStr of dates) {
        const priceData = timeSeries[dateStr];
        
        // 提取价格字段（兼容多种字段名）
        const close = parseFloat(
            priceData['4. close'] || priceData['4. sell price'] || priceData['close'] || priceData['price'] || 0
        );
        
        const open = parseFloat(
            priceData['1. open'] || priceData['open'] || close
        );
        
        const high = parseFloat(
            priceData['2. high'] || priceData['high'] || close
        );
        
        const low = parseFloat(
            priceData['3. low'] || priceData['low'] || close
        );

        if (!isNaN(open) && !isNaN(high) && !isNaN(low) && !isNaN(close)) {
            ohlcData.push({
                time: dateStr,
                open: open,
                high: high,
                low: low,
                close: close
            });
        }
    }

    console.log(`转换后 OHLC 数据点数：${ohlcData.length}`);
    return ohlcData;
}

/**
 * 加载基准指数的 K线数据并显示
 * 功能：加载基准数据并绘制蜡烛图
 */
async function loadAndDisplayKline() {
    console.log('[loadAndDisplayKline] 开始执行...');
    
    if (!klinesChart) {
        console.error('[loadAndDisplayKline] K线图表未初始化，klinesChart 值:', klinesChart);
        return;
    }
    console.log('[loadAndDisplayKline] K线图表已初始化');
    
    // 确保图表有有效的尺寸
    const candleContainer = document.getElementById('klinesChart');
    const parentContainer = document.getElementById('klinesChartContainer');
    const currentWidth = candleContainer.offsetWidth;
    const currentHeight = parentContainer.offsetHeight;
    console.log('[loadAndDisplayKline] 当前图表容器尺寸:', currentWidth, 'x', currentHeight);
    
    // 如果容器尺寸为0，强制应用父容器的尺寸
    if (currentWidth === 0 || currentHeight === 0) {
        console.warn('[loadAndDisplayKline] 容器尺寸为0，应用默认或父容器尺寸');
        const w = currentWidth || parentContainer.offsetWidth || 1200;
        const h = currentHeight || parentContainer.offsetHeight || 500;
        try {
            klinesChart.applyOptions({ width: w, height: h });
            console.log('[loadAndDisplayKline] 已应用尺寸:', w, 'x', h);
        } catch (e) {
            console.error('[loadAndDisplayKline] 应用尺寸失败:', e);
        }
    }

    try {
        console.log('[loadAndDisplayKline] 开始加载基准指数 K线数据...');
        
        // 确保数据加载器已初始化
        await dataLoader.initialize();
        console.log('[loadAndDisplayKline] 数据加载器已初始化');

        // 获取基准数据（同时获取原始时间序列）
        // 需要直接加载基准数据的原始时间序列
        const marketConfig = dataLoader.getMarketConfig();
        console.log('[loadAndDisplayKline] 市场配置:', marketConfig);
        if (!marketConfig) {
            console.warn('[loadAndDisplayKline] 未能获取市场配置');
            return;
        }

        // 获取基准文件路径
        const benchmarkFile = marketConfig.benchmark_file || 'data/a_stock_data/sse_50_day/index_daily_sh000001.json';
        console.log('[loadAndDisplayKline] 将加载基准文件:', benchmarkFile);

        const fullPath = `${dataLoader.baseDataPath}/${benchmarkFile}`;
        console.log('[loadAndDisplayKline] 完整 URL:', fullPath);
        const response = await fetch(fullPath);
        if (!response.ok) {
            console.error('[loadAndDisplayKline] 基准文件加载失败，状态码:', response.status, '路径:', fullPath);
            return;
        }
        console.log('[loadAndDisplayKline] 基准文件加载成功，状态码:', response.status);

        const data = await response.json();
        console.log('[loadAndDisplayKline] JSON 数据加载成功，数据键:', Object.keys(data));

        // 获取时间序列
        let timeSeries = data['Time Series (Daily)'] || data['Time Series (60min)'];
        if (!timeSeries) {
            for (const k of Object.keys(data)) {
                if (k.toLowerCase().includes('time series')) {
                    timeSeries = data[k];
                    break;
                }
            }
        }

        console.log('[loadAndDisplayKline] 时间序列数据:', timeSeries ? '已获取，长度: ' + Object.keys(timeSeries).length : '未找到');
        if (!timeSeries) {
            console.error('[loadAndDisplayKline] 未找到时间序列数据，数据结构:', data);
            return;
        }

        currentBenchmarkTimeSeries = timeSeries;

        const ohlcData = convertToOHLC(timeSeries);
        if (ohlcData.length === 0) {
            console.error('[loadAndDisplayKline] 转换后没有数据!');
            return;  // 此时还没有 addCandlestickSeries，安全退出
        }

        // 移除旧系列（用全局引用，真正有效）
        if (candlestickSeriesInstance) {
            klinesChart.removeSeries(candlestickSeriesInstance);
            candlestickSeriesInstance = null;
        }

        // 创建新系列并保存到全局
        candlestickSeriesInstance = klinesChart.addCandlestickSeries({
            upColor: '#FF4444',
            downColor: '#00B050',
            borderUpColor: '#FF4444',
            borderDownColor: '#00B050',
            wickUpColor: '#FF4444',
            wickDownColor: '#00B050',
        });

        candlestickSeriesInstance.setData(ohlcData);
        // 创建蜡烛图 - A股配色：涨为红色，跌为绿色
      
       
        // ============ 添加鼠标悬停事件处理 ============
        // 订阅十字线移动事件（鼠标在图表上移动时触发）
        klinesChart.subscribeCrosshairMove((param) => {
            // 如果鼠标离开图表或没有指向数据点，隐藏tooltip
            if (param.point === undefined || param.time === undefined) {
                hideKlineTooltip();
                return;
            }

            // 从 candlestickSeries 的数据中查找对应时间的K线数据
            const ohlcItem = ohlcData.find(item => item.time === param.time);

            if (ohlcItem) {
                // 获取鼠标的客户端坐标
                const chartContainer = document.getElementById('klinesChart');
                const rect = chartContainer.getBoundingClientRect();
                const clientX = rect.left + param.point.x;
                const clientY = rect.top + param.point.y;

                // 更新并显示 Tooltip
                updateKlineTooltip(clientX, clientY, ohlcItem);
            } else {
                hideKlineTooltip();
            }
        });

        console.log('[loadAndDisplayKline] 已添加鼠标悬停事件处理');

        // 自适应视图
        console.log('[loadAndDisplayKline] 调整视图大小...');
        klinesChart.timeScale().fitContent();
        
        // 注册窗口大小变化事件处理器
        console.log('[loadAndDisplayKline] 注册窗口大小变化事件...');
        const handleResize = () => {
            try {
                const container = document.getElementById('klinesChartContainer');
                if (container && !container.classList.contains('hidden')) {
                    klinesChart.applyOptions({
                        width: container.offsetWidth,
                        height: container.offsetHeight
                    });
                }
            } catch (error) {
                // 忽略错误
            }
        };
        window.addEventListener('resize', handleResize);

        console.log('[loadAndDisplayKline] K线图表已绘制完成');

    } catch (error) {
        console.error('加载 K线数据失败:', error);
    }
}

/**
 * 在线性和 K线视图之间切换
 * 功能：隐藏线性图表，显示 K线视图；反之亦然
 */
function toggleBetweenCharts() {
    const assetChartContainer = document.getElementById('assetChartContainer');
    const klinesChartContainer = document.getElementById('klinesChartContainer');
    const klineBtn = document.getElementById('k-line-mode');

    console.log('[toggleBetweenCharts] ===== 开始执行 =====');
    console.log('[toggleBetweenCharts] assetChartContainer:', assetChartContainer);
    console.log('[toggleBetweenCharts] klinesChartContainer:', klinesChartContainer);
    console.log('[toggleBetweenCharts] klineBtn:', klineBtn);
    console.log('[toggleBetweenCharts] 当前 klinesChart 状态:', klinesChart);

    if (!assetChartContainer || !klinesChartContainer) {
        console.error('找不到图表容器。页面中的容器元素：');
        console.error('所有 div 元素：', document.querySelectorAll('div[id*="Chart"]'));
        return;
    }

    const isChartHidden = assetChartContainer.classList.contains('hidden');
    console.log('[toggleBetweenCharts] isChartHidden:', isChartHidden);

    if (isChartHidden) {
        // 当前显示的是 K线，切换回线性
        console.log('[toggleBetweenCharts] 执行切换逻辑：从 K线 切换到线性');
        assetChartContainer.classList.remove('hidden');
        klinesChartContainer.classList.add('hidden');
        klineBtn.textContent = 'K线视图';
        console.log('[toggleBetweenCharts] ✓ 已切换到线性图表');
    } else {
        // 当前显示的是线性，切换到 K线
        console.log('[toggleBetweenCharts] 执行切换逻辑：从线性 切换到 K线');
        assetChartContainer.classList.add('hidden');
        klinesChartContainer.classList.remove('hidden');
        klineBtn.textContent = '线性视图';
        console.log('[toggleBetweenCharts] HTML 类已更新');
        
        // 强制浏览器重排，使容器获得有效尺寸
        void klinesChartContainer.offsetHeight; // 触发重排
        console.log('[toggleBetweenCharts] 强制重排，容器尺寸:', 
            klinesChartContainer.offsetWidth, 'x', klinesChartContainer.offsetHeight);
        
        // 立即初始化或更新
        if (!klinesChart) {
            console.log('[toggleBetweenCharts] klinesChart 为空，执行初始化...');
            if (initKlineChart()) {
                console.log('[toggleBetweenCharts] 初始化成功，立即加载数据...');
                loadAndDisplayKline();
            } else {
                console.error('[toggleBetweenCharts] 初始化失败！');
            }
        } else {
            // K线图表已存在，更新其尺寸并重新载入数据
            console.log('[toggleBetweenCharts] klinesChart 已存在，应用父容器尺寸...');
            const w = klinesChartContainer.offsetWidth;
            const h = klinesChartContainer.offsetHeight;
            console.log('[toggleBetweenCharts] 应用尺寸:', w, 'x', h);
            try {
                klinesChart.applyOptions({ width: w, height: h });
                klinesChart.timeScale().fitContent();
                console.log('[toggleBetweenCharts] ✓ K线图表已更新');
                // 重新加载数据
                loadAndDisplayKline();
            } catch (error) {
                console.error('[toggleBetweenCharts] 更新K线时出错:', error);
            }
        }
    }
    console.log('[toggleBetweenCharts] ===== 执行完毕 =====');
}

/**
 * 响应市场切换时重新加载 K线数据
 * 功能：当用户切换市场时，如果 K线图表已显示，则重新加载对应市场的基准数据
 */

async function refreshKlineForNewMarket() {
    const klinesChartContainer = document.getElementById('klinesChartContainer');
    
    if (klinesChartContainer && !klinesChartContainer.classList.contains('hidden')) {
        console.log('市场已切换，重新加载 K线数据...');
        if (klinesChart) {
            klinesChart.remove();
            klinesChart = null;
            candlestickSeriesInstance = null;  // ← 加这一行
        }
        
        if (initKlineChart()) {
            await loadAndDisplayKline();
        }
    }
}
