// ============================================
// 资产变化图表 - 主页可视化
// ============================================

// 数据加载器实例
const dataLoader = new DataLoader();
window.dataLoader = dataLoader; // 导出到全局作用域供transaction-loader使用

// 当前图表实例
let chartInstance = null;

// 存储所有代理的数据
let allAgentsData = {};

// 是否采用对数刻度
let isLogScale = false;

// 当前选中的代理
let currentSelectedAgent = null;

// K线图表相关全局变量
let klinesChart = null;
let currentBenchmarkTimeSeries = null;
let klinesChartTooltip = null;

// ============ 配置 ============
// 不同代理的颜色调色板
const agentColors = [
    '#00d4ff', // 青蓝
    '#00ffcc', // 青色
    '#ff006e', // 热粉
    '#ffbe0b', // 黄色
    '#8338ec', // 紫色
    '#3a86ff', // 蓝色
    '#fb5607', // 橙色
    '#06ffa5'  // 薄荷
];

// SVG图像缓存
const iconImageCache = {};

// ============ 工具函数 ============

/**
 * 将SVG图标加载为图像对象
 * @param {string} iconPath - 图标路径
 * @returns {Promise} 返回图像对象的Promise
 */
function loadIconImage(iconPath) {
    return new Promise((resolve, reject) => {
        // 如果已缓存，直接返回
        if (iconImageCache[iconPath]) {
            resolve(iconImageCache[iconPath]);
            return;
        }
        
        // 创建新的图像对象
        const img = new Image();
        img.onload = () => {
            // 成功加载时缓存并返回
            iconImageCache[iconPath] = img;
            resolve(img);
        };
        img.onerror = reject;
        img.src = iconPath;
    });
}

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

        // 清空之前的蜡烛图
        if (klinesChart) {
            try {
                klinesChart.candlestickSeries?.forEach(series => {
                    klinesChart.removeSeries(series);
                });
            } catch (e) {
                // 忽略错误
            }
        }

        // 创建蜡烛图 - A股配色：涨为红色，跌为绿色
        const candlestickSeries = klinesChart.addCandlestickSeries({
            upColor: '#FF4444',      // 涨时红色（A股）
            downColor: '#00B050',    // 跌时绿色（A股）
            borderUpColor: '#FF4444',
            borderDownColor: '#00B050',
            wickUpColor: '#FF4444',
            wickDownColor: '#00B050',
        });

        // 转换为 OHLC 格式
        const ohlcData = convertToOHLC(timeSeries);
        
        console.log('[loadAndDisplayKline] K线数据转换完成，共', ohlcData.length, '个数据点');
        if (ohlcData.length === 0) {
            console.error('[loadAndDisplayKline] 转换后没有数据!');
            return;
        }
        
        // 设置蜡烛图数据
        console.log('[loadAndDisplayKline] 设置蜡烛图数据...');
        candlestickSeries.setData(ohlcData);
        console.log('[loadAndDisplayKline] 蜡烛图数据已设置');

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
    
    // 仅在 K线视图可见时刷新
    if (klinesChartContainer && !klinesChartContainer.classList.contains('hidden')) {
        console.log('市场已切换，重新加载 K线数据...');
        if (klinesChart) {
            klinesChart.remove();
            klinesChart = null;
        }
        
        if (initKlineChart()) {
            await loadAndDisplayKline();
        }
    }
}


/**
 * 根据当前市场更新副标题
 * 将前端市场ID映射到config.yaml中定义的市场key
 */
function updateMarketSubtitle() {
    console.log('[updateMarketSubtitle] 开始更新副标题...');
    
    let currentMarket = dataLoader.getMarket();
    console.log('[updateMarketSubtitle] 原始市场ID:', currentMarket);

    // 市场ID映射表 - 将前端的市场ID映射到config.yaml中的市场key
    const marketMapping = {
        'sse50':  'cn',        // 上证50 -> config.yaml markets.cn
        'zxg':    'cn_sxg',    // 自选股 -> config.yaml markets.cn_sxg
        'csi300': 'cn',        // 沪深300 -> config.yaml markets.cn
        'zz500':  'cn',        // 中证500 -> config.yaml markets.cn
        'gem':    'cn',        // 创业板指 -> config.yaml markets.cn
        'cn':     'cn',        // 上证50（默认）
        'cn_sxg': 'cn_sxg',    // 自选股
    };

    // 获取有效市场ID（如果有映射则使用映射值，否则使用原值）
    const effectiveMarket = marketMapping[currentMarket] || currentMarket;
    console.log('[updateMarketSubtitle] 映射后的市场ID:', effectiveMarket);

    // 获取市场配置信息
    const marketConfig = dataLoader.getMarketConfig(effectiveMarket);
    console.log('[updateMarketSubtitle] 市场配置:', marketConfig);

    // 获取副标题DOM元素
    const subtitleElement = document.getElementById('marketSubtitle');
    console.log('[updateMarketSubtitle] 副标题元素:', subtitleElement);

    // 更新副标题文本
    if (marketConfig && marketConfig.subtitle && subtitleElement) {
        subtitleElement.textContent = marketConfig.subtitle;
        console.log('副标题已更新为:', marketConfig.subtitle);
    } else {
        // 日志记录缺失的数据
        console.warn('[updateMarketSubtitle] 缺少必需数据:', {
            hasMarketConfig: !!marketConfig,
            hasSubtitle: marketConfig?.subtitle,
            hasElement: !!subtitleElement,
            usedMarket: effectiveMarket
        });

        // 显示默认副标题
        if (subtitleElement) {
            subtitleElement.textContent = "A股市场";
        }
    }
}

/**
 * 加载数据並刷新UI
 * 1. 初始化数据加载器
 * 2. 更新市场副标题
 * 3. 加载所有代理数据
 * 4. 预加载代理图标
 * 5. 创建图表、图例、排行楼、交易记录
 */
