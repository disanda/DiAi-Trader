// Data Loader Utility
// Handles loading and processing all trading data
// Canonical market data lives under ./data/Astocks, ./data/ETFs and ./data/USstocks.
// ./data/agent_data_astock/sse_50_day/glm-4.5-air

const chineseMarkets = ['sse50', 'zxg_17', 'zxg_30', 'etf_30']; //'cn', 'zxg', 'csi300', 'zz500', 'gem', 

class DataLoader {
    constructor() {
        this.agentData = {};
        this.priceCache = {};
        this.config = null;
        this.baseDataPath = '';
        this.currentMarket = 'sse50'; // 'us' or 'cn'
        this.nameCache = {}; // 新增：专门存股票名称
    }

    // Switch market between US stocks and A-shares
    setMarket(market) {
        this.currentMarket = market;
        this.agentData = {};
        this.priceCache = {};
    }

    // Get current market
    getMarket() {
        return this.currentMarket;
    }

    // Get current market configuration
    getMarketConfig() {
        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'sse50',        // sse50 -> config.yaml markets.sse50
            'zxg_17': 'zxg_17',    // zxg_17 -> config.yaml markets.zxg_17
            'zxg_30': 'zxg_30',        // zxg_30 -> config.yaml markets.zxg_30
            'etf_30': 'etf_30',        // etf_30 -> config.yaml markets.etf_30
            'zz500':  'zz500',        // zz500 -> config.yaml markets.zz500
            'cn':     'cn',        // cn -> config.yaml markets.cn
            'cn_hour': 'cn',       // cn_hour -> config.yaml markets.cn_hour
            'us':     'us',        // us -> config.yaml markets.us (if exists)
        };
        
