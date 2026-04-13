// 数据加载器（Data Loader）
// 负责加载、处理并转换交易及价格数据以供前端显示
// 支持 A 股（合并文件）与美股（逐只文件）两类数据源
// 常见路径示例：./data/a_stock_data/sse_50_day, ./data/agent_data_astock/sse_50_day/glm-4.5-air

class DataLoader {
    constructor() {
        // 缓存所有 agent 的处理后数据（按 agent 名称）
        this.agentData = {};
        // 缓存价格时间序列，key 为 symbol
        this.priceCache = {};
        // 配置对象（从 window.configLoader 加载）
        this.config = null;
        // 数据基础路径（从 configLoader 获取，用于 fetch 请求）
        this.baseDataPath = '';
        // 当前市场标识，默认 'cn'（可为 'us' 或各种 cn 变体）
        this.currentMarket = 'cn'; // 'us' or 'cn'
        // 股票代码到名称的缓存（用于展示）
        this.nameCache = {}; // 新增：专门存股票名称
    }

    // Switch market between US stocks and A-shares
    // 功能：切换当前市场（例如 'cn' 或 'us'），并清空相关缓存
    setMarket(market) {
        this.currentMarket = market;
        this.agentData = {};
        this.priceCache = {};
    }

    // Get current market
    // 功能：返回当前市场标识
    getMarket() {
        return this.currentMarket;
    }

    // Get current market configuration
    // 功能：根据前端市场 ID 映射到配置中的 market key，并从全局 configLoader 获取市场配置
    getMarketConfig() {
        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'cn',        // sse50 -> config.yaml markets.cn
            'zxg':    'cn_sxg',    // zxg -> config.yaml markets.cn_sxg
            'csi300': 'cn',        // csi300 -> config.yaml markets.cn
            'zz500':  'cn',        // zz500 -> config.yaml markets.cn
            'gem':    'cn',        // gem -> config.yaml markets.cn
            'cn':     'cn',        // cn -> config.yaml markets.cn
            'cn_sxg': 'cn_sxg',    // cn_sxg -> config.yaml markets.cn_sxg
            'cn_hour': 'cn',       // cn_hour -> config.yaml markets.cn
            'us':     'us',        // us -> config.yaml markets.us (if exists)
        };
        