async function loadDataAndRefresh() {
    showLoading(); // 显示加载提示符

    try {
        // 确保数据配置已加载
        await dataLoader.initialize();

        // 更新当前市场的副标题
        updateMarketSubtitle();

        // 加载所有代理的一你数据
        console.log('正在加载所有代理的数据...');
        allAgentsData = await dataLoader.loadAllAgentsData();
        console.log('数据加载完成:', allAgentsData);

        // 预加载svg图标
        const agentNames = Object.keys(allAgentsData);
        const iconPromises = agentNames.map(agentName => {
            const iconPath = dataLoader.getAgentIcon(agentName);
            return loadIconImage(iconPath).catch(err => {
                console.warn(`为 ${agentName} 加载图标失败:`, err);
            });
        });
        await Promise.all(iconPromises);
        console.log('嚾标预加载完成');

        // 摒的存在的图表并等候一个氡0ms确保它完全销毁
        if (chartInstance) {
            console.log('需要删除旧图表...');
            chartInstance.destroy();
            chartInstance = null;
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        // 更新统计信息
        updateStats();

        // 创建图表
        createChart();

        // 创建嚾例
        createLegend();

        // 创建排行楼和交易记录
        await createLeaderboard();
        await createActionFlow();

    } catch (error) {
        console.error('加载数据失败:', error);
        alert('业务数据加载失败。请检查控制台是否有错误信息。');
    } finally {
        hideLoading(); // 隐藏加载提示符
    }
}

/**
 * 初始化页面
 * 1. 设置事件监听晨
 * 2. 加载初始数据
 * 3. 更新UI状态
 */
async function init() {
    // 需要首先设置事件监听晨才能收到用户外上改变
    setupEventListeners();

    // 加载初始数据
    await loadDataAndRefresh();
    
    // 初始化UI状态
    updateMarketUI();
}

/**
 * 更新统计信息卡片
 * 显示：代理数量、交易时间范围、最优业维、最优餞率
 */
function updateStats() {
    // 获取代理名称列表
    const agentNames = Object.keys(allAgentsData);
    const agentCount = agentNames.length;

    // 计算时间范围（最早与最晩知处）
    let minDate = null;
    let maxDate = null;

    agentNames.forEach(name => {
        const history = allAgentsData[name].assetHistory;
        if (history.length > 0) {
            const firstDate = history[0].date;
            const lastDate = history[history.length - 1].date;

            if (!minDate || firstDate < minDate) minDate = firstDate;
            if (!maxDate || lastDate > maxDate) maxDate = lastDate;
        }
    });

    // 找到最优业维（收益率最高）
    let bestAgent = null;
    let bestReturn = -Infinity;

    agentNames.forEach(name => {
        const returnValue = allAgentsData[name].return;
        if (returnValue > bestReturn) {
            bestReturn = returnValue;
            bestAgent = name;
        }
    });

    // 更新DOM元素
    document.getElementById('agent-count').textContent = agentCount;

    // 日期格式化函数 - 适配易时代戳
    const formatDateRange = (dateStr) => {
        if (!dateStr) return 'N/A';
        const date = new Date(dateStr);
        return date.toLocaleString('zh-CN', {year: 'numeric', month: 'numeric', day: 'numeric' });
    };

    // 更新交易时间范围
    document.getElementById('trading-period').textContent = minDate && maxDate ?
        `${formatDateRange(minDate)} 至 ${formatDateRange(maxDate)}` : 'N/A';
    
    // 从全路径提取代理名称用于检索
    const bestPerformerName = bestAgent ? bestAgent.split('/').pop() : null;
    document.getElementById('best-performer').textContent = bestPerformerName ?
        dataLoader.getAgentDisplayName(bestPerformerName) : 'N/A';
    document.getElementById('avg-return').textContent = bestAgent ?
        dataLoader.formatPercent(bestReturn) : 'N/A';
}

/**
 * 创建主嚾表
 * 特效：
 * - 收集所有代理的数据点
 * - 为Chart.js构建数据集
 * - 添加负责N标記的插件
 */
function createChart() {
    const ctx = document.getElementById('assetChart').getContext('2d');

    // Collect all unique dates and sort them
    const allDates = new Set();
    Object.keys(allAgentsData).forEach(agentName => {
        allAgentsData[agentName].assetHistory.forEach(h => allDates.add(h.date));
    });
    const sortedDates = Array.from(allDates).sort();

    console.log('=== CHART DEBUG ===');
    console.log('Total unique dates:', sortedDates.length);
    console.log('Date range:', sortedDates[0], 'to', sortedDates[sortedDates.length - 1]);
    console.log('Agent names:', Object.keys(allAgentsData));

    const datasets = Object.keys(allAgentsData).map((agentName, index) => {
        const data = allAgentsData[agentName];
        // agentName may be a full path like 'agent_data_astock/sse_50_day/glm-4.5-air'
        // extract the folder key expected by configLoader (e.g., 'glm-4.5-air')
        const folderKey = agentName.split('/').pop();
        let color, borderWidth, borderDash;

        // Special styling for benchmarks (check if name contains 'QQQ' or 'SSE')
        const isBenchmark = agentName.includes('QQQ') || agentName.includes('SSE');
        if (isBenchmark) {
            color = dataLoader.getAgentBrandColor(folderKey) || '#ff6b00';
            borderWidth = 2;
            borderDash = [5, 5]; // Dashed line for benchmark
        } else {
            color = dataLoader.getAgentBrandColor(folderKey) || agentColors[index % agentColors.length];
            borderWidth = 3;
            borderDash = [];
        }

        console.log(`[DATASET ${index}] ${agentName} => COLOR: ${color}, isBenchmark: ${isBenchmark}`);

        // Create data points for all dates, filling missing dates with null
        const chartData = sortedDates.map(date => {
            const historyEntry = data.assetHistory.find(h => h.date === date);
            return {
                x: date,
                y: historyEntry ? historyEntry.value : null
            };
        });

        console.log(`Dataset ${index} (${agentName}):`, {
            label: dataLoader.getAgentDisplayName(folderKey),
            dataPoints: chartData.filter(d => d.y !== null).length,
            color: color,
            isBenchmark: isBenchmark,
            sampleData: chartData.slice(0, 3)
        });

        // Detect if we have hourly data (many data points with time component)
        const isHourlyData = sortedDates.length > 50 && sortedDates[0].includes(':');

        const datasetObj = {
            // Use display name resolved from folder key
            label: dataLoader.getAgentDisplayName(folderKey),
            data: chartData,
            borderColor: color,
            backgroundColor: isBenchmark ? 'transparent' : createGradient(ctx, color), // Keep gradient for all
            borderWidth: borderWidth,
            borderDash: borderDash,
            tension: isHourlyData ? 0.45 : 0.4, // More smoothing for dense hourly data
            pointRadius: 0,
            pointHoverRadius: 7,
            pointHoverBackgroundColor: color,
            pointHoverBorderColor: '#fff',
            pointHoverBorderWidth: 3,
            fill: !isBenchmark, // Fill for all non-benchmark agents
            spanGaps: true, // Draw continuous lines even with missing data points
            segment: {
                borderColor: color,
            },
            // store folder key for later lookups in tooltip/legend
            agentFolder: folderKey,
            agentIcon: dataLoader.getAgentIcon(folderKey)
        };

        console.log(`[DATASET OBJECT ${index}] borderColor: ${datasetObj.borderColor}, pointHoverBackgroundColor: ${datasetObj.pointHoverBackgroundColor}`);

        return datasetObj;
    });

    // Create gradient for area fills
    function createGradient(ctx, color) {
        // Parse color and create gradient
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, color + '30'); // 30% opacity at top
        gradient.addColorStop(0.5, color + '15'); // 15% opacity at middle
        gradient.addColorStop(1, color + '05'); // 5% opacity at bottom
        return gradient;
    }

    // Custom plugin to draw icons on chart lines with pulsing animation
    const iconPlugin = {
        id: 'iconLabels',
        afterDatasetsDraw: (chart) => {
            const ctx = chart.ctx;
            const now = Date.now();

            chart.data.datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                if (!meta.hidden && dataset.data.length > 0) {
                    // Get the last point
                    const lastPoint = meta.data[meta.data.length - 1];

                    if (lastPoint) {
                        const x = lastPoint.x;
                        const y = lastPoint.y;

                        ctx.save();

                        // Calculate pulse animation values
                        const pulseSpeed = 1500; // milliseconds per cycle
                        const phase = ((now + datasetIndex * 300) % pulseSpeed) / pulseSpeed; // Offset each line
                        const pulse = Math.sin(phase * Math.PI * 2) * 0.5 + 0.5; // 0 to 1

                        // Draw animated ripple rings (outer glow effect)
                        for (let i = 0; i < 3; i++) {
                            const ripplePhase = ((now + datasetIndex * 300 + i * 500) % 2000) / 2000;
                            const rippleSize = 6 + ripplePhase * 20;
                            const rippleOpacity = (1 - ripplePhase) * 0.4;

                            ctx.strokeStyle = dataset.borderColor;
                            ctx.globalAlpha = rippleOpacity;
                            ctx.lineWidth = 2;
                            ctx.beginPath();
                            ctx.arc(x, y, rippleSize, 0, Math.PI * 2);
                            ctx.stroke();
                        }

                        ctx.globalAlpha = 1;

                        // Draw main pulsing point
                        const pointSize = 5 + pulse * 3;

                        // Outer glow
                        ctx.shadowColor = dataset.borderColor;
                        ctx.shadowBlur = 10 + pulse * 15;
                        ctx.fillStyle = dataset.borderColor;
                        ctx.beginPath();
                        ctx.arc(x, y, pointSize, 0, Math.PI * 2);
                        ctx.fill();

                        // Inner bright core
                        ctx.shadowBlur = 5;
                        ctx.fillStyle = '#ffffff';
                        ctx.beginPath();
                        ctx.arc(x, y, pointSize * 0.5, 0, Math.PI * 2);
                        ctx.fill();

                        // Reset shadow
                        ctx.shadowBlur = 0;

                        // Draw icon image with glow background (positioned to the right)
                        const iconSize = 30;
                        const iconX = x + 22;

                        // Icon background circle with glow
                        ctx.shadowColor = dataset.borderColor;
                        ctx.shadowBlur = 15;
                        ctx.fillStyle = dataset.borderColor;
                        ctx.beginPath();
                        ctx.arc(iconX, y, iconSize / 2, 0, Math.PI * 2);
                        ctx.fill();

                        // Reset shadow for icon
                        ctx.shadowBlur = 0;

                        // Draw icon image if loaded
                        if (iconImageCache[dataset.agentIcon]) {
                            const img = iconImageCache[dataset.agentIcon];
                            const imgSize = iconSize * 0.6; // Icon slightly smaller than circle
                            ctx.drawImage(img, iconX - imgSize/2, y - imgSize/2, imgSize, imgSize);
                        }

                        ctx.restore();
                    }
                }
            });

            // Request animation frame to continuously update the pulse effect
            requestAnimationFrame(() => {
                if (chart && !chart.destroyed) {
                    chart.update('none'); // Update without animation to maintain smooth pulse
                }
            });
        }
    };

    console.log('Creating chart with', datasets.length, 'datasets');
    console.log('Datasets summary:', datasets.map(d => ({
        label: d.label,
        borderColor: d.borderColor,
        backgroundColor: typeof d.backgroundColor === 'string' ? d.backgroundColor : 'GRADIENT',
        dataPoints: d.data.filter(p => p.y !== null).length,
        borderWidth: d.borderWidth,
        fill: d.fill
    })));

    // DEBUG: Log the actual Chart.js config
    console.log('[CHART.JS CONFIG] About to create chart with datasets:', JSON.stringify(
        datasets.map(d => ({ label: d.label, borderColor: d.borderColor }))
    ));

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            resizeDelay: 200,
            layout: {
                padding: {
                    right: 50,
                    top: 10,
                    bottom: 10
                }
            },
            interaction: {
                mode: 'index',
                intersect: false
            },
            elements: {
                line: {
                    borderJoinStyle: 'round',
                    borderCapStyle: 'round'
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: false,
                    external: function(context) {
                        // Custom HTML tooltip
                        const tooltipModel = context.tooltip;
                        let tooltipEl = document.getElementById('chartjs-tooltip');

                        // Create element on first render
                        if (!tooltipEl) {
                            tooltipEl = document.createElement('div');
                            tooltipEl.id = 'chartjs-tooltip';
                            tooltipEl.innerHTML = '<div class="tooltip-container"></div>';
                            document.body.appendChild(tooltipEl);
                        }

                        // Hide if no tooltip
                        if (tooltipModel.opacity === 0) {
                            tooltipEl.style.opacity = 0;
                            return;
                        }

                        // Set Text
                        if (tooltipModel.body) {
                            const dataPoints = tooltipModel.dataPoints || [];

                            // Sort data points by value at this time point (descending)
                            const sortedPoints = [...dataPoints].sort((a, b) => {
                                const valueA = a.parsed.y || 0;
                                const valueB = b.parsed.y || 0;
                                return valueB - valueA;
                            });

                            // Format title (date/time)
                            const titleLines = tooltipModel.title || [];
                            let titleHtml = '';
                            if (titleLines.length > 0) {
                                const dateStr = titleLines[0];
                                if (dateStr && dateStr.includes(':')) {
                                    const date = new Date(dateStr);
                                    titleHtml = date.toLocaleString('en-US', {
                                        month: 'short',
                                        day: 'numeric',
                                        year: 'numeric',
                                        hour: '2-digit',
                                        minute: '2-digit'
                                    });
                                } else {
                                    titleHtml = dateStr;
                                }
                            }

                            // Build body HTML with logos and ranked data
                            let innerHtml = `<div class="tooltip-title">${titleHtml}</div>`;
                            innerHtml += '<div class="tooltip-body">';

                            sortedPoints.forEach((dataPoint, index) => {
                                const dataset = dataPoint.dataset;
                                // dataset.label already contains the friendly display name
                                const displayName = dataset.label;
                                const value = dataPoint.parsed.y;
                                // Use stored agentFolder / agentIcon when available
                                const agentFolder = dataset.agentFolder || dataset.agentName || null;
                                const icon = dataset.agentIcon || (agentFolder ? dataLoader.getAgentIcon(agentFolder) : null);
                                const color = dataset.borderColor;

                                // Add ranking badge
                                const rankBadge = `<span class="rank-badge">#${index + 1}</span>`;

                                innerHtml += `
                                    <div class="tooltip-row">
                                        ${rankBadge}
                                        <img src="${icon}" class="tooltip-icon" alt="${displayName}">
                                        <span class="tooltip-label" style="color: ${color}">${displayName}</span>
                                        <span class="tooltip-value">${dataLoader.formatCurrency(value)}</span>
                                    </div>
                                `;
                            });

                            innerHtml += '</div>';

                            const container = tooltipEl.querySelector('.tooltip-container');
                            container.innerHTML = innerHtml;
                        }

                        const position = context.chart.canvas.getBoundingClientRect();
                        const tooltipWidth = tooltipEl.offsetWidth || 300;
                        const tooltipHeight = tooltipEl.offsetHeight || 200;

                        // Smart positioning to prevent overflow
                        let left = position.left + window.pageXOffset + tooltipModel.caretX;
                        let top = position.top + window.pageYOffset + tooltipModel.caretY;

                        // Offset to prevent covering the hover point
                        const offset = 15;
                        left += offset;
                        top -= offset;

                        // Check if tooltip would go off right edge
                        const viewportWidth = window.innerWidth;
                        const viewportHeight = window.innerHeight;

                        if (left + tooltipWidth > viewportWidth - 20) {
                            // Position to the left of the cursor instead
                            left = position.left + window.pageXOffset + tooltipModel.caretX - tooltipWidth - offset;
                        }

                        // Check if tooltip would go off bottom edge
                        if (top + tooltipHeight > viewportHeight - 20) {
                            top = viewportHeight - tooltipHeight - 20;
                        }

                        // Check if tooltip would go off top edge
                        if (top < 20) {
                            top = 20;
                        }

                        // Check if tooltip would go off left edge
                        if (left < 20) {
                            left = 20;
                        }

                        // Display, position, and set styles
                        tooltipEl.style.opacity = 1;
                        tooltipEl.style.position = 'absolute';
                        tooltipEl.style.left = left + 'px';
                        tooltipEl.style.top = top + 'px';
                        tooltipEl.style.pointerEvents = 'none';
                        tooltipEl.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
                        tooltipEl.style.transform = 'translateZ(0)'; // GPU acceleration
                    }
                }
            },
            scales: {
                x: {
                    type: 'category',
                    labels: sortedDates,
                    grid: {
                        color: 'rgba(45, 55, 72, 0.3)',
                        drawBorder: false,
                        lineWidth: 1
                    },
                    ticks: {
                        color: '#a0aec0',
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 15,
                        font: {
                            size: 11
                        },
                        callback: function(value, index) {
                            // Format hourly timestamps for better readability
                            const dateStr = this.getLabelForValue(value);
                            if (!dateStr) return '';

                            // If it's an hourly timestamp (contains time)
                            if (dateStr.includes(':')) {
                                const date = new Date(dateStr);
                                // Show date and hour
                                const month = (date.getMonth() + 1).toString().padStart(2, '0');
                                const day = date.getDate().toString().padStart(2, '0');
                                const hour = date.getHours().toString().padStart(2, '0');
                                return `${month}/${day} ${hour}:00`;
                            }
                            return dateStr;
                        }
                    }
                },
                y: {
                    type: isLogScale ? 'logarithmic' : 'linear',
                    grid: {
                        color: 'rgba(45, 55, 72, 0.3)',
                        drawBorder: false,
                        lineWidth: 1
                    },
                    ticks: {
                        color: '#a0aec0',
                        callback: function(value) {
                            return dataLoader.formatCurrency(value);
                        },
                        font: {
                            size: 11
                        }
                    }
                }
            }
        },
        plugins: [iconPlugin]
    });
}

