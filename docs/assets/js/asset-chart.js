// 首页- Asset Evolution Chart - Main page visualization

const dataLoader = new DataLoader();
window.dataLoader = dataLoader; // Export to global for transaction-loader
let chartInstance = null;
let allAgentsData = {};
let isLogScale = false;
let currentSelectedAgent = null;

// Color palette for different agents
const agentColors = [
    '#00d4ff', // Cyan Blue
    '#00ffcc', // Cyan
    '#ff006e', // Hot Pink
    '#ffbe0b', // Yellow
    '#8338ec', // Purple
    '#3a86ff', // Blue
    '#fb5607', // Orange
    '#06ffa5'  // Mint
];


const iconImageCache = {}; //Cache for loaded SVG images

// Function to load SVG as image
function loadIconImage(iconPath) {
    return new Promise((resolve, reject) => {
        if (iconImageCache[iconPath]) {
            resolve(iconImageCache[iconPath]);
            return;
        }
        
        const img = new Image();
        img.onload = () => {
            iconImageCache[iconPath] = img;
            resolve(img);
        };
        img.onerror = reject;
        img.src = iconPath;
    });
}

// Update market subtitle based on current market
function updateMarketSubtitle() {
    console.log('[updateMarketSubtitle] Starting...');
    
    let currentMarket = dataLoader.getMarket();
    console.log('[updateMarketSubtitle] Raw market from dataLoader:', currentMarket);

    // 新增：映射邏輯，將前端的市場 ID 映射到 config.yaml 中的市場 key
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

    // 如果是已知的子市場，就映射到 config.yaml 裡存在的 key
    const effectiveMarket = marketMapping[currentMarket] || currentMarket;
    console.log('[updateMarketSubtitle] Effective market after mapping:', effectiveMarket);

    const marketConfig = dataLoader.getMarketConfig(effectiveMarket);  // ← 改用 effectiveMarket
    console.log('[updateMarketSubtitle] Market config:', marketConfig);

    const subtitleElement = document.getElementById('marketSubtitle');
    console.log('[updateMarketSubtitle] Subtitle element:', subtitleElement);

    if (marketConfig && marketConfig.subtitle && subtitleElement) {
        subtitleElement.textContent = marketConfig.subtitle;
        console.log('Updated subtitle to:', marketConfig.subtitle);
    } else {
        console.warn('[updateMarketSubtitle] Missing required data:', {
            hasMarketConfig: !!marketConfig,
            hasSubtitle: marketConfig?.subtitle,
            hasElement: !!subtitleElement,
            usedMarket: effectiveMarket
        });

        // 保底顯示（可選）
        if (subtitleElement) {
            subtitleElement.textContent = "A股市場";
        }
    }
}