        const configKey = marketMapping[this.currentMarket] || this.currentMarket;
        return window.configLoader.getMarketConfig(configKey);
    }

    // 获取股票名字的简易方法
    getStockName(symbol) {return this.nameCache[symbol] || symbol;} // 如果没找到名字，就返回代码本身

    // Initialize with configuration
    async initialize() {
        if (!this.config) {
            this.config = await window.configLoader.loadConfig();
            this.baseDataPath = window.configLoader.getDataPath();
        }
    }

    // Load all agent names from configuration
    async loadAgentList() {
        try {
            // Ensure config is loaded
            await this.initialize();

            const marketConfig = this.getMarketConfig();
            const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data_astock';
            const agents = [];
            
            // Map front-end market IDs to config.yaml market keys
            const marketMapping = {
                'sse50':  'sse50',        // sse50 -> config.yaml markets.sse50
                'zxg_17': 'zxg_17',    // zxg_17 -> config.yaml markets.zxg_17
                'zxg_30': 'zxg_30',        // zxg_30 -> config.yaml markets.zxg_30
                'etf_30': 'etf_30',        // etf_30 -> config.yaml markets.etf_30
                'gem':    'cn',        
                'cn':     'cn',        
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
    async loadAStockPrices() {
        if (Object.keys(this.priceCache).length > 0) {
            return this.priceCache;
        }

        try {
            const marketConfig = this.getMarketConfig();
            // Default to merged.jsonl if not specified
            const priceFile = marketConfig && marketConfig.price_data_file ? marketConfig.price_data_file : 'a_stock_data/sse_50_day/merged.jsonl';
            
            console.log(`Loading A-share prices from ${priceFile}...`);
            const response = await fetch(`${this.baseDataPath}/${priceFile}`);
            if (!response.ok) throw new Error(`Failed to load A-share prices from ${priceFile}`);

            const text = await response.text();
            const lines = text.trim().split('\n');

            for (const line of lines) {
                if (!line.trim()) continue;
                const data = JSON.parse(line);
                if (data.data && Array.isArray(data.data)) {
                    for (const row of data.data) {
                        const symbol = row.ts_code;
                        if (!symbol) continue;
                        this.nameCache[symbol] = row.name || symbol;
                        (this.priceCache[symbol] ||= {})[row.trade_date] = row;
                    }
                    continue;
                }
                // Canonical merged.json uses data: {"000001.SZ": [records...]}
                if (data.data && !Array.isArray(data.data) && typeof data.data === 'object') {
                    const names = data.names || data.name_map || (data.meta && data.meta.name_map) || {};
                    for (const [symbol, records] of Object.entries(data.data)) {
                        if (!Array.isArray(records)) continue;
                        this.priceCache[symbol] ||= {};
                        if (names[symbol]) this.nameCache[symbol] = names[symbol];
                        for (const row of records) {
                            const date = row.trade_date || row.date;
                            if (!date) continue;
                            this.nameCache[symbol] = row.name || this.nameCache[symbol] || symbol;
                            this.priceCache[symbol][date] = row;
                        }
                    }
                    continue;
                }

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
    async loadStockPrice(symbol) {
        if (this.priceCache[symbol]) {
            return this.priceCache[symbol];
        }

        // Check if current market is a Chinese market (including all variants: cn, zxg, csi300, zz500, gem, sse50, etc.)
        //const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_zxg', 'cn_hour', 'sse50', 'zxg_17', 'zxg_30', 'etf_30'];
        const isChinaMarket = this.currentMarket.startsWith('cn') || chineseMarkets.includes(this.currentMarket);
        
        if (isChinaMarket) {
            // Load the lightweight latest snapshot first; fetch full symbol history lazily.
            await this.loadAStockPrices();
            if (this.priceCache[symbol] && Object.keys(this.priceCache[symbol]).length > 1) return this.priceCache[symbol];
            try {
                const marketConfig = this.getMarketConfig();
                const root = marketConfig?.price_data_file?.startsWith('ETFs/') ? 'ETFs/stocks' : 'Astocks/stocks';
                const response = await fetch(`${this.baseDataPath}/${root}/${encodeURIComponent(symbol)}.json`, { cache: 'no-store' });
                if (response.ok) {
                    const payload = await response.json();
                    const records = payload.records || [];
                    this.priceCache[symbol] = Object.fromEntries(records.map(row => [row.trade_date || row.date, row]));
                    if (payload.name) this.nameCache[symbol] = payload.name;
                }
            } catch (error) { console.warn(`[loadStockPrice] history unavailable for ${symbol}`, error); }
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
    async getClosingPrice(symbol, dateOrTimestamp) {
        const prices = await this.loadStockPrice(symbol);
        if (!prices) {
            return null;
        }

        // Treat these market ids as Chinese A-share markets as well
        //const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_zxg', 'cn_hour', 'sse50', 'zxg_17', 'zxg_30', 'etf_30'];
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

        if (true) { 
            // this.currentMarket.startsWith('cn') && !isHourlyConfig
            // A-SHARES DAILY LOGIC: Handle multiple transactions per day AND fill date gaps
            // Used only for 'cn' (daily) market, not 'cn_hour'

            // Detect if data is hourly or daily
            const firstDate = positions[0]?.date || '';
            const isHourlyData = firstDate.includes(':'); // Has time component

            console.log(`Detected ${isHourlyData ? 'hourly' : 'daily'} data format for ${agentName}`);

            // Group positions by DATE (for hourly data, group by date and take last entry)
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

                // Skip weekends when building position map
                const d = new Date(dateKey + 'T00:00:00');
                const dayOfWeek = d.getDay();
                if (dayOfWeek === 0 || dayOfWeek === 6) {
                    console.log(`Skipping weekend date ${dateKey} from position data`);
                    return; // Skip this position (it's a weekend)
                }

                // Keep the position with the highest ID for each date (most recent)
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

            // Fill all dates in range (skip weekends)
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

                // Use position for this date if exists, otherwise use last known position
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

                // Calculate asset value using current iteration date for price lookup
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
            // US STOCKS OR CN HOURLY LOGIC: Keep timestamps, do not flatten to daily
            console.log(`Using fine-grained timestamp logic for ${this.currentMarket} (hourly/raw mode)`);

            // Group positions by timestamp and take only the last position for each timestamp
            const positionsByTimestamp = {};
            positions.forEach(position => {
                const timestamp = position.date;
                if (!positionsByTimestamp[timestamp] || position.id > positionsByTimestamp[timestamp].id) {
                    positionsByTimestamp[timestamp] = position;
                }
            });

            // Convert to array and sort by timestamp
            const uniquePositions = Object.values(positionsByTimestamp).sort((a, b) => {
                if (a.date !== b.date) {
                    return a.date.localeCompare(b.date);
                }
                return a.id - b.id;
            });

            console.log(`Reduced from ${positions.length} to ${uniquePositions.length} unique positions for ${agentName}`);

            for (const position of uniquePositions) {
                const timestamp = position.date;
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

        // Check if we have enough valid data
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
    async loadBenchmarkData() {
        // Determine which benchmark to load based on market type
        // Treat a set of front-end market IDs as CN (A-shares) markets
        // const chineseMarkets = ['cn', 'zxg', 'csi300', 'zz500', 'gem', 'sse50', 'cn_zxg', 'cn_hour'];

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
            const dir = benchmarkFile ? benchmarkFile.split('/').slice(0, -1).join('/') : 'data/Astocks/indices';
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
            
            // Build a price map for easy lookup
            const priceMap = {};
            for (const date of dates) {
                const closePrice = timeSeries[date]['4. close'] || timeSeries[date]['4. sell price'];
                if (closePrice) {
                    priceMap[date] = parseFloat(closePrice);
                }
            }

            // If expanding to hourly, use agent timestamps; otherwise use benchmark dates
            const timestampsToUse = expandToHourly ? 
                Array.from(allAgentTimestamps).sort() : 
                dates;

            // Determine if benchmark data is hourly (has time component)
            const isHourlyBenchmark = dates.length > 0 && dates[0].includes(':');
            console.log(`Benchmark data type: ${isHourlyBenchmark ? 'Hourly' : 'Daily'}, expandToHourly: ${expandToHourly}`);

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
    getCurrentHoldings(agentName) {
        const data = this.agentData[agentName];
        if (!data || !data.positions || data.positions.length === 0) return null;

        const latestPosition = data.positions[data.positions.length - 1];
        return latestPosition && latestPosition.positions ? latestPosition.positions : null;
    }

    // Get trade history for an agent
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
    formatCurrency(value) {
        const marketConfig = this.getMarketConfig();
        const currency = 'CNY' // marketConfig ? marketConfig.currency : 'CNY';
        const locale = 'zh-CN' // this.currentMarket = 'zh-CN' // === 'cn' ? 'zh-CN' : 'en-US' ;

        return new Intl.NumberFormat(locale, {
            style: 'currency',
            currency: currency,
            minimumFractionDigits: 2
        }).format(value);
    }

    // Format percentage
    formatPercent(value) {
        const sign = value >= 0 ? '+' : '';
        return `${sign}${value.toFixed(2)}%`;
    }

    // // Get nice display name for agent
    // getAgentDisplayName(agentName) {
    //     const displayName = window.configLoader.getDisplayName(agentName, this.currentMarket);
    //     if (displayName) return displayName;

    //     // Fallback to legacy names
    //     const names = {
    //         'gemini-2.5-flash': 'Gemini-2.5-flash',
    //         'qwen3-max': 'Qwen3-max',
    //         'MiniMax-M2': 'MiniMax-M2',
    //         'gpt-5': 'GPT-5',
    //         'deepseek-chat-v3.1': 'DeepSeek-v3.1',
    //         'claude-3.7-sonnet': 'Claude 3.7 Sonnet',
    //         'QQQ Invesco': 'QQQ ETF',
    //         'SSE 50 Index': 'SSE 50 Index' 
    //     };
    //     return names[agentName] || agentName;
    // }

    // 修复bug Repeat similar normalization for getAgentDisplayName and getAgentBrandColor
    getAgentDisplayName(agentName) {
        const display = window.configLoader.getDisplayName(agentName, this.currentMarket);
        if (display) return display;

        const normalizedName = this.getAgentIconKey(agentName);
        const fallbackDisplay = window.configLoader.getDisplayName(normalizedName, this.currentMarket);
        if (fallbackDisplay) return fallbackDisplay;

        // Legacy
        const names = {
            'glm-4.5-air': 'GLM 4.5 air',
            'glm-4.5-flash': 'GLM 4.5 flash',
            'gpt-oss-120b': 'gpt-oss-120b',
            'qwen3-235b-a22b': 'qwen3-235b-a22b',
            // Add others
            'SSE 50 Index': 'SSE 50 Index'
        };
        return names[normalizedName] || normalizedName;
    }

    // Get icon for agent (SVG file path)  获得走势图的agent icon
    getAgentIcon(agentName) { 
        // Try full agentName first (matches YAML folder)
        const icon = window.configLoader.getIcon(agentName, this.currentMarket);
        //const normalizedName = agentName.split('/').pop();  // e.g., "agent_data_astock/ZSG_17_day/glm-4.5-flash" -> "glm-4.5-flash"
        //const icon = window.configLoader.getIcon(normalizedName, this.currentMarket);
        if (icon) return icon;

        // Fallback to normalized name 修复走势图 icon bug
        const normalizedName = this.getAgentIconKey(agentName);
        const fallbackIcon = window.configLoader.getIcon(normalizedName, this.currentMarket);
        if (fallbackIcon) return fallbackIcon;

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

    // // Get agent name without version suffix for icon lookup
    // getAgentIconKey(agentName) {
    //     // This method is kept for backward compatibility
    //     return agentName;
    // }

    // 修复无icon bug Get agent name without version suffix for icon lookup (existing, but enhance for full paths)
    getAgentIconKey(agentName) {
        return agentName.split('/').pop();  // e.g., "agent_data_astock/ZSG_17_day/glm-4.5-flash" -> "glm-4.5-flash"
    }

    // Get icon for agent
    getAgentIcon(agentName) {
        // Try full name first
        console.log(`[getAgentIcon] Input: ${agentName}`);
        let icon = window.configLoader.getIcon(agentName, this.currentMarket);
        if (icon) {
        console.log(`[getAgentIcon] Found with full: ${icon}`);
        return icon;
        }

        // Normalize and try again
        const normalizedName = this.normalizeAgentName(agentName);
        icon = window.configLoader.getIcon(normalizedName, this.currentMarket);
        console.log(`[getAgentIcon] Found with normalized: ${icon}`);
        if (icon) return icon;

        // Legacy fallbacks (based on your config.yaml)
        const icons = {
            'glm-4.5-air': './figs/zhipu-color.svg',
            'glm-4.5-flash': './figs/zhipu-color.svg',
            'gpt-oss-120b': './figs/openai.svg',
            'qwen3-235b-a22b': './figs/qwen.svg',
            // Add more if needed
            'SSE 50 Index': './figs/stock.svg'
        };
        return icons[normalizedName] || './figs/stock.svg';  // Default icon
    }

    // // Get brand color for agent
    // getAgentBrandColor(agentName) {
    //     const color = window.configLoader.getColor(agentName, this.currentMarket);
    //     console.log(`[getAgentBrandColor] agentName: ${agentName}, market: ${this.currentMarket}, color: ${color}`);
    //     if (color) return color;

    //     // Fallback to legacy colors
    //     const colors = {
    //         'gemini-2.5-flash': '#8A2BE2',
    //         'qwen3-max': '#0066ff',
    //         'MiniMax-M2': '#ff0000',
    //         'gpt-5': '#10a37f',
    //         'deepseek-chat-v3.1': '#4a90e2',
    //         'claude-3.7-sonnet': '#cc785c',
    //         'QQQ Invesco': '#ff6b00',
    //         'SSE 50 Index': '#e74c3c'
    //     };
    //     return colors[agentName] || null;
    // }

    getAgentBrandColor(agentName) {
        const color = window.configLoader.getColor(agentName, this.currentMarket);
        if (color) return color;

        const normalizedName = this.getAgentIconKey(agentName);
        const fallbackColor = window.configLoader.getColor(normalizedName, this.currentMarket);
        if (fallbackColor) return fallbackColor;

        // Legacy
        const colors = {
            'glm-4.5-air': '#6610f2',
            'glm-4.5-flash': '#6610f2',
            'gpt-oss-120b': '#00ffcc',
            'qwen3-235b-a22b': '#00d4ff',
            // Add others
            'SSE 50 Index': '#e74c3c'
        };
        return colors[normalizedName] || null;
    }

}

// Export for use in other modules and expose globally
window.DataLoader = DataLoader;
