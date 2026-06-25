/**
 * Stock Manager - choose_stock.js
 * 管理ashare_symbol.py中的股票列表（无需API服务）
 */

class StockManager {
    constructor() {
        this.stocks = {};
        this.originalStocks = {};
        this.init();
    }

    async init() {
        await this.loadStocks();
        this.renderUI();
        this.setupEventListeners();
    }

    /**
     * 加载股票数据
     */
    async loadStocks() {
        try {
            const response = await fetch('data/stocks.json');
            if (!response.ok) throw new Error('Failed to load stocks.json');
            
            this.stocks = await response.json();
            
            const oriResponse = await fetch('data/stocks_ori.json');
            if (oriResponse.ok) {
                this.originalStocks = await oriResponse.json();
            } else {
                this.originalStocks = JSON.parse(JSON.stringify(this.stocks));
            }
            
            console.log('✓ Stock data loaded');
        } catch (error) {
            console.error('Load error:', error);
            this.showError('加载股票数据失败: ' + error.message);
        }
    }

    /**
     * 渲染UI
     */
    renderUI() {
        const mainContent = document.querySelector('main');
        if (!mainContent) return;

        const portfolioGrid = mainContent.querySelector('.portfolio-grid');
        if (portfolioGrid) portfolioGrid.innerHTML = '';

        let managerSection = document.getElementById('stock-manager');
        if (!managerSection) {
            managerSection = document.createElement('section');
            managerSection.id = 'stock-manager';
            mainContent.appendChild(managerSection);
        }

        managerSection.innerHTML = `
            <div class="manager-header">
                <div class="header-info">
                    <h3>股票组管理</h3>
                    <p class="header-subtitle">编辑、维护和保存股票配置</p>
                </div>
                <div class="manager-actions">
                    <button id="btn-add-group" class="btn btn-primary">＋ 新增组</button>
                    <button id="btn-save"      class="btn btn-success">📁 保存</button>
                    <button id="btn-reset"     class="btn btn-warning">↺ 恢复默认</button>
                    <button id="btn-download"  class="btn btn-info">⬇ 下载数据</button>
                </div>
            </div>

            <div id="stock-groups" class="stock-groups-container"></div>

            <!-- 终端输出面板（默认隐藏） -->
            <div id="terminal-panel" class="terminal-panel" style="display:none; margin-top:1.5rem;">
                <div class="terminal-bar">
                    <div class="terminal-bar-left">
                        <span id="terminal-status-dot" class="terminal-status-dot"></span>
                        <span class="terminal-title">终端输出 — 1.get_price_tushare.py</span>
                    </div>
                    <div class="terminal-bar-right">
                        <span id="terminal-status-text" class="terminal-status-text">就绪</span>
                        <button class="terminal-close-btn" onclick="document.getElementById('terminal-panel').style.display='none'">✕</button>
                    </div>
                </div>
                <div id="terminal-progress" class="terminal-progress" style="display:none;">
                    <div class="terminal-progress-fill"></div>
                </div>
                <div id="terminal-body" class="terminal-body"></div>
            </div>
        `;

        this.renderStockGroups();
    }

    /**
     * 渲染股票组
     */
    renderStockGroups() {
        const container = document.getElementById('stock-groups');
        if (!container) return;

        container.innerHTML = '';
        Object.keys(this.stocks).forEach(groupName => {
            container.appendChild(this.createGroupCard(groupName));
        });
    }

    /**
     * 创建股票组卡片
     */
    createGroupCard(groupName) {
        const stocks = this.stocks[groupName];
        const card = document.createElement('div');
        card.className = 'stock-group-card';
        card.id = `group-${groupName}`;

        const header = document.createElement('div');
        header.className = 'group-card-header';
        header.innerHTML = `
            <div class="group-info">
                <h4>${groupName}</h4>
                <span class="stock-count">${stocks.length} 支</span>
            </div>
        `;

        const preview = document.createElement('div');
        preview.className = 'group-preview';
        const displayStocks = stocks.slice(0, 3).map(s => `<span>${s}</span>`).join('');
        const more = stocks.length > 3 ? `<span class="more-indicator">+${stocks.length - 3} more</span>` : '';
        preview.innerHTML = displayStocks + more;

        const actions = document.createElement('div');
        actions.className = 'group-actions';
        actions.innerHTML = `
            <button class="btn-action btn-view"   onclick="stockManager.showGroupDetails('${groupName}')">查看</button>
            <button class="btn-action btn-edit"   onclick="stockManager.showEditDialog('${groupName}')">编辑</button>
            <button class="btn-action btn-delete" onclick="stockManager.deleteGroup('${groupName}')">删除</button>
        `;

        card.appendChild(header);
        card.appendChild(preview);
        card.appendChild(actions);
        return card;
    }

    /**
     * 显示股票组详情
     */
    showGroupDetails(groupName) {
        const stocks = this.stocks[groupName];
        const modal = this.createModal(
            `${groupName} - 详情（${stocks.length} 支）`,
            this.createDetailContent(stocks)
        );
        document.body.appendChild(modal);
    }