        const configKey = marketMapping[this.currentMarket] || this.currentMarket;
        return window.configLoader.getMarketConfig(configKey);
    }

    // 获取股票名字的简易方法
    // 功能：优先从 `nameCache` 获取股票名称，未命中返回代码本身
    getStockName(symbol) {return this.nameCache[symbol] || symbol;} // 如果没找到名字，就返回代码本身

    // Initialize with configuration
    // 功能：延迟加载全局配置并设置基础数据路径
    async initialize() {
        if (!this.config) {
            this.config = await window.configLoader.loadConfig();
            this.baseDataPath = window.configLoader.getDataPath();
        }
    }

    // Load all agent names from configuration
    // 功能：根据当前市场从配置中获取启用的 agent 列表，并检测每个 agent 的 position 文件是否存在
    async loadAgentList() {
        try {
            // Ensure config is loaded
            await this.initialize();

            const marketConfig = this.getMarketConfig();
            const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data_astock';
            const agents = [];
            
            // Map front-end market IDs to config.yaml market keys
            const marketMapping = {
                'sse50':  'cn',        
                'zxg':    'cn_sxg',    
                'csi300': 'cn',        
                'zz500':  'cn',        
                'gem':    'cn',        
                'cn':     'cn',        
                'cn_sxg': 'cn_sxg',    
                'cn_hour': 'cn',       
                'us':     'us',        
            };
            const configKey = marketMapping[this.currentMarket] || this.currentMarket;
            const enabledAgents = window.configLoader.getEnabledAgents(configKey);

            for (const agentConfig of enabledAgents) {
                try {
                    console.log(`Checking agent: ${agentConfig.folder} in ${agentDataDir}`);
                    // Avoid duplicating agentDataDir if agentConfig.folder already contains it or if agentDataDir is empty
                    let folderPath = agentConfig.folder;
                    if (agentDataDir && agentDataDir.trim() !== '') {
                        folderPath = agentConfig.folder.startsWith(agentDataDir) ? agentConfig.folder : `${agentDataDir}/${agentConfig.folder}`;
                    }
                    const response = await fetch(`${this.baseDataPath}/${folderPath}/position/position.jsonl`);
                    if (response.ok) {
                        agents.push(agentConfig.folder);
                        console.log(`Added agent: ${agentConfig.folder}`);
                    } else {
                        console.log(`Agent ${agentConfig.folder} not found (status: ${response.status})`);
                    }
                } catch (e) {
                    console.log(`Agent ${agentConfig.folder} error:`, e.message);
                }
            }

            return agents;
        } catch (error) {
            console.error('Error loading agent list:', error);
            return [];
        }
    }

    // Load position data for a specific agent
    // 功能：读取指定 agent 的 position.jsonl 文件，解析每一行为 JSON 并返回位置数组
    async loadAgentPositions(agentName) {
        try {
            const marketConfig = this.getMarketConfig();
            const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data_astock';
            // Avoid duplicating agentDataDir if agentName already contains it or if agentDataDir is empty
            let folderPath = agentName;
            if (agentDataDir && agentDataDir.trim() !== '') {
                folderPath = agentName.startsWith(agentDataDir) ? agentName : `${agentDataDir}/${agentName}`;
            }
            const response = await fetch(`${this.baseDataPath}/${folderPath}/position/position.jsonl`);
            if (!response.ok) throw new Error(`Failed to load positions for ${agentName}`);

            const text = await response.text();
            const lines = text.trim().split('\n').filter(line => line.trim() !== '');
            const positions = lines.map(line => {
                try {
                    return JSON.parse(line);
                } catch (parseError) {
                    console.error(`Error parsing line for ${agentName}:`, line, parseError);
                    return null;
                }
            }).filter(pos => pos !== null);

            console.log(`Loaded ${positions.length} positions for ${agentName}`);
            return positions;
        } catch (error) {
            console.error(`Error loading positions for ${agentName}:`, error);
            return [];
        }
    }

    // Load all A-share stock prices from merged.jsonl
    // 功能：从合并的 JSONL 文件中一次性加载所有 A 股行情数据并缓存，支持日线与 60 分数据
    async loadAStockPrices() {
        if (Object.keys(this.priceCache).length > 0) {
            return this.priceCache;
        }

        try {
            const marketConfig = this.getMarketConfig();
            // Default to merged.jsonl if not specified
            const priceFile = marketConfig && marketConfig.price_data_file ? marketConfig.price_data_file : 'data/a_stock_data/sse_50_day/merged.jsonl';
            
            console.log(`Loading A-share prices from ${priceFile}...`);
            const response = await fetch(`${this.baseDataPath}/${priceFile}`);
            if (!response.ok) throw new Error(`Failed to load A-share prices from ${priceFile}`);

            const text = await response.text();
            const lines = text.trim().split('\n');

            for (const line of lines) {
                if (!line.trim()) continue;
                const data = JSON.parse(line);

                // 统一提取 Meta Data 引用
                const metaData = data['Meta Data']; 
                if (!metaData) continue;

                // 使用一致的 metaData 引用来提取字段
                const symbol = metaData['2. Symbol'];
                const name = metaData['2.1. Name'];
                this.nameCache[symbol] = name;// 存入缓存

                // Support both Daily and 60min keys
                this.priceCache[symbol] = data['Time Series (Daily)'] || data['Time Series (60min)'];
            }

            console.log(`Loaded prices for ${Object.keys(this.priceCache).length} A-share stocks`);
            return this.priceCache;
        } catch (error) {
            console.error('Error loading A-share prices:', error);
            return {};
        }
    }

    // Load price data for a specific stock symbol
    // 功能：根据当前市场选择从 priceCache（A 股）或单个文件（美股）加载指定股票的时间序列
    async loadStockPrice(symbol) {
        if (this.priceCache[symbol]) {
            return this.priceCache[symbol];
        }

        // Check if current market is a Chinese market (including all variants: cn, zxg, csi300, zz500, gem, sse50, etc.)
        const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_sxg', 'cn_hour'];
        const isChinaMarket = this.currentMarket.startsWith('cn') || chineseMarkets.includes(this.currentMarket);
        
        if (isChinaMarket) {
            // For A-shares, load all prices at once from merged.jsonl
            await this.loadAStockPrices();
            return this.priceCache[symbol] || null;
        }

        // For US stocks, load individual JSON files
        try {
            const priceFilePrefix = window.configLoader.getPriceFilePrefix();
            const filePath = `${this.baseDataPath}/${priceFilePrefix}${symbol}.json`;
            const response = await fetch(filePath);
            if (!response.ok) {
                console.warn(`[loadStockPrice] ❌ ${symbol}: HTTP ${response.status}`);
                throw new Error(`Failed to load price for ${symbol}`);
            }

            const data = await response.json();
            // Support both hourly (60min) and daily data formats
            this.priceCache[symbol] = data['Time Series (60min)'] || data['Time Series (Daily)'];

            if (!this.priceCache[symbol]) {
                console.warn(`[loadStockPrice] ❌ ${symbol}: No time series data found`);
                return null;
            }

            const dataPointCount = Object.keys(this.priceCache[symbol]).length;
            const sampleDates = Object.keys(this.priceCache[symbol]).sort().slice(0, 3);
            console.log(`[loadStockPrice] ✅ ${symbol}: ${dataPointCount} points, samples: ${sampleDates.join(', ')}`);

            return this.priceCache[symbol];
        } catch (error) {
            console.error(`[loadStockPrice] ❌ ${symbol}:`, error.message);
            return null;
        }
    }

    // Get closing price for a symbol on a specific date/time
    // 功能：返回给定时间点或日期的收盘价，兼容不同字段名与日/小时级别的数据
    async getClosingPrice(symbol, dateOrTimestamp) {
        const prices = await this.loadStockPrice(symbol);
        if (!prices) {
            return null;
        }

        // Treat these market ids as Chinese A-share markets as well
        const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_sxg', 'cn_hour'];
        const isChinaMarket = this.currentMarket.startsWith('cn') || chineseMarkets.includes(this.currentMarket);

        // Try exact match first (for hourly data like "2025-10-01 10:00:00")
        if (prices[dateOrTimestamp]) {
            // Support multiple possible field names, fallback to buy price if necessary
            const closePrice = prices[dateOrTimestamp]['4. close'] || prices[dateOrTimestamp]['4. sell price'] || prices[dateOrTimestamp]['close'] || prices[dateOrTimestamp]['1. buy price'];
            return closePrice ? parseFloat(closePrice) : null;
        }

        // For A-shares: Extract date only for daily data matching
        if (isChinaMarket) {
            const dateOnly = dateOrTimestamp.split(' ')[0]; // "2025-10-01 10:00:00" -> "2025-10-01"

            // Exact daily match - try multiple field names including buy price as fallback
            if (prices[dateOnly]) {
                const closePrice = prices[dateOnly]['4. close'] || prices[dateOnly]['4. sell price'] || prices[dateOnly]['4. sell'] || prices[dateOnly]['close'] || prices[dateOnly]['1. buy price'];
                if (closePrice) {
                    return parseFloat(closePrice);
                }
            }

            // Try same-day timestamps (hourly keys like '2025-10-01 10:00:00')
            const datePrefix = dateOnly;
            const matchingKeys = Object.keys(prices).filter(key => key.startsWith(datePrefix));
            if (matchingKeys.length > 0) {
                // Use the last (most recent) timestamp for that date
                const lastKey = matchingKeys.sort().pop();
                const closePrice = prices[lastKey]['4. close'] || prices[lastKey]['4. sell price'] || prices[lastKey]['4. sell'] || prices[lastKey]['close'] || prices[lastKey]['1. buy price'];
                if (closePrice) {
                    return parseFloat(closePrice);
                }
            }

            // FALLBACK: find the most recent previous date available in the price series
            const allKeys = Object.keys(prices).filter(k => k.length >= 10).sort();
            // Keep only keys that look like dates (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
            const candidateKeys = allKeys.filter(k => k.slice(0,10) <= dateOnly);
            if (candidateKeys.length > 0) {
                const nearest = candidateKeys.sort().pop();
                const entry = prices[nearest];
                // Try multiple price field names in order of preference, fallback to buy price if close/sell unavailable
                const closePrice = entry && (entry['4. close'] || entry['4. sell price'] || entry['4. sell'] || entry['close'] || entry['1. buy price']);
                if (closePrice) {
                    return parseFloat(closePrice);
                }
            }
        }

        return null;
    }

    async getTradePrice(symbol, dateOrTimestamp, action) {
        // 功能：根据交易方向（buy/sell）尝试返回对应的买入价或卖出价，兼容多种字段名
        const prices = await this.loadStockPrice(symbol);
        if (!prices) {
            return null;
        }

        // 尝试精确匹配（小时级数据）
        let dayData = prices[dateOrTimestamp];
        if (!dayData) {
            // 对于日级数据，提取日期部分
            const dateOnly = dateOrTimestamp.split(' ')[0];
            dayData = prices[dateOnly];
        }

        if (!dayData) {
            return null;
        }

        let priceKey;
        if (action === 'buy') {
            // 支持多种可能的开盘/买价字段名
            priceKey = dayData['1. open'] || 
                       dayData['1. buy price'] ||  // ← 新增：实际字段
                       dayData['1. buy'] ||
                       dayData['open'];
        } else { // sell
            // 支持多种可能的收盘/卖价字段名
            priceKey = dayData['4. close'] || 
                       dayData['4. sell price'] ||  // ← 已支持，但保留
                       dayData['4. sell'] ||
                       dayData['close'];
        }

        const price = priceKey || dayData['4. sell price']; // 最后兼容旧逻辑
        return price ? parseFloat(price) : null;
    }

    // Calculate total asset value for a position on a given date
    // 功能：根据 position（包含持仓表和现金）计算指定日期的资产总值（现金 + 股票市值）
    async calculateAssetValue(position, date) {
        let totalValue = position.positions.CASH || 0;
        let partialValue = true; // Track if we got all prices

        // Get all stock symbols (exclude CASH)
        const symbols = Object.keys(position.positions).filter(s => s !== 'CASH');

        for (const symbol of symbols) {
            const shares = position.positions[symbol];
            if (shares > 0) {
                const price = await this.getClosingPrice(symbol, date);
                if (price && !isNaN(price)) {
                    totalValue += shares * price;
                } else {
                    console.warn(`Missing or invalid price for ${symbol} on ${date}; using cash-only value`);
                    partialValue = false;
                }
            }
        }

        // For A-shares: If any stock price is missing, still return the value (at least CASH + prices we got)
        // This prevents skipping entire dates when some symbols lack pricing
        return totalValue;
    }

    // Load complete data for an agent including asset values over time
    // 功能：读取 agent 的所有 position，按日或时间戳计算每个时间点的资产净值，填补日期间隙并返回历史序列
    async loadAgentData(agentName) {
        console.log(`Starting to load data for ${agentName} in ${this.currentMarket} market...`);
        const positions = await this.loadAgentPositions(agentName);
        if (positions.length === 0) {
            console.log(`No positions found for ${agentName}`);
            return null;
        }

        console.log(`Processing ${positions.length} positions for ${agentName}...`);

        let assetHistory = [];
        
        const marketConfig = this.getMarketConfig();
        const isHourlyConfig = marketConfig && marketConfig.time_granularity === 'hourly';

        if (this.currentMarket.startsWith('cn') && !isHourlyConfig) {
            // A-SHARES DAILY LOGIC: 处理同一交易日内多笔交易，并在日期范围内填补缺失的交易日
            // 仅用于日线模式（非 cn_hour 的小时模式）

            // Detect if data is hourly or daily
            const firstDate = positions[0]?.date || '';
            const isHourlyData = firstDate.includes(':'); // Has time component

            console.log(`Detected ${isHourlyData ? 'hourly' : 'daily'} data format for ${agentName}`);

            // 将 position 按日期分组（对于小时级数据，按日期取当日最新一条记录）
            const positionsByDate = {};
            positions.forEach(position => {
                let dateKey;
                if (isHourlyData) {
                    // Extract date only: "2025-10-01 10:00:00" -> "2025-10-01"
                    dateKey = position.date.split(' ')[0];
                } else {
                    // Already in date format: "2025-10-01"
                    dateKey = position.date;
                }

                // 跳过周末（周六、周日），不将其计入交易日序列
                const d = new Date(dateKey + 'T00:00:00');
                const dayOfWeek = d.getDay();
                if (dayOfWeek === 0 || dayOfWeek === 6) {
                    console.log(`Skipping weekend date ${dateKey} from position data`);
                    return; // Skip this position (it's a weekend)
                }

                // 对每个日期保留 ID 最大（最新）的 position
                if (!positionsByDate[dateKey] || position.id > positionsByDate[dateKey].id) {
                    positionsByDate[dateKey] = {
                        ...position,
                        dateKey: dateKey,  // Store normalized date for price lookup
                        originalDate: position.date  // Keep original for reference
                    };
                }
            });

            // Convert to array and sort by date
            const uniquePositions = Object.values(positionsByDate).sort((a, b) => {
                return a.dateKey.localeCompare(b.dateKey);
            });

            console.log(`Reduced from ${positions.length} to ${uniquePositions.length} unique daily positions for ${agentName}`);

            if (uniquePositions.length === 0) {
                console.warn(`No unique positions for ${agentName}`);
                return null;
            }

            // Get date range
            const startDate = new Date(uniquePositions[0].dateKey + 'T00:00:00');
            const endDate = new Date(uniquePositions[uniquePositions.length - 1].dateKey + 'T00:00:00');

            // Create a map of positions by date for quick lookup
            const positionMap = {};
            uniquePositions.forEach(pos => {
                positionMap[pos.dateKey] = pos;
            });

            // 在起止日期之间逐日遍历，跳过周末，并使用已知或最近的 position 计算当日资产
            let currentPosition = null;
            for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
                // Extract date string in local timezone (avoid UTC conversion issues)
                const year = d.getFullYear();
                const month = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                const dateStr = `${year}-${month}-${day}`;
                const dayOfWeek = d.getDay();

                // Skip weekends (Saturday = 6, Sunday = 0)
                if (dayOfWeek === 0 || dayOfWeek === 6) {
                    console.log(`Skipping weekend in gap-fill loop: ${dateStr} (day ${dayOfWeek})`);
                    continue;
                }

                // 若该日期有 position，则更新 currentPosition；否则复用上一个有效的 position
                if (positionMap[dateStr]) {
                    currentPosition = positionMap[dateStr];
                    console.log(`[${agentName}] Date ${dateStr}: Updated currentPosition (id=${currentPosition.id})`);
                } else {
                    console.log(`[${agentName}] Date ${dateStr}: Using previous currentPosition (id=${currentPosition?.id})`);
                }

                // Skip if we don't have any position yet
                if (!currentPosition) {
                    console.log(`[${agentName}] Date ${dateStr}: No position available, skipping`);
                    continue;
                }

                // 使用当前循环的日期作为价格查询时间，计算资产净值
                const assetValue = await this.calculateAssetValue(currentPosition, dateStr);
                console.log(`[${agentName}] Date ${dateStr}: assetValue = ${assetValue}`);

                if (assetValue === null || isNaN(assetValue)) {
                    console.warn(`Skipping date ${dateStr} for ${agentName} due to missing price data`);
                    continue;
                }

                assetHistory.push({
                    date: dateStr,
                    value: assetValue,
                    id: currentPosition.id,
                    action: positionMap[dateStr]?.this_action || null  // Only show action if position changed
                });
            }

        } else {
            // 美股或 CN 小时数据逻辑：保留原始时间戳（不合并为日线），逐条计算资产
            console.log(`Using fine-grained timestamp logic for ${this.currentMarket} (hourly/raw mode)`);

            // 将 position 按完整时间戳分组，保留每个时间戳下 ID 最大的记录
            const positionsByTimestamp = {};
            positions.forEach(position => {
                const timestamp = position.date;
                if (!positionsByTimestamp[timestamp] || position.id > positionsByTimestamp[timestamp].id) {
                    positionsByTimestamp[timestamp] = position;
                }
            });

            // 转为数组并按时间戳排序，以便顺序计算资产历史
            const uniquePositions = Object.values(positionsByTimestamp).sort((a, b) => {
                if (a.date !== b.date) {
                    return a.date.localeCompare(b.date);
                }
                return a.id - b.id;
            });

            console.log(`Reduced from ${positions.length} to ${uniquePositions.length} unique positions for ${agentName}`);

            for (const position of uniquePositions) {
                const timestamp = position.date;
                // 计算每个时间点的资产净值
                const assetValue = await this.calculateAssetValue(position, timestamp);
                
                // For CN Hourly, we might have missing prices if timestamp doesn't align perfectly
                if (assetValue === null) {
                     console.warn(`Skipping timestamp ${timestamp} for ${agentName} due to missing price`);
                     continue;
                }

                assetHistory.push({
                    date: timestamp,
                    value: assetValue,
                    id: position.id,
                    action: position.this_action || null
                });
            }
        }

        // 检查是否获得到有效的资产历史数据
        if (assetHistory.length === 0) {
            console.error(`❌ ${agentName}: NO VALID ASSET HISTORY`);
            return null;
        }

        const result = {
            name: agentName,
            positions: positions,
            assetHistory: assetHistory,
            initialValue: assetHistory[0]?.value || 10000,
            currentValue: assetHistory[assetHistory.length - 1]?.value || 0,
            return: assetHistory.length > 0 ?
                ((assetHistory[assetHistory.length - 1].value - assetHistory[0].value) / assetHistory[0].value * 100) : 0
        };

        console.log(`Successfully loaded data for ${agentName}:`, {
            positions: positions.length,
            assetHistory: assetHistory.length,
            initialValue: result.initialValue,
            currentValue: result.currentValue,
            return: result.return,
            dateRange: assetHistory.length > 0 ?
                `${assetHistory[0].date} to ${assetHistory[assetHistory.length - 1].date}` : 'N/A',
            sampleDates: assetHistory.slice(0, 5).map(h => h.date)
        });

        return result;
    }

    // Load benchmark data (QQQ for US, SSE 50 for A-shares)
    // 功能：根据当前市场返回对应的基准（美股示例为 QQQ，A 股为 SSE 50），用于与 agent 表现对比
    async loadBenchmarkData() {
        // Determine which benchmark to load based on market type
        // Treat a set of front-end market IDs as CN (A-shares) markets
        const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_sxg', 'cn_hour'];

        if (this.currentMarket === 'us') {
            // For US markets, return null (QQQ loading not implemented)
            console.warn('US market benchmark (QQQ) loading not implemented');
            return null;
        } else if (chineseMarkets.includes(this.currentMarket) || this.currentMarket.startsWith('cn')) {
            // For all CN market variants (including sse50, zxg), load SSE 50 Index or market-specific benchmark
            return await this.loadSSE50Data();
        }

        return null;
    }

    // Aggregate hourly time series data to daily (take end-of-day close price)
    // 功能：将小时级时间序列聚合为日线，选择当日收盘（或接近收盘的小时）作为代表
    aggregateHourlyToDaily(hourlyTimeSeries) {
        const dailyData = {};
        const dates = Object.keys(hourlyTimeSeries).sort();
        
        for (const timestamp of dates) {
            const dateOnly = timestamp.split(' ')[0]; // Extract date part
            const hour = timestamp.split(' ')[1]?.split(':')[0]; // Extract hour
            
            // Keep the last (end of day) price for each date
            // Assuming market closes at 15:00 (3 PM)
            if (!dailyData[dateOnly] || hour === '15') {
                dailyData[dateOnly] = hourlyTimeSeries[timestamp];
            }
        }
        
        console.log(`Aggregated ${dates.length} hourly data points to ${Object.keys(dailyData).length} daily data points`);
        return dailyData;
    }

    // Load SSE 50 Index data for A-shares
    // 功能：查找并加载上证 50 指数的时间序列数据（支持多种候选文件名和路径）
    async loadSSE50Data() {
        try {
            console.log('Loading SSE 50 Index data...');

            // Always use daily SSE 50 data, even in hourly mode
            const marketConfig = this.getMarketConfig();
            const benchmarkFile = marketConfig ? marketConfig.benchmark_file : null;

            // Try the configured benchmark file first, then fall back to common filenames
            const candidates = [];
            if (benchmarkFile) candidates.push(benchmarkFile);
            // derive directory
            const dir = benchmarkFile ? benchmarkFile.split('/').slice(0, -1).join('/') : 'a_stock_data/sse_50_day';
            candidates.push(`${dir}/index_daily_sh000001.json`);
            candidates.push(`${dir}/index_daily_sse_50.json`);
            candidates.push(`${dir}/index_daily_000016.SH.json`);
            candidates.push(`${dir}/index_daily_000001.SH.json`);

            let response = null;
            let foundFile = null;
            for (const f of candidates) {
                try {
                    // normalize path to avoid double slashes
                    const path = `${this.baseDataPath}/${f}`.replace(/\\/g, '/').replace(/\/\//g, '/');
                    // Try fetch
                    // console.log('Trying benchmark path:', path);
                    const r = await fetch(path);
                    if (r.ok) {
                        response = r;
                        foundFile = f;
                        break;
                    }
                } catch (e) {
                    // ignore and try next
                }
            }

            if (!response) {
                console.warn('SSE 50 Index data not found in candidates:', candidates);
                throw new Error('Failed to load SSE 50 Index data');
            }

            const data = await response.json();

            // Robustly find the time series key (handle placeholders like '{freq}')
            let timeSeries = data['Time Series (Daily)'] || data['Time Series (60min)'];
            let usedTimeSeriesKey = null;
            if (!timeSeries) {
                for (const k of Object.keys(data)) {
                    if (k.toLowerCase().includes('time series')) {
                        timeSeries = data[k];
                        usedTimeSeriesKey = k;
                        break;
                    }
                }
            } else {
                usedTimeSeriesKey = timeSeries === data['Time Series (Daily)'] ? 'Time Series (Daily)' : 'Time Series (60min)';
            }

            if (!timeSeries) {
                console.warn('SSE 50 Index data not found (no Time Series key) in', foundFile);
                return null;
            }

            console.log('Using benchmark time series key:', usedTimeSeriesKey || '(default)');

            const benchmarkName = marketConfig ? marketConfig.benchmark_display_name : 'SSE 50';
            
            // For hourly mode, we need to expand daily benchmark to match hourly agent timestamps
            const isHourlyMode = this.currentMarket === 'cn_hour';
            return this.createBenchmarkAssetHistory(benchmarkName, timeSeries, 'CNY', isHourlyMode);
        } catch (error) {
            console.error('Error loading SSE 50 data:', error);
            return null;
        }
    }

    // Create benchmark asset history from time series data
    // 功能：将基准的时间序列（日线或小时线）转换为与 agent 相同格式的 assetHistory，
    //        支持将日线扩展到 agent 的小时级时间戳以便精确对齐
    createBenchmarkAssetHistory(name, timeSeries, currency, expandToHourly = false) {
        try {
            // Convert to asset history format
            const assetHistory = [];
            const dates = Object.keys(timeSeries).sort();

            // Calculate benchmark performance starting from first agent's initial value
            const agentNames = Object.keys(this.agentData);
            const uiConfig = window.configLoader.getUIConfig();
            let initialValue = uiConfig.initial_value; // Default initial value from config

            if (agentNames.length > 0) {
                const firstAgent = this.agentData[agentNames[0]];
                if (firstAgent && firstAgent.assetHistory.length > 0) {
                    initialValue = firstAgent.assetHistory[0].value;
                }
            }

            // Find the earliest start date and latest end date across all agents
            let startDate = null;
            let endDate = null;
            // Collect all agent timestamps for hourly expansion
            const allAgentTimestamps = new Set();
            
            if (agentNames.length > 0) {
                agentNames.forEach(agentName => {
                    const agent = this.agentData[agentName];
                    if (agent && agent.assetHistory.length > 0) {
                        const agentStartDate = agent.assetHistory[0].date;
                        const agentEndDate = agent.assetHistory[agent.assetHistory.length - 1].date;

                        if (!startDate || agentStartDate < startDate) {
                            startDate = agentStartDate;
                        }
                        if (!endDate || agentEndDate > endDate) {
                            endDate = agentEndDate;
                        }
                        
                        // Collect all timestamps if we need to expand
                        if (expandToHourly) {
                            agent.assetHistory.forEach(h => allAgentTimestamps.add(h.date));
                        }
                    }
                });
            }

            let benchmarkStartPrice = null;
            let currentValue = initialValue;
            
            // 构建价格映射（日期->收盘价），以便快速查找
            const priceMap = {};
            for (const date of dates) {
                const closePrice = timeSeries[date]['4. close'] || timeSeries[date]['4. sell price'];
                if (closePrice) {
                    priceMap[date] = parseFloat(closePrice);
                }
            }

            // 如果需要扩展到小时级，则使用 agent 的所有时间戳；否则使用基准自身的日期序列
            const timestampsToUse = expandToHourly ? 
                Array.from(allAgentTimestamps).sort() : 
                dates;

            // Determine if benchmark data is hourly (has time component)
            const isHourlyBenchmark = dates.length > 0 && dates[0].includes(':');
            console.log(`Benchmark data type: ${isHourlyBenchmark ? 'Hourly' : 'Daily'}, expandToHourly: ${expandToHourly}`);

            // 遍历需要输出的时间戳列表，计算基准在每个时间点的等权资产价值
            for (const timestamp of timestampsToUse) {
                // Skip if outside agent date range
                if (startDate && timestamp < startDate) continue;
                if (endDate && timestamp > endDate) continue;

                // Find the benchmark price
                let price;
                if (isHourlyBenchmark && !expandToHourly) {
                    // Hourly benchmark data (like QQQ 60min), use exact timestamp
                    price = priceMap[timestamp];
                } else if (expandToHourly) {
                    // Daily benchmark data expanded to hourly timestamps, use date part
                    const dateOnly = timestamp.split(' ')[0];
                    price = priceMap[dateOnly];
                } else {
                    // Daily benchmark data with daily timestamps
                    price = priceMap[timestamp];
                }
                
                if (!price) {
                    // console.warn(`No price found for ${timestamp}`);
                    continue;
                }

                if (!benchmarkStartPrice) {
                    benchmarkStartPrice = price;
                }

                // Calculate benchmark performance relative to start
                const benchmarkReturn = (price - benchmarkStartPrice) / benchmarkStartPrice;
                currentValue = initialValue * (1 + benchmarkReturn);

                assetHistory.push({
                    date: timestamp,
                    value: currentValue,
                    id: `${name.toLowerCase().replace(/\s+/g, '-')}-${timestamp}`,
                    action: null
                });
            }

            // 构造结果对象，包含 assetHistory 与统计信息
            const result = {
                name: name,
                positions: [],
                assetHistory: assetHistory,
                initialValue: initialValue,
                currentValue: assetHistory.length > 0 ? assetHistory[assetHistory.length - 1].value : initialValue,
                return: assetHistory.length > 0 ?
                    ((assetHistory[assetHistory.length - 1].value - assetHistory[0].value) / assetHistory[0].value * 100) : 0,
                currency: currency
            };

            console.log(`Successfully loaded ${name} data:`, {
                assetHistory: assetHistory.length,
                initialValue: result.initialValue,
                currentValue: result.currentValue,
                return: result.return
            });

            return result;
        } catch (error) {
            console.error(`Error creating benchmark asset history for ${name}:`, error);
            return null;
        }
    }

    // Load all agents data with caching
    // Load all agents data with caching
    // 功能：一次性加载所有启用 agent 的数据并生成 allData，包含可选的基准数据
    async loadAllAgentsData() {
        const startTime = performance.now();
        console.log('Starting to load all agents data...');

        // Try to load from cache first or Cache miss or disabled - fall back to live calculation
        console.log('⚠ Cache miss - performing live calculation (slow path)');
        const calcStartTime = performance.now();

        const agents = await this.loadAgentList();
        console.log('Found agents:', agents);
        const allData = {};

        for (const agent of agents) {
            console.log(`Loading data for ${agent}...`);
            const data = await this.loadAgentData(agent);
            if (data) {
                allData[agent] = data;
                console.log(`Successfully added ${agent} to allData`);
            } else {
                console.log(`Failed to load data for ${agent}`);
            }
        }

        console.log('Final allData:', Object.keys(allData));
        this.agentData = allData;

        // Load benchmark data (QQQ for US, SSE 50 for A-shares)
        const benchmarkData = await this.loadBenchmarkData();
        if (benchmarkData) {
            allData[benchmarkData.name] = benchmarkData;
            console.log(`Successfully added ${benchmarkData.name} to allData`);
        }

        const calcTime = performance.now() - calcStartTime;
        const totalTime = performance.now() - startTime;

        return allData;
    }

    // Get current holdings for an agent (latest position)
    // 功能：获取指定 agent 的最新持仓（包括股票和现金）
    getCurrentHoldings(agentName) {
        const data = this.agentData[agentName];
        if (!data || !data.positions || data.positions.length === 0) return null;

        const latestPosition = data.positions[data.positions.length - 1];
        return latestPosition && latestPosition.positions ? latestPosition.positions : null;
    }

    // Get trade history for an agent
    // 功能：返回按时间倒序排列的实际交易记录（排除 no_trade）
    getTradeHistory(agentName) {
        const data = this.agentData[agentName];
        if (!data) {
            console.log(`[getTradeHistory] No data for agent: ${agentName}`);
            return [];
        }

        console.log(`[getTradeHistory] Agent: ${agentName}, Total positions: ${data.positions.length}`);

        const allActions = data.positions.filter(p => p.this_action);
        console.log(`[getTradeHistory] Positions with this_action: ${allActions.length}`);

        const trades = data.positions
            .filter(p => p.this_action && p.this_action.action !== 'no_trade')
            .map(p => ({
                date: p.date,
                action: p.this_action.action,
                symbol: p.this_action.symbol,
                amount: p.this_action.amount
            }))
            .reverse(); // Most recent first

        console.log(`[getTradeHistory] Actual trades (excluding no_trade): ${trades.length}`);
        console.log(`[getTradeHistory] First 3 trades:`, trades.slice(0, 3));

        return trades;
    }

    // Format number as currency
    // 功能：根据当前市场和配置格式化货币显示（本地化 + 货币符号）
    formatCurrency(value) {
        const marketConfig = this.getMarketConfig();
        const currency = marketConfig ? marketConfig.currency : 'CNY';
        const locale = this.currentMarket === 'cn' ? 'zh-CN' : 'en-US' ;

        return new Intl.NumberFormat(locale, {
            style: 'currency',
            currency: currency,
            minimumFractionDigits: 2
        }).format(value);
    }

    // Format percentage
    // 功能：格式化百分比字符串，带符号与两位小数
    formatPercent(value) {
        const sign = value >= 0 ? '+' : '';
        return `${sign}${value.toFixed(2)}%`;
    }

    // Get nice display name for agent
    // 功能：返回 agent 的展示名称，优先从 configLoader 查询，失败回退到内置名字映射
    getAgentDisplayName(agentName) {
        // agentName might be a folder key like 'glm-4.5-air' or full path with slashes
        // For config lookup, ensure we're using the folder key
        const folderKey = typeof agentName === 'string' && agentName.includes('/') 
            ? agentName.split('/').pop() 
            : agentName;
        
        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'cn',
            'zxg':    'cn_sxg',
            'csi300': 'cn',
            'zz500':  'cn',
            'gem':    'cn',
            'cn':     'cn',
            'cn_sxg': 'cn_sxg',
            'cn_hour': 'cn',
            'us':     'us',
        };
        const effectiveMarket = marketMapping[this.currentMarket] || this.currentMarket;
        
        const displayName = window.configLoader.getDisplayName(folderKey, effectiveMarket);
        if (displayName) return displayName;

        // Fallback to legacy names
        const names = {
            'gemini-2.5-flash': 'Gemini-2.5-flash',
            'qwen3-max': 'Qwen3-max',
            'MiniMax-M2': 'MiniMax-M2',
            'gpt-5': 'GPT-5',
            'deepseek-chat-v3.1': 'DeepSeek-v3.1',
            'claude-3.7-sonnet': 'Claude 3.7 Sonnet',
            'QQQ Invesco': 'QQQ ETF',
            'SSE 50 Index': 'SSE 50 Index' 
        };
        return names[agentName] || folderKey;
    }

    // Get icon for agent (SVG file path)
    // 功能：返回 agent 的图标路径，优先使用配置中的图标，失败则使用内置路径回退
    getAgentIcon(agentName) {
        // agentName might be a folder key like 'glm-4.5-air' or full path with slashes
        // For config lookup, ensure we're using the folder key
        const folderKey = typeof agentName === 'string' && agentName.includes('/') 
            ? agentName.split('/').pop() 
            : agentName;
        
        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'cn',
            'zxg':    'cn_sxg',
            'csi300': 'cn',
            'zz500':  'cn',
            'gem':    'cn',
            'cn':     'cn',
            'cn_sxg': 'cn_sxg',
            'cn_hour': 'cn',
            'us':     'us',
        };
        const effectiveMarket = marketMapping[this.currentMarket] || this.currentMarket;
        
        const icon = window.configLoader.getIcon(folderKey, effectiveMarket);
        if (icon) return icon;

        // Fallback to legacy icons
        const icons = {
            'gemini-2.5-flash': './figs/google.svg',
            'qwen3-max': './figs/qwen.svg',
            'MiniMax-M2': './figs/minimax.svg',
            'gpt-5': './figs/openai.svg',
            'claude-3.7-sonnet': './figs/claude-color.svg',
            'deepseek-chat-v3.1': './figs/deepseek.svg',
            'QQQ Invesco': './figs/stock.svg',
            'SSE 50 Index': './figs/stock.svg'
        };
        return icons[agentName] || './figs/stock.svg';
    }

    // Get agent name without version suffix for icon lookup
    // 功能：兼容老接口，返回用于查找图标的 agent 名称键（目前直接返回原名）
    getAgentIconKey(agentName) {
        // This method is kept for backward compatibility
        return agentName;
    }

    // Get brand color for agent
    // 功能：返回 agent 的品牌色（用于 UI），优先从配置获取，失败时使用内置的回退颜色
    getAgentBrandColor(agentName) {
        // agentName might be a folder key like 'glm-4.5-air' or full path with slashes
        // For config lookup, ensure we're using the folder key
        const folderKey = typeof agentName === 'string' && agentName.includes('/') 
            ? agentName.split('/').pop() 
            : agentName;
        
        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'cn',
            'zxg':    'cn_sxg',
            'csi300': 'cn',
            'zz500':  'cn',
            'gem':    'cn',
            'cn':     'cn',
            'cn_sxg': 'cn_sxg',
            'cn_hour': 'cn',
            'us':     'us',
        };
        const effectiveMarket = marketMapping[this.currentMarket] || this.currentMarket;
        
        const color = window.configLoader.getColor(folderKey, effectiveMarket);
        console.log(`[getAgentBrandColor] folderKey: ${folderKey}, market: ${this.currentMarket} => effectiveMarket: ${effectiveMarket}, color: ${color}`);
        if (color) return color;

        // Fallback to legacy colors
        const colors = {
            'gemini-2.5-flash': '#8A2BE2',
            'qwen3-max': '#0066ff',
            'MiniMax-M2': '#ff0000',
            'gpt-5': '#10a37f',
            'deepseek-chat-v3.1': '#4a90e2',
            'claude-3.7-sonnet': '#cc785c',
            'QQQ Invesco': '#ff6b00',
            'SSE 50 Index': '#e74c3c'
        };
        return colors[agentName] || null;
    }

}

// 导出到全局作用域，供其他前端模块使用
window.DataLoader = DataLoader;