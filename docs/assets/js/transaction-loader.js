// Transaction and Leaderboard Data Loader
// Loads transaction history and agent performance data

class TransactionLoader {
    constructor() {
        this.allTransactions = [];
        this.leaderboardData = [];
    }

    // Load all transactions from all agents
    async loadAllTransactions() {
        const config = window.configLoader;
        const dataLoader = window.dataLoader;
        const currentMarket = dataLoader.getMarket();
        const agents = config.getEnabledAgents(currentMarket);

        console.log(`[TransactionLoader] Loading transactions for ${agents.length} agents in ${currentMarket} market`);

        const promises = agents.map(agent => this.loadAgentTransactions(agent.folder, currentMarket));
        const results = await Promise.all(promises);

        // Flatten and sort by date (most recent first)
        this.allTransactions = results
            .flat()
            .sort((a, b) => new Date(b.date) - new Date(a.date));

        console.log(`[TransactionLoader] Loaded ${this.allTransactions.length} total transactions`);

        return this.allTransactions;
    }

    // Load transactions for a single agent
    // async loadAgentTransactions(agentFolder, market = 'cn') {
    //     try {
    //         const marketConfig = window.configLoader.getMarketConfig(market);
    //         const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data';
    //         const positionPath = `data/${agentDataDir}/${agentFolder}/position/position.jsonl`;

    //         console.log(`[TransactionLoader] Loading transactions from: ${positionPath}`);

    //         const response = await fetch(positionPath);
    //         if (!response.ok) {
    //             console.warn(`[TransactionLoader] Failed to fetch ${positionPath}: ${response.status}`);
    //             return [];
    //         }

    //         const text = await response.text();

    //         const transactions = text
    //             .trim()
    //             .split('\n')
    //             .filter(line => line.trim())
    //             .map(line => {
    //                 const data = JSON.parse(line);
    //                 return {
    //                     agentFolder: agentFolder,
    //                     date: data.date,
    //                     id: data.id,
    //                     action: data.this_action?.action || 'initial',
    //                     symbol: data.this_action?.symbol || '',
    //                     amount: data.this_action?.amount || 0,
    //                     positions: data.positions,
    //                     cash: data.CASH || 0
    //                 };
    //             })
    //             .filter(t => {
    //                 // Filter out non-trades: no action, no_trade, initial state, or 0 amount
    //                 if (!t.action || t.action === 'initial' || t.action === 'no_trade') {
    //                     return false;
    //                 }
    //                 // Filter out transactions with 0 amount (no real trade)
    //                 if (!t.amount || t.amount === 0) {
    //                     return false;
    //                 }
    //                 // Filter out transactions with no symbol
    //                 if (!t.symbol || t.symbol === '') {
    //                     return false;
    //                 }
    //                 return true;
    //             });
    //     } catch (error) {
    //         console.warn(`Failed to load transactions for ${agentFolder}:`, error);
    //         return [];
    //     }
    // }

    // Load transactions for a single agent
    async loadAgentTransactions(agentFolder, market = 'cn') {
        try {
            const marketConfig = window.configLoader.getMarketConfig(market);
            const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data_astock';
            const positionPath = `data/${agentDataDir}/${agentFolder}/position/position.jsonl`;

            console.log(`[TransactionLoader] Loading transactions from: ${positionPath}`);

            const response = await fetch(positionPath);
            if (!response.ok) {
                console.warn(`[TransactionLoader] Failed to fetch ${positionPath}: ${response.status}`);
                return [];
            }

            const text = await response.text();

            const transactions = text
                .trim()
                .split('\n')
                .filter(line => line.trim())
                .map(line => JSON.parse(line))
                .filter(data => {
                    const action = data.this_action?.action;
                    const amount = data.this_action?.amount || 0;
                    const symbol = data.this_action?.symbol || '';
                    return action && action !== 'initial' && action !== 'no_trade' && amount !== 0 && symbol !== '';
                })
                .map(async (data) => {
                    const transaction = {
                        agentFolder: agentFolder,
                        date: data.date,
                        id: data.id,
                        action: data.this_action.action,
                        symbol: data.this_action.symbol,
                        amount: data.this_action.amount,
                        positions: data.positions,
                        cash: data.CASH || 0,
                        price: null  // To be filled
                    };

                    // 新增：使用 getTradePrice 获取区分的价格
                    try {
                        transaction.price = await window.dataLoader.getTradePrice(
                            transaction.symbol,
                            transaction.date,
                            transaction.action
                        );
                    } catch (error) {
                        console.warn(`Failed to get trade price for ${transaction.symbol} at ${transaction.date}:`, error);
                        transaction.price = null;
                    }

                    return transaction;
                });

            // 等待所有价格查询
            return await Promise.all(transactions);
        } catch (error) {
            console.warn(`Failed to load transactions for ${agentFolder}:`, error);
            return [];
        }
    }