/**
 * 创建嚾例
 * 显示每个代理的名称、颜色与收益率
 */
function createLegend() {
    const legendContainer = document.getElementById('agentLegend');
    legendContainer.innerHTML = '';

    Object.keys(allAgentsData).forEach((agentName, index) => {
        const data = allAgentsData[agentName];
        let color, borderStyle;
        // Extract folder key for lookups
        const folderKey = agentName.split('/').pop();

        // Special styling for benchmarks (check if name contains 'QQQ' or 'SSE')
        const isBenchmark = folderKey.includes('QQQ') || folderKey.includes('SSE') || agentName.includes('QQQ') || agentName.includes('SSE');
        if (isBenchmark) {
            color = dataLoader.getAgentBrandColor(folderKey) || '#ff6b00';
            borderStyle = 'dashed';
        } else {
            color = dataLoader.getAgentBrandColor(folderKey) || agentColors[index % agentColors.length];
            borderStyle = 'solid';
        }

        console.log(`[LEGEND ${index}] ${agentName} => COLOR: ${color}, isBenchmark: ${isBenchmark}`);
        
        const returnValue = data.return;
        const returnClass = returnValue >= 0 ? 'positive' : 'negative';
        const iconPath = dataLoader.getAgentIcon(folderKey);
        const brandColor = dataLoader.getAgentBrandColor(folderKey);

        const legendItem = document.createElement('div');
        legendItem.className = 'legend-item';
        const legendDisplayName = dataLoader.getAgentDisplayName(folderKey);
        const legendIcon = dataLoader.getAgentIcon(folderKey);
        const legendBrandColor = dataLoader.getAgentBrandColor(folderKey) || brandColor;
        legendItem.innerHTML = `
            <div class="legend-icon" ${legendBrandColor ? `style="background: ${legendBrandColor}20;"` : ''}>
                <img src="${legendIcon}" alt="${folderKey}" class="legend-icon-img" />
            </div>
            <div class="legend-color" style="background: ${color}; border-style: ${borderStyle};"></div>
            <div class="legend-info">
                <div class="legend-name">${legendDisplayName}</div>
                <div class="legend-return ${returnClass}">${dataLoader.formatPercent(returnValue)}</div>
            </div>
        `;

        legendContainer.appendChild(legendItem);
    });
}