    createDetailContent(stocks) {
        const content = document.createElement('div');
        content.className = 'detail-content';
        const list = stocks.map((stock, index) =>
            `<div class="stock-line">${index + 1}. ${stock}</div>`
        ).join('');
        content.innerHTML = `<div class="stocks-list">${list}</div>`;
        return content;
    }

    /**
     * 显示编辑对话框
     */
    showEditDialog(groupName) {
        const stocks = this.stocks[groupName];
        const modal = this.createModal(
            `编辑 - ${groupName}`,
            this.createEditForm(groupName, stocks),
            true
        );
        document.body.appendChild(modal);

        const saveBtn = modal.querySelector('.btn-save');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveGroupEdit(groupName, modal));
        }
    }

    createEditForm(groupName, stocks) {
        const form = document.createElement('div');
        form.className = 'edit-form';

        const textarea = document.createElement('textarea');
        textarea.className = 'stocks-textarea';
        textarea.id = `edit-textarea-${groupName}`;
        textarea.placeholder = '每行一个股票代码，格式: 600000.SH';
        textarea.value = stocks.join('\n');
        textarea.rows = 15;

        const footer = document.createElement('div');
        footer.className = 'modal-actions';
        footer.innerHTML = `
            <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
            <button class="btn btn-save btn-primary">保存</button>
        `;

        form.appendChild(textarea);
        form.appendChild(footer);
        return form;
    }

    saveGroupEdit(groupName, modal) {
        const textarea = modal.querySelector('.stocks-textarea');
        const stocks = textarea.value
            .split('\n')
            .map(s => s.trim())
            .filter(s => s.length > 0);

        if (stocks.length === 0) { this.showError('股票列表不能为空'); return; }

        this.stocks[groupName] = stocks;
        this.showSuccess(`✓ ${groupName} 已保存 (${stocks.length} 支)`);
        modal.remove();
        this.renderStockGroups();
    }

    /**
     * 新增组
     */
    showAddGroupDialog() {
        const modal = this.createModal('新增股票组', this.createAddForm(), true);
        document.body.appendChild(modal);

        const saveBtn = modal.querySelector('.btn-save');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveNewGroup(modal));
        }
    }

    createAddForm() {
        const form = document.createElement('div');
        form.className = 'add-form';
        form.innerHTML = `
            <div class="form-group">
                <label>组名称</label>
                <input type="text" id="new-group-name" class="form-input" placeholder="如: MyPortfolio">
            </div>
            <div class="form-group">
                <label>股票列表</label>
                <textarea id="new-group-stocks" class="stocks-textarea" placeholder="每行一个股票代码，如: 600000.SH" rows="15"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                <button class="btn btn-save btn-primary">创建</button>
            </div>
        `;
        return form;
    }

    saveNewGroup(modal) {
        const groupName = modal.querySelector('#new-group-name').value.trim();
        const stocksText = modal.querySelector('#new-group-stocks').value;

        if (!groupName) { this.showError('请输入组名称'); return; }
        if (this.stocks[groupName]) { this.showError(`组 '${groupName}' 已存在`); return; }

        const stocks = stocksText
            .split('\n')
            .map(s => s.trim())
            .filter(s => s.length > 0);

        if (stocks.length === 0) { this.showError('股票列表不能为空'); return; }

        this.stocks[groupName] = stocks;
        this.showSuccess(`✓ 组 '${groupName}' 已创建 (${stocks.length} 支)`);
        modal.remove();
        this.renderStockGroups();
    }

    /**
     * 删除股票组
     */
    deleteGroup(groupName) {
        if (!confirm(`确定要删除 '${groupName}' 吗？`)) return;
        delete this.stocks[groupName];
        this.showSuccess(`✓ '${groupName}' 已删除`);
        this.renderStockGroups();
    }

    /**
     * 恢复默认
     */
    async resetToDefault() {
        if (!confirm('确定要恢复为默认配置吗？所有修改将丢失。')) return;
        this.stocks = JSON.parse(JSON.stringify(this.originalStocks));
        await this.saveStocks(true);
        this.renderStockGroups();
    }

    /**
     * ─────────────────────────────────────────
     * 下载数据 — 调用后端 /download-stocks 接口
     * 并将脚本输出实时渲染到终端面板
     * ─────────────────────────────────────────
     */
    async downloadStocks() {
        const panel    = document.getElementById('terminal-panel');
        const body     = document.getElementById('terminal-body');
        const progress = document.getElementById('terminal-progress');
        const dot      = document.getElementById('terminal-status-dot');
        const statusTx = document.getElementById('terminal-status-text');
        const btn      = document.getElementById('btn-download');

        if (!panel || !body) return;

        // 展开面板、清空旧内容
        panel.style.display = 'block';
        body.innerHTML = '';
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        // 进入"运行中"状态
        btn.disabled = true;
        btn.textContent = '⬇ 下载中…';
        dot.className = 'terminal-status-dot dot-running';
        statusTx.textContent = '运行中…';
        progress.style.display = 'block';

        this.appendTerminalLine('▶ POST /download-stocks', 'info');
        this.appendTerminalLine('  脚本: data/1.get_price_tushare.py', 'dim');

        try {
            const response = await fetch('http://127.0.0.1:9999/download-stocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });

            const result = await response.json();

            // 渲染 stdout（按行拆分）
            if (result.stdout && result.stdout.trim()) {
                this.appendTerminalLine('── stdout ──────────────────', 'dim');
                result.stdout.split('\n').forEach(line => {
                    if (line.trim()) this.appendTerminalLine(line, 'default');
                });
            }

            // 渲染 stderr（有内容时才显示）
            if (result.stderr && result.stderr.trim()) {
                this.appendTerminalLine('── stderr ──────────────────', 'dim');
                result.stderr.split('\n').forEach(line => {
                    if (line.trim()) this.appendTerminalLine(line, 'error');
                });
            }

            if (result.success) {
                this.appendTerminalLine(`✓ ${result.message}  (exit 0)`, 'ok');
                dot.className = 'terminal-status-dot dot-ok';
                statusTx.textContent = '完成';
                this.showSuccess('✓ 数据下载完成');
            } else {
                this.appendTerminalLine(
                    `✗ ${result.message}  (exit ${result.returncode ?? '?'})`, 'error'
                );
                dot.className = 'terminal-status-dot dot-error';
                statusTx.textContent = `失败 (exit ${result.returncode ?? '?'})`;
                this.showError('下载脚本执行失败，请查看终端输出');
            }

        } catch (error) {
            this.appendTerminalLine(`✗ 无法连接到服务: ${error.message}`, 'error');
            this.appendTerminalLine('  请先运行: python docs/save_stocks_server.py', 'dim');
            dot.className = 'terminal-status-dot dot-error';
            statusTx.textContent = '连接失败';
            this.showError('无法连接到本地服务 (127.0.0.1:9999)');
        } finally {
            progress.style.display = 'none';
            btn.disabled = false;
            btn.textContent = '⬇ 下载数据';
            // 滚动到终端底部
            body.scrollTop = body.scrollHeight;
        }
    }

    /**
     * 向终端面板追加一行输出
     * @param {string} text  - 行内容
     * @param {'default'|'ok'|'error'|'info'|'dim'} type
     */
    appendTerminalLine(text, type = 'default') {
        const body = document.getElementById('terminal-body');
        if (!body) return;

        const line = document.createElement('div');
        line.className = `terminal-line terminal-line--${type}`;
        line.textContent = text;
        body.appendChild(line);
        body.scrollTop = body.scrollHeight;
    }

    /**
     * 创建模态框
     */
    createModal(title, content, isLarge = false) {
        const modal = document.createElement('div');
        modal.className = 'modal';

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.addEventListener('click', () => modal.remove());

        const dialog = document.createElement('div');
        dialog.className = isLarge ? 'modal-dialog modal-lg' : 'modal-dialog';

        const header = document.createElement('div');
        header.className = 'modal-header';
        header.innerHTML = `
            <h3>${title}</h3>
            <button class="btn-close" onclick="this.closest('.modal').remove()">✕</button>
        `;

        const body = document.createElement('div');
        body.className = 'modal-body';
        body.appendChild(content);

        dialog.appendChild(header);
        dialog.appendChild(body);
        modal.appendChild(overlay);
        modal.appendChild(dialog);
        return modal;
    }

    /**
     * 通知
     */
    showNotification(message, type) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    showError(message)   { this.showNotification(message, 'error'); }
    showSuccess(message) { this.showNotification(message, 'success'); }

    /**
     * 保存到 stocks.json
     */
    async saveStocks(isReset = false) {
        try {
            const response = await fetch('http://127.0.0.1:9999/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.stocks)
            });

            const result = await response.json();

            if (result.success) {
                const message = isReset
                    ? `✓ 已恢复为默认配置 (${Object.keys(this.stocks).length} 个组)`
                    : `✓ 已保存到 stocks.json (${Object.keys(this.stocks).length} 个组)`;
                this.showSuccess(message);
            } else {
                this.showError('保存失败: ' + result.error);
            }
        } catch (error) {
            this.showError('无法连接到保存服务: ' + error.message + '\n\n请先运行: python docs/save_stocks_server.py');
        }
    }

    /**
     * 事件监听
     */
    setupEventListeners() {
        document.getElementById('btn-add-group')
            ?.addEventListener('click', () => this.showAddGroupDialog());

        document.getElementById('btn-save')
            ?.addEventListener('click', () => this.saveStocks());

        document.getElementById('btn-reset')
            ?.addEventListener('click', () => this.resetToDefault());

        document.getElementById('btn-download')
            ?.addEventListener('click', () => this.downloadStocks());

        document.getElementById('btn-export')
            ?.addEventListener('click', () => this.exportPython());
    }
}

// 全局实例
let stockManager;
document.addEventListener('DOMContentLoaded', () => {
    stockManager = new StockManager();
});