    // Load agent's thinking/response for a specific transaction
    async loadAgentThinking(agentFolder, date, market = 'us') {
        try {
            const marketConfig = window.configLoader.getMarketConfig(market);
            const agentDataDir = marketConfig ? marketConfig.data_dir : 'agent_data';
            const logPath = `data/${agentDataDir}/${agentFolder}/log/${date}/log.jsonl`;
            const response = await fetch(logPath);

            // If log file doesn't exist, return null (no reasoning available)
            if (!response.ok) {
                return null;
            }

            const text = await response.text();
            const lines = text.trim().split('\n').filter(line => line.trim());

            // Collect all assistant messages
            const assistantMessages = [];
            for (const line of lines) {
                try {
                    const data = JSON.parse(line);
                    if (data.new_messages) {
                        // Handle both array and single object formats
                        const messages = Array.isArray(data.new_messages)
                            ? data.new_messages
                            : [data.new_messages];

                        for (const msg of messages) {
                            if (msg.role === 'assistant') {
                                // Remove <FINISH_SIGNAL> tag if present
                                const content = msg.content.replace(/<FINISH_SIGNAL>/g, '').trim();
                                if (content) {
                                    assistantMessages.push(content);
                                }
                            }
                        }
                    }
                } catch (e) {
                    console.warn(`Failed to parse line: ${line}`, e);
                }
            }

            if (assistantMessages.length > 0) {
                // Concatenate all assistant messages with double newlines
                return assistantMessages.join('\n\n');
            }

            return null;
        } catch (error) {
            console.warn(`Failed to load thinking for ${agentFolder} at ${date}:`, error);
            return null;
        }
    }

    // Calculate profit for a transaction
    async calculateTransactionProfit(transaction) {
        // For now, return null - will be calculated when price data is integrated
        // This would need: buy price at transaction time, sell price (if sell), or current price
        return null;
    }

    // Build leaderboard data
    async buildLeaderboard(allAgentsData) {
        const leaderboard = [];
        const currentMarket = window.dataLoader ? window.dataLoader.getMarket() : 'cn';

        // Map front-end market IDs to config.yaml market keys
        const marketMapping = {
            'sse50':  'cn',        // 上证50 -> config.yaml markets.cn
            'zxg':    'cn_sxg',    // 自选股 -> config.yaml markets.cn_sxg
            'csi300': 'cn',        // 沪深300 -> config.yaml markets.cn
            'zz500':  'cn',        // 中证500 -> config.yaml markets.cn
            'gem':    'cn',        // 创业板指 -> config.yaml markets.cn
            'cn':     'cn',        // 上证50（默认）
            'cn_sxg': 'cn_sxg',    // 自选股
        };
        
        const effectiveMarket = marketMapping[currentMarket] || currentMarket;
        console.log('[buildLeaderboard] currentMarket:', currentMarket, '=> effectiveMarket:', effectiveMarket);

        for (const [agentName, data] of Object.entries(allAgentsData)) {
            // Extract folder key from full path (e.g., 'agent_data_astock/sse_50_day/glm-4.5-air' => 'glm-4.5-air')
            const folderKey = agentName.split('/').pop();
            
            const assetHistory = data.assetHistory || [];
            const initialValue = assetHistory[0]?.value || 10000;
            const finalValue = assetHistory[assetHistory.length - 1]?.value || initialValue;
            const gain = finalValue - initialValue;
            const gainPercent = ((finalValue - initialValue) / initialValue) * 100;

            leaderboard.push({
                agentName: agentName,
                folderKey: folderKey,
                displayName: window.configLoader.getDisplayName(folderKey, effectiveMarket),
                icon: window.configLoader.getIcon(folderKey, effectiveMarket),
                color: window.configLoader.getColor(folderKey, effectiveMarket),
                initialValue: initialValue,
                currentValue: finalValue,
                gain: gain,
                gainPercent: gainPercent,
                return: data.return || gainPercent
            });
        }

        // Sort by current value (descending)
        leaderboard.sort((a, b) => b.currentValue - a.currentValue);

        // Add rank
        leaderboard.forEach((item, index) => {
            item.rank = index + 1;
        });

        this.leaderboardData = leaderboard;
        return leaderboard;
    }

    // Get most recent N transactions
    getMostRecentTransactions(n = 100) {
        return this.allTransactions.slice(0, n);
    }

    // Format currency
    formatCurrency(value) {
        if (value === null || value === undefined) return 'N/A';
        return new Intl.NumberFormat('zh-CN', { 
            style: 'currency',
            currency: 'CNY',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(value);
    } //zh-CN, en-US

    // Format percent
    formatPercent(value) {
        if (value === null || value === undefined) return 'N/A';
        const sign = value >= 0 ? '+' : '';
        return `${sign}${value.toFixed(2)}%`;
    }

    // Format date/time
    formatDateTime(dateStr) {
        const date = new Date(dateStr);
        return date.toLocaleString('zh-CN', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // Get action icon
    getActionIcon(action) {
        return action === 'buy' ? '📈' : '📉';
    }

    // Get action color
    getActionColor(action) {
        return action === 'buy' ? 'var(--success)' : 'var(--danger)';
    }
}

// Create global instance
window.transactionLoader = new TransactionLoader();