/**
 * 切换线性/对数刻度
 * 点击按预一次会切换Y轴的刻度（线性⇄对数）
 */
function toggleScale() {
    isLogScale = !isLogScale;

    const button = document.getElementById('toggle-log');
    button.textContent = isLogScale ? '对数刻度' : '线性刻度';

    // Update chart
    if (chartInstance) {
        chartInstance.destroy();
    }
    createChart();
}




/**
 * 将嚾表数据导出为CSV文件
 * 包含整个时间段内所有代理的资产价值
 */
function exportData() {
    let csv = 'Date,';

    // Header row with agent names
    const agentNames = Object.keys(allAgentsData);
    csv += agentNames.map(name => {
        const folderKey = name.split('/').pop();
        return dataLoader.getAgentDisplayName(folderKey);
    }).join(',') + '\n';

    // Collect all unique dates
    const allDates = new Set();
    agentNames.forEach(name => {
        allAgentsData[name].assetHistory.forEach(h => allDates.add(h.date));
    });

    // Sort dates
    const sortedDates = Array.from(allDates).sort();

    // Data rows
    sortedDates.forEach(date => {
        const row = [date];
        agentNames.forEach(name => {
            const history = allAgentsData[name].assetHistory;
            const entry = history.find(h => h.date === date);
            row.push(entry ? entry.value.toFixed(2) : '');
        });
        csv += row.join(',') + '\n';
    });

    // Download CSV
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'aitrader_asset_evolution.csv';
    a.click();
    window.URL.revokeObjectURL(url);
}