// Load data and refresh UI
async function loadDataAndRefresh() {
    showLoading();

    try {
        // Ensure config is loaded first
        await dataLoader.initialize();

        // Update subtitle for the current market
        updateMarketSubtitle();

        // Load all agents data
        console.log('Loading all agents data...');
        allAgentsData = await dataLoader.loadAllAgentsData();
        console.log('Data loaded:', allAgentsData);

        // Preload all agent icons
        const agentNames = Object.keys(allAgentsData);
        const iconPromises = agentNames.map(agentName => {
            const folderKey = agentName.split('/').pop();           // ← 新增这行
            //const iconPath = dataLoader.getAgentIcon(agentName);
            const iconPath = dataLoader.getAgentIcon(agentName);    // ← 改成 folderKey
            console.warn(`load icon for ${agentName}:`, agentName);
            console.warn(`load icon for ${agentName}:`, folderKey);
            console.warn(`load icon for ${agentName}:`, iconPath);
            return loadIconImage(iconPath).catch(err => {
                console.warn(`Failed to load icon for ${agentName}:`, err);
            });
        });
        await Promise.all(iconPromises);
        console.log('Icons preloaded');

        // Destroy existing chart if it exists
        if (chartInstance) {
            console.log('Destroying existing chart...');
            chartInstance.destroy();
            chartInstance = null;
            // Wait a tick to ensure chart is fully destroyed before creating new one
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        // Update stats
        updateStats();

        // Create chart
        createChart();

        // Create legend
        createLegend();

        // Create leaderboard and action flow
        await createLeaderboard();
        await createActionFlow();

    } catch (error) {
        console.error('Error loading data:', error);
        alert('Failed to load trading data. Please check console for details.');
    } finally {
        hideLoading();
    }
}

// Initialize the page
async function init() {
    // Set up event listeners first
    setupEventListeners();

    // Load initial data
    await loadDataAndRefresh();
    
    // Initialize UI state
    updateMarketUI();

    // 在 loadDataAndRefresh() 的 finally 块中添加：
    // setupTradeHistoryCollapsible();
}

// Update statistics cards
function updateStats() {
    const agentNames = Object.keys(allAgentsData);
    const agentCount = agentNames.length;

    // Calculate date range
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

    // Find best performer
    let bestAgent = null;
    let bestReturn = -Infinity;

    agentNames.forEach(name => {
        const returnValue = allAgentsData[name].return;
        if (returnValue > bestReturn) {
            bestReturn = returnValue;
            bestAgent = name;
        }
    });

    // Update DOM
    document.getElementById('agent-count').textContent = agentCount;

    // Format date range - uniform format for both markets
    const formatDateRange = (dateStr) => {
        if (!dateStr) return 'N/A'; // Parse date string (handles both "2025-10-01" and "2025-10-01 10:00:00" formats)
        const date = new Date(dateStr);
        // return date.toLocaleString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
        return date.toLocaleString('zh-CN', {year: 'numeric', month: 'numeric', day: 'numeric' });
    };

    document.getElementById('trading-period').textContent = minDate && maxDate ?
        `${formatDateRange(minDate)} 至 ${formatDateRange(maxDate)}` : 'N/A';
    
    // Extract folder name from full path for display name lookup
    const bestPerformerName = bestAgent ? bestAgent.split('/').pop() : null;
    document.getElementById('best-performer').textContent = bestPerformerName ?
        dataLoader.getAgentDisplayName(bestPerformerName) : 'N/A';
    document.getElementById('avg-return').textContent = bestAgent ?
        dataLoader.formatPercent(bestReturn) : 'N/A';
}

// Create the main chart
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
            color = dataLoader.getAgentBrandColor(agentName) || '#ff6b00';
            borderWidth = 2;
            borderDash = [5, 5]; // Dashed line for benchmark
        } else {
            color = dataLoader.getAgentBrandColor(agentName) || agentColors[index % agentColors.length];
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
            agentFolder: agentName, // folderKey,
            agentIcon: dataLoader.getAgentIcon(agentName)
        };

        console.log(`[DATASET OBJECT ${index}] borderColor: ${datasetObj.borderColor}, pointHoverBackgroundColor: ${datasetObj.pointHoverBackgroundColor}`);
        console.log(`[DATASET OBJECT ${index}] agentIcon: ${datasetObj.agentIcon}, agentFolder: ${datasetObj.agentFolder}`);
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
    console.log('Preload icon key example:', dataLoader.getAgentIcon('glm-4.5-air'));
    console.log('Preload icon key example2:', dataLoader.getAgentIcon('agent_data_astock/sse_50_day/glm-4.5-air')); // agent_data_astock/sse_50_day/glm-4.5-air
    console.log('Dataset agentIcon example:', datasets[0].agentIcon);
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

// Create legend
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

// Toggle between linear and log scale
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

// Export chart data as CSV
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

// Update UI based on current market state
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

// Set up event listeners
function setupEventListeners() {
    document.getElementById('toggle-log').addEventListener('click', toggleScale);
    document.getElementById('export-chart').addEventListener('click', exportData);
    document.getElementById('k-line-mode').addEventListener('click', toggleBetweenCharts);
    
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
                await refreshKlineForNewMarket();  //刷新k线
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

// Create leaderboard
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

//加载最近交易记录
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

function hideLoadingIndicator() {
    const existingLoader = actionFlowState.container.querySelector('.transactions-loading');
    if (existingLoader) {
        existingLoader.remove();
    }
}

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

// Format thinking text into paragraphs
function formatThinking(text) {
    // Split by double newlines or numbered lists
    const paragraphs = text.split(/\n\n+/).filter(p => p.trim());

    if (paragraphs.length === 0) {
        return `<p>${text}</p>`;
    }

    return paragraphs.map(p => `<p>${p.trim()}</p>`).join('');
}

// Loading overlay controls
function showLoading() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

// === 改进版：更新最近交易记录（修复日期无年份 + 价格显示0）===
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

// Force default market selection on load 解决index默认下拉列表问题
const marketSelector = document.getElementById('marketSelector');
marketSelector.value = 'sse50';  // Set value directly
const defaultOption = marketSelector.querySelector('option[value="sse50"]');
if (defaultOption) {
    defaultOption.selected = true;  // Explicitly select the option
}
dataLoader.setMarket('sse50');  // Sync with data loader
updateMarketUI();  // Update any UI dependent on market
marketSelector.dispatchEvent(new Event('change'));  // Trigger change event to load data if needed

// Add debug logging to verify
console.log('Default market forced to:', marketSelector.value);
console.log('Selected option:', marketSelector.options[marketSelector.selectedIndex].text);


// Initialize on page load
window.addEventListener('DOMContentLoaded', init);

const full = "agent_data_astock/sse_50_day/glm-4.5-air";
const short = "glm-4.5-air";
console.log('Full:', dataLoader.getAgentIcon(full));  // 应为自定义，如"./figs/zhipu-color.svg"
console.log('Short:', dataLoader.getAgentIcon(short)); // 目前为"./figs/stock.svg"（bug）