/**
 * 根据当前市场更新UI状态
 * 操作：
 * - 更新按钱的活动状态
 * - 显示/隐藏粗度加简化设置
 * - 更新下拉单选择项
 */
function updateMarketUI() {
    const currentMarket = dataLoader.getMarket();
    const usBtn = document.getElementById('usMarketBtn');
    const cnBtn = document.getElementById('cnMarketBtn');
    const granularityWrapper = document.getElementById('granularityWrapper');
    const dailyBtn = document.getElementById('dailyBtn');
    const hourlyBtn = document.getElementById('hourlyBtn');
    const marketSelector = document.getElementById('marketSelector');

    // Reset all active states
    if (usBtn) usBtn.classList.remove('active');
    if (cnBtn) cnBtn.classList.remove('active');
    if (dailyBtn) dailyBtn.classList.remove('active');
    if (hourlyBtn) hourlyBtn.classList.remove('active');

    // Update dropdown selector to match current market
    if (marketSelector) {
        marketSelector.value = currentMarket;
    }

    if (currentMarket === 'us') {
        if (usBtn) usBtn.classList.add('active');
        if (granularityWrapper) granularityWrapper.classList.add('hidden');
    } else {
        // Both 'cn' and 'cn_hour' keep the main CN button active
        if (cnBtn) cnBtn.classList.add('active');
        if (granularityWrapper) granularityWrapper.classList.remove('hidden');
        
        if (currentMarket === 'cn_hour') {
            if (hourlyBtn) hourlyBtn.classList.add('active');
        } else {
            if (dailyBtn) dailyBtn.classList.add('active');
        }
    }
    
    updateMarketSubtitle();
}

/**
 * 设置所有不市场切换、涾度切换、数据导出等不件
 * 事件监听晨的中心
 */
function setupEventListeners() {
    console.log('[setupEventListeners 调试] 开始绑定事件监听器...');
    
    // K线视图切换按钮
    const klineModeBtn = document.getElementById('k-line-mode');
    console.log('[K线按钮] 找到的按钮元素:', klineModeBtn);
    
    if (klineModeBtn) {
        console.log('[K线按钮] 成功绑定点击事件');
        klineModeBtn.addEventListener('click', toggleBetweenCharts);
    } else {
        console.error('[K线按钮] 未找到 id="k-line-mode" 的按钮元素');
        // 尝试通过其他方式查找按钮
        const allButtons = document.querySelectorAll('button');
        console.log('[K线按钮] 页面中所有按钮:', allButtons);
        allButtons.forEach((btn, idx) => {
            console.log(`按钮 ${idx}:`, btn.id, btn.textContent);
        });
    }
    
    document.getElementById('toggle-log').addEventListener('click', toggleScale);
    document.getElementById('export-chart').addEventListener('click', exportData);

    // Market switching
    const usMarketBtn = document.getElementById('usMarketBtn');
    const cnMarketBtn = document.getElementById('cnMarketBtn');
    
    // Granularity switching
    const dailyBtn = document.getElementById('dailyBtn');
    const hourlyBtn = document.getElementById('hourlyBtn');

    if (usMarketBtn) {
        usMarketBtn.addEventListener('click', async () => {
            if (dataLoader.getMarket() !== 'us') {
                dataLoader.setMarket('us');
                updateMarketUI();
                await loadDataAndRefresh();
            }
        });
    }

    if (cnMarketBtn) {
        cnMarketBtn.addEventListener('click', async () => {
            const current = dataLoader.getMarket();
            // If not currently in any CN mode, switch to default CN (Hourly)
            if (current !== 'cn' && current !== 'cn_hour') {
                dataLoader.setMarket('cn_hour');
                updateMarketUI();
                await loadDataAndRefresh();
            }
        });
    }

    if (dailyBtn) {
        dailyBtn.addEventListener('click', async () => {
            if (dataLoader.getMarket() !== 'cn') {
                dataLoader.setMarket('cn');
                updateMarketUI();
                await loadDataAndRefresh();
            }
        });
    }

    if (hourlyBtn) {
        hourlyBtn.addEventListener('click', async () => {
            if (dataLoader.getMarket() !== 'cn_hour') {
                dataLoader.setMarket('cn_hour');
                updateMarketUI();
                await loadDataAndRefresh();
            }
        });
    }

    // Market selector change event (new dropdown)
    const marketSelector = document.getElementById('marketSelector');
    if (marketSelector) {
        marketSelector.addEventListener('change', async (e) => {
            const selectedMarket = e.target.value;  // 'sse50', 'zxg', 'csi300', etc.
            console.log('[marketSelector] Selected:', selectedMarket);
            
            if (dataLoader.getMarket() !== selectedMarket) {
                dataLoader.setMarket(selectedMarket);  // 设置前端市场 ID
                updateMarketUI();
                await loadDataAndRefresh();  // 重新加载数据
                
                // 若K线图表已显示，则刷新K线数据
                await refreshKlineForNewMarket();
            }
        });
    }

    // Scroll to top button
    const scrollBtn = document.getElementById('scrollToTop');
    window.addEventListener('scroll', () => {
        if (window.pageYOffset > 300) {
            scrollBtn.classList.add('visible');
        } else {
            scrollBtn.classList.remove('visible');
        }
    });

    scrollBtn.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Window resize handler for chart responsiveness
    let resizeTimeout;
    const handleResize = () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            if (chartInstance) {
                console.log('Resizing chart...'); // Debug log
                chartInstance.resize();
                chartInstance.update('none'); // Force update without animation
            }
        }, 100); // Faster response
    };

    window.addEventListener('resize', handleResize);

    // Also handle orientation change for mobile
    window.addEventListener('orientationchange', handleResize);
}

/**
 * 创建不行排同
 * 显示排名、嚾标、收賊不增率
 * 点击排行楼项目会载入该代理的交易记录
 */
async function createLeaderboard() {
    const leaderboard = await window.transactionLoader.buildLeaderboard(allAgentsData);
    const container = document.getElementById('leaderboardList');
    container.innerHTML = '';

    leaderboard.forEach((item, index) => {
        const rankClass = index === 0 ? 'first' : index === 1 ? 'second' : index === 2 ? 'third' : '';
        const gainClass = item.gain >= 0 ? 'positive' : 'negative';

        const itemEl = document.createElement('div');
        itemEl.className = 'leaderboard-item';
        itemEl.style.animationDelay = `${index * 0.05}s`;
        itemEl.innerHTML = `
            <div class="leaderboard-rank ${rankClass}">#${item.rank}</div>
            <div class="leaderboard-icon">
                <img src="${item.icon}" alt="${item.displayName}">
            </div>
            <div class="leaderboard-info">
                <div class="leaderboard-name">${item.displayName}</div>
                <div class="leaderboard-value">${window.transactionLoader.formatCurrency(item.currentValue)}</div>
            </div>
            <div class="leaderboard-gain">
                <div class="gain-amount ${gainClass}">${window.transactionLoader.formatCurrency(item.gain)}</div>
                <div class="gain-percent ${gainClass}">${window.transactionLoader.formatPercent(item.gainPercent)}</div>
            </div>
        `;

        container.appendChild(itemEl);

        // 新添加：点击选择代理
        itemEl.addEventListener('click', () => {selectAgent(item.agentName);});
    });
}

/**
 * 选择一个代理
 * 加载该代理的交易记录不载入交易时間线
 */
async function selectAgent(agentName) {
    currentSelectedAgent = agentName;

    // 更新 Action Flow
    await loadAgentActions(agentName);

    // 新增：更新最近交易记录（时间线）
    await updateTradeHistory(agentName);

    // 展开两个栏目（如果折叠）
    document.getElementById('actionList').classList.remove('collapsed');

    // 展开下方最近交易记录（时间线）
    document.getElementById('tradeTimeline').classList.remove('collapsed');
}

// Create action flow with pagination
let actionFlowState = {
    allTransactions: [],
    loadedCount: 0,
    pageSize: 20,
    maxTransactions: 500,
    isLoading: false,
    container: null
};

/**
 * 创建不行记录容器不铺设储、下拉加载、折叠非闻
 */
async function createActionFlow() {
    // Load all transactions
    //await window.transactionLoader.loadAllTransactions();
    //actionFlowState.allTransactions = window.transactionLoader.getMostRecentTransactions(100);
    actionFlowState.container = document.getElementById('actionList');
    actionFlowState.container.innerHTML = '<div class="no-selection-message">智能体交易记录</div>';
    actionFlowState.loadedCount = 0;


    //await loadMoreTransactions(); // Load initial batch
    // setupScrollListener();     // Set up scroll listener

    // 新添加：折叠事件
    const actionHeader = document.getElementById('actionFlowHeader');
    actionHeader.addEventListener('click', () => {
        const list = document.getElementById('actionList');
        list.classList.toggle('collapsed');
        const icon = actionHeader.querySelector('.collapse-icon');
        icon.textContent = list.classList.contains('collapsed') ? '▼' : '▲';
    });

    // 类似为 Trading Log 添加折叠
    const logHeader = document.getElementById('tradingLogHeader');
    if (logHeader) {
        logHeader.addEventListener('click', () => {
            const content = document.querySelector('.trading-log-content');  // 或 id="tradingLogContent"
            content.classList.toggle('collapsed');
            const icon = logHeader.querySelector('.collapse-icon');
            icon.textContent = content.classList.contains('collapsed') ? '▼' : '▲';
        });
    }
}

async function loadAgentActions(agentName) {
    const market = dataLoader.getMarket();
    const transactions = await window.transactionLoader.loadAgentTransactions(agentName, market);
    
    // 排序 desc by date
    transactions.sort((a, b) => new Date(b.date) - new Date(a.date));

    const container = actionFlowState.container;
    container.innerHTML = '';  // 清空

    if (transactions.length === 0) {
        container.innerHTML = '<div class="no-transactions">该智能体暂无交易记录</div>';
        return;
    }

    for (const transaction of transactions) {
        const displayName = window.configLoader.getDisplayName(agentName, market);
        const icon = window.configLoader.getIcon(agentName, market);
        const actionClass = transaction.action;
        const stockName = dataLoader.getStockName(transaction.symbol);
        const thinking = await window.transactionLoader.loadAgentThinking(agentName, transaction.date, market);

        const cardEl = document.createElement('div');
        cardEl.className = 'action-card';

        let cardHTML = `
            <div class="action-header">
                <div class="action-agent-icon">
                    <img src="${icon}" alt="${displayName}">
                </div>
                <div class="action-meta">
                    <div class="action-agent-name">${displayName}</div>
                    <div class="action-details">
                        <span class="action-type ${actionClass}"> ${transaction.action}</span>
                        <span class="action-symbol">${transaction.symbol}-(${stockName})</span>
                        <span>×${transaction.amount}</span>
                    </div>
                </div>
                <div class="action-timestamp">${window.transactionLoader.formatDateTime(transaction.date)}</div>
            </div>
        `;

        if (thinking !== null) {
            cardHTML += `
            <div class="action-body">
                <div class="action-thinking-label">
                    <span class="thinking-icon">🧠</span>
                    Agent Reasoning
                </div>
                <div class="action-thinking">${formatThinking(thinking)}</div>
            </div>
            `;
        }

        cardEl.innerHTML = cardHTML;
        container.appendChild(cardEl);
    }
}

/**
 * 下拉加载更多交易记录
 * 使用分段加载来优化性能
 */
async function loadMoreTransactions() {
    if (actionFlowState.isLoading) return;
    if (actionFlowState.loadedCount >= actionFlowState.allTransactions.length) return;
    if (actionFlowState.loadedCount >= actionFlowState.maxTransactions) return;

    actionFlowState.isLoading = true;

    // Show loading indicator
    showLoadingIndicator();

    // Calculate how many to load
    const startIndex = actionFlowState.loadedCount;
    const endIndex = Math.min(
        startIndex + actionFlowState.pageSize,
        actionFlowState.allTransactions.length,
        actionFlowState.maxTransactions
    );

    // Load this batch
    for (let i = startIndex; i < endIndex; i++) {
        const transaction = actionFlowState.allTransactions[i];
        const agentName = transaction.agentFolder;
        const currentMarket = dataLoader.getMarket();
        const displayName = window.configLoader.getDisplayName(agentName, currentMarket);
        const icon = window.configLoader.getIcon(agentName, currentMarket);
        const actionClass = transaction.action;
        const stockName = dataLoader.getStockName(transaction.symbol);

        // Load agent's thinking
        const thinking = await window.transactionLoader.loadAgentThinking(agentName, transaction.date, currentMarket);

        const cardEl = document.createElement('div');
        cardEl.className = 'action-card';
        cardEl.style.animationDelay = `${(i % actionFlowState.pageSize) * 0.03}s`;

        // Build card HTML - only include reasoning section if thinking is available
        let cardHTML = `
            <div class="action-header">
                <div class="action-agent-icon">
                    <img src="${icon}" alt="${displayName}">
                </div>
                <div class="action-meta">
                    <div class="action-agent-name">${displayName}</div>
                    <div class="action-details">
                        <span class="action-type ${actionClass}">${transaction.action}</span>
                        <span class="action-symbol">${transaction.symbol}-(${stockName})</span>
                        <span>×${transaction.amount}</span>
                    </div>
                </div>
                <div class="action-timestamp">${window.transactionLoader.formatDateTime(transaction.date)}</div>
            </div>
        `;

        // Only add reasoning section if thinking is available
        if (thinking !== null) {
            cardHTML += `
            <div class="action-body">
                <div class="action-thinking-label">
                    <span class="thinking-icon">🧠</span>
                    Agent Reasoning
                </div>
                <div class="action-thinking">${formatThinking(thinking)}</div>
            </div>
            `;
        }

        cardEl.innerHTML = cardHTML;

        // Remove the status note and loading indicator before adding new cards
        const existingNote = actionFlowState.container.querySelector('.transactions-status-note');
        if (existingNote) {
            existingNote.remove();
        }
        const existingLoader = actionFlowState.container.querySelector('.transactions-loading');
        if (existingLoader) {
            existingLoader.remove();
        }

        actionFlowState.container.appendChild(cardEl);
    }

    actionFlowState.loadedCount = endIndex;
    actionFlowState.isLoading = false;

    // Hide loading indicator and add status note
    hideLoadingIndicator();
    updateStatusNote();
}

/**
 * 显示加载提示符
 */
function showLoadingIndicator() {
    // Remove existing indicator
    const existingLoader = actionFlowState.container.querySelector('.transactions-loading');
    if (existingLoader) {
        existingLoader.remove();
    }

    const loaderEl = document.createElement('div');
    loaderEl.className = 'transactions-loading';
    loaderEl.style.cssText = 'text-align: center; padding: 1.5rem; color: var(--accent); font-size: 0.9rem; font-weight: 500;';
    loaderEl.innerHTML = '⏳ Loading more transactions...';
    actionFlowState.container.appendChild(loaderEl);
}

/**
 * 隐藏加载提示符
 */
function hideLoadingIndicator() {
    const existingLoader = actionFlowState.container.querySelector('.transactions-loading');
    if (existingLoader) {
        existingLoader.remove();
    }
}

/**
 * 更新交易记录页面下方的状态接条
 */
function updateStatusNote() {
    // Remove existing note
    const existingNote = actionFlowState.container.querySelector('.transactions-status-note');
    if (existingNote) {
        existingNote.remove();
    }

    // Add new note
    const noteEl = document.createElement('div');
    noteEl.className = 'transactions-status-note';
    noteEl.style.cssText = 'text-align: center; padding: 1.5rem; color: var(--text-muted); font-size: 0.9rem;';

    const totalAvailable = actionFlowState.allTransactions.length;
    const loaded = actionFlowState.loadedCount;

    if (loaded >= actionFlowState.maxTransactions || loaded >= totalAvailable) {
        // We've loaded everything we can
        if (totalAvailable > actionFlowState.maxTransactions) {
            noteEl.textContent = `Showing the most recent ${loaded} of ${totalAvailable} total transactions`;
        } else {
            noteEl.textContent = `Showing all ${loaded} recent transactions`;
        }
    } else {
        // More to load
        noteEl.textContent = `Loaded ${loaded} of ${Math.min(totalAvailable, actionFlowState.maxTransactions)} transactions. Scroll down to load more...`;
    }

    actionFlowState.container.appendChild(noteEl);
}

/**
 * 设置了载入里前的下拉监听晨
 */
function setupScrollListener() {
    const container = actionFlowState.container;
    let ticking = false;

    const checkScroll = () => {
        const scrollTop = container.scrollTop;
        const scrollHeight = container.scrollHeight;
        const clientHeight = container.clientHeight;

        // Trigger load when user is within 300px of bottom
        if (scrollHeight - (scrollTop + clientHeight) < 300) {
            if (!actionFlowState.isLoading &&
                actionFlowState.loadedCount < actionFlowState.maxTransactions &&
                actionFlowState.loadedCount < actionFlowState.allTransactions.length) {
                loadMoreTransactions();
            }
        }

        ticking = false;
    };

    // Listen to the container's scroll, not window scroll
    container.addEventListener('scroll', () => {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                checkScroll();
            });
            ticking = true;
        }
    });
}

/**
 * 格式化思考文本（将换行或列表怍成段落）
 */
function formatThinking(text) {
    // Split by double newlines or numbered lists
    const paragraphs = text.split(/\n\n+/).filter(p => p.trim());

    if (paragraphs.length === 0) {
        return `<p>${text}</p>`;
    }

    return paragraphs.map(p => `<p>${p.trim()}</p>`).join('');
}

/**
 * 显示减斗㛢叠层罩（整个页面的加载信号）
 */
function showLoading() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
}

/**
 * 隐藏斠布叠层
 */
function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

/**
 * 更新指定代理的交易历史信息时间线
 * 改进：验证日期格式、处理价格缺失
 */
async function updateTradeHistory(agentName) {
    const timeline = document.getElementById('tradeTimeline');
    if (!timeline) return;

    timeline.innerHTML = '<div class="loading-trades">加载中...</div>';

    try {
        const market = dataLoader.getMarket();
        const transactions = await window.transactionLoader.loadAgentTransactions(agentName, market);

        // 按时间降序排序（最新在前）
        transactions.sort((a, b) => new Date(b.date) - new Date(a.date));

        // 取最近 20 条
        const recentTrades = transactions.slice(0, 20);

        timeline.innerHTML = '';

        if (recentTrades.length === 0) {
            timeline.innerHTML = '<div class="no-trades">该智能体暂无交易记录</div>';
            return;
        }

        recentTrades.forEach(trade => {
            const stockName = dataLoader.getStockName(trade.symbol) || trade.symbol;
            const actionClass = trade.action.toLowerCase();

            // 关键修复1：自定义日期格式，强制带年份
            const tradeDate = new Date(trade.date);
            let formattedDate;
            if (market === 'cn_hour' || trade.date.includes(':')) {
                // 小时级别：2025-10-01 10:00 → 2025/10/01 10:00
                formattedDate = tradeDate.getFullYear() + '/' +
                                String(tradeDate.getMonth() + 1).padStart(2, '0') + '/' +
                                String(tradeDate.getDate()).padStart(2, '0') + ' ' +
                                String(tradeDate.getHours()).padStart(2, '0') + ':' +
                                String(tradeDate.getMinutes()).padStart(2, '0');
            } else {
                // 日级别：只显示年/月/日
                formattedDate = tradeDate.getFullYear() + '/' +
                                String(tradeDate.getMonth() + 1).padStart(2, '0') + '/' +
                                String(tradeDate.getDate()).padStart(2, '0');
            }

            // 关键修复2：安全获取价格，优先使用 price，其次 avg_price 或执行价格字段
            let price = 0;
            if (trade.price !== undefined && trade.price !== null) {
                price = trade.price;
            } 
            // 如果仍为0，可显示 “--” 更友好
            const priceDisplay = price > 0 ? dataLoader.formatCurrency(price) : '--';

            const tradeEl = document.createElement('div');
            tradeEl.className = `trade-event ${actionClass}`;

            tradeEl.innerHTML = `
                <div class="trade-dot"></div>
                <div class="trade-content">
                    <div class="trade-header">
                        <span class="trade-action">${trade.action.toUpperCase()}</span>
                        <span class="trade-symbol">${trade.symbol}</span>
                        <span class="trade-amount">×${trade.amount}</span>
                    </div>
                    <div class="trade-details">
                        <span class="trade-date">${formattedDate}</span>
                        <span class="trade-price">@ ${priceDisplay}</span>
                        <span class="trade-stock-name">(${stockName})</span>
                    </div>
                </div>
            `;

            timeline.appendChild(tradeEl);
        });
    } catch (error) {
        console.error('Failed to load trade history:', error);
        timeline.innerHTML = '<div class="no-trades">加载失败，请检查控制台</div>';
    }
}

// ============================================
// 页面初始化入口
// ============================================
// 当页面加载完毕后自动初始化应用
window.addEventListener('DOMContentLoaded', init);

