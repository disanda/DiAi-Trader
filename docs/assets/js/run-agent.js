/**
 * Agent Manager - run-agent.js
 * 配置文件的读写全部通过 http://127.0.0.1:9999 后端完成，
 * 避免浏览器无法跨目录 fetch 静态文件的问题。
 */

class AgentManager {
    constructor() {
        this.config = null;
        // 后端（项目根目录）视角的相对路径
        this.configPathForBackend = 'configs/astock_config_day.json';
        this.isRunning = false;
        this.init();
    }

    async init() {
        await this.loadConfig();
        this.renderUI();
        this.setupEventListeners();
    }

    // ─────────────────────────────────────────
    // 读取配置（通过 9999 后端）
    // ─────────────────────────────────────────

    async loadConfig() {
        try {
            const res = await fetch(
                `http://127.0.0.1:9999/load-config?path=${encodeURIComponent(this.configPathForBackend)}`
            );
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const result = await res.json();
            if (!result.success) throw new Error(result.error || '加载失败');
            this.config = result.data;
            console.log(`✓ 配置加载成功，共 ${this.config.models?.length ?? 0} 个智能体`);
        } catch (err) {
            console.warn('⚠ 加载配置失败，使用空模板:', err.message);
            this.showError('加载配置失败: ' + err.message + '  →  请确认 save_stocks_server.py 已运行');
            this.config = this.getDefaultConfig();
        }
    }

    getDefaultConfig() {
        return {
            agent_type: 'BaseAgentAStock',
            market: 'cn',
            date_range: { init_date: '2026-03-01', end_date: '2026-03-10' },
            models: [],
            agent_config: { max_steps: 3, max_retries: 3, base_delay: 1.0, initial_cash: 1000000.0 },
            log_config: {
                model_data_path: './data/agent_data_astock/ZSG_17_day',
                Ashare_data_path: './data/a_stock_data/ZSG_17_day/merged.jsonl',
                Ashare_symbols: 'ZSG_17',
                BAR_MODE: 'daily'
            }
        };
    }

    // ─────────────────────────────────────────
    // 保存配置到磁盘（通过 9999 后端）
    // ─────────────────────────────────────────

    async saveConfigToDisk(silent = false) {
        try {
            const res = await fetch('http://127.0.0.1:9999/save-config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: this.configPathForBackend, data: this.config })
            });
            const result = await res.json();
            if (result.success) {
                if (!silent) this.showSuccess(`✓ 配置已保存到 ${this.configPathForBackend}`);
            } else {
                this.showError('保存失败: ' + result.error);
            }
            return result.success;
            
        } catch (err) {
            this.showError('无法连接到服务 (9999): ' + err.message);
            return false;
        }
    }

    // ─────────────────────────────────────────
    // UI 渲染
    // ─────────────────────────────────────────

    renderUI() {
        const mainContent = document.querySelector('main');
        if (!mainContent) return;

        let section = document.getElementById('agent-manager');
        if (!section) {
            section = document.createElement('section');
            section.id = 'agent-manager';
            mainContent.appendChild(section);
        }

        section.innerHTML = `
            <div class="manager-header">
                <div class="header-info">
                    <h3>智能体管理</h3>
                    <p class="header-subtitle">配置、管理并运行 AI 交易智能体</p>
                </div>
                <div class="manager-actions">
                    <button id="btn-add-agent"  class="btn btn-primary">＋ 新增智能体</button>
                    <button id="btn-edit-rules" class="btn btn-info">⚙ 编辑运行规则</button>
                    <button id="btn-save-cfg"   class="btn btn-warning"> 保存配置</button>
                    <button id="btn-run-agent"  class="btn btn-success">▶ 运行</button>
                </div>
            </div>

            <div id="agent-cards" class="stock-groups-container"></div>

            <!-- 终端面板 -->
            <div id="terminal-panel" class="terminal-panel" style="display:none; margin-top:1.5rem;">
                <div class="terminal-bar">
                    <div class="terminal-bar-left">
                        <span id="terminal-status-dot" class="terminal-status-dot"></span>
                        <span class="terminal-title" id="terminal-title-text">终端输出</span>
                    </div>
                    <div class="terminal-bar-right">
                        <span id="terminal-status-text" class="terminal-status-text">就绪</span>
                        <button class="terminal-close-btn"
                                onclick="document.getElementById('terminal-panel').style.display='none'">✕</button>
                    </div>
                </div>
                <div id="terminal-progress" class="terminal-progress" style="display:none;">
                    <div class="terminal-progress-fill"></div>
                </div>
                <div id="terminal-body" class="terminal-body"></div>
            </div>
        `;

        this.renderAgentCards();
    }

    renderAgentCards() {
        const container = document.getElementById('agent-cards');
        if (!container || !this.config) return;
        container.innerHTML = '';

        if (!this.config.models || this.config.models.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🤖</div>
                    <p>暂无智能体配置</p>
                    <p class="empty-sub">点击「新增智能体」添加，或确认后端服务已启动</p>
                </div>`;
            return;
        }

        this.config.models.forEach((model, index) => {
            container.appendChild(this.createAgentCard(model, index));
        });
    }

    createAgentCard(model, index) {
        const card = document.createElement('div');
        card.className = `stock-group-card agent-card${model.enabled ? '' : ' agent-card--disabled'}`;
        card.id = `agent-card-${index}`;

        const badge = model.enabled
            ? `<span class="badge badge-enabled">✓ 启用</span>`
            : `<span class="badge badge-disabled">✕ 禁用</span>`;

        const maskedKey = model.openai_api_key
            ? (model.openai_api_key.length > 8
                ? model.openai_api_key.slice(0, 4) + '••••' + model.openai_api_key.slice(-4)
                : '••••')
            : '（未填写）';

        card.innerHTML = `
            <div class="group-card-header">
                <div class="group-info">
                    <h4> ${this.esc(model.name || '未命名')}</h4>
                    <div class="agent-badges">${badge}</div>
                </div>
            </div>
            <div class="agent-card-body">
                <div class="agent-info-grid">
                    <div class="info-item">
                        <span class="info-label">BaseModel</span>
                        <span class="info-value">${this.esc(model.basemodel || '-')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Signature</span>
                        <span class="info-value">${this.esc(model.signature || '-')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">API URL</span>
                        <span class="info-value info-url">${this.esc(model.openai_base_url || '-')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">API Key</span>
                        <span class="info-value info-key">${maskedKey}</span>
                    </div>
                </div>
            </div>
            <div class="group-actions">
                <button class="btn-action btn-edit"
                        onclick="agentManager.showEditAgentDialog(${index})">编辑</button>
                <button class="btn-action ${model.enabled ? 'btn-warning' : 'btn-view'}"
                        onclick="agentManager.toggleAgent(${index})">
                    ${model.enabled ? '禁用' : '启用'}
                </button>
                <button class="btn-action btn-delete"
                        onclick="agentManager.deleteAgent(${index})">删除</button>
            </div>
        `;
        return card;
    }

    esc(str) {
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ─────────────────────────────────────────
    // 新增智能体
    // ─────────────────────────────────────────

    showAddAgentDialog() {
        const tpl = { name: '', basemodel: '', signature: '', enabled: true, openai_base_url: '', openai_api_key: '' };
        const modal = this.createModal('新增智能体', this.createAgentForm(tpl, true), true);
        document.body.appendChild(modal);
        modal.querySelector('.btn-save')?.addEventListener('click', () => this.saveNewAgent(modal));
    }

    saveNewAgent(modal) {
        const data = this.readAgentForm(modal);
        if (!data) return;
        if (!this.config.models) this.config.models = [];
        this.config.models.push(data);
        this.showSuccess(`✓ 智能体 '${data.name}' 已添加（请点击「💾 保存配置」写入磁盘）`);
        modal.remove();
        this.renderAgentCards();
    }

    // ─────────────────────────────────────────
    // 编辑智能体
    // ─────────────────────────────────────────

    showEditAgentDialog(index) {
        const model = this.config.models[index];
        const modal = this.createModal(`编辑智能体 — ${model.name}`, this.createAgentForm(model, false), true);
        document.body.appendChild(modal);
        modal.querySelector('.btn-save')?.addEventListener('click', () => this.saveAgentEdit(index, modal));
    }

    saveAgentEdit(index, modal) {
        const data = this.readAgentForm(modal);
        if (!data) return;
        this.config.models[index] = data;
        this.showSuccess(`✓ '${data.name}' 已更新（请点击「💾 保存配置」写入磁盘）`);
        modal.remove();
        this.renderAgentCards();
    }

    createAgentForm(model, isNew) {
        const form = document.createElement('div');
        form.className = 'add-form';
        form.innerHTML = `
            <div class="form-row">
                <div class="form-group">
                    <label>名称 (name) <span class="required">*</span></label>
                    <input type="text" class="form-input" name="name"
                           value="${this.esc(model.name || '')}" placeholder="如: glm-4.5-air">
                </div>
                <div class="form-group">
                    <label>启用状态</label>
                    <select class="form-input" name="enabled">
                        <option value="true"  ${model.enabled !== false ? 'selected' : ''}>✓ 启用</option>
                        <option value="false" ${model.enabled === false  ? 'selected' : ''}>✕ 禁用</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>BaseModel <span class="required">*</span></label>
                    <input type="text" class="form-input" name="basemodel"
                           value="${this.esc(model.basemodel || '')}" placeholder="如: glm-4.5-air">
                </div>
                <div class="form-group">
                    <label>Signature <span class="required">*</span></label>
                    <input type="text" class="form-input" name="signature"
                           value="${this.esc(model.signature || '')}" placeholder="如: glm-4.5-air">
                </div>
            </div>
            <div class="form-group">
                <label>API Base URL</label>
                <input type="text" class="form-input" name="openai_base_url"
                       value="${this.esc(model.openai_base_url || '')}"
                       placeholder="如: https://open.bigmodel.cn/api/paas/v4">
            </div>
            <div class="form-group">
                <label>API Key</label>
                <input type="password" class="form-input" name="openai_api_key"
                       value="${this.esc(model.openai_api_key || '')}"
                       placeholder="填写 API Key（保存后脱敏显示）">
                <button type="button" class="btn-toggle-key"
                        onclick="const i=this.previousElementSibling;
                                 i.type=i.type==='password'?'text':'password';
                                 this.textContent=i.type==='password'?'👁 显示':'🙈 隐藏'">
                    👁 显示
                </button>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                <button class="btn btn-save btn-primary">${isNew ? '创建' : '保存改动'}</button>
            </div>
        `;
        return form;
    }

    readAgentForm(modal) {
        const get = n => modal.querySelector(`[name="${n}"]`)?.value?.trim() || '';
        const name = get('name'), basemodel = get('basemodel'), signature = get('signature');
        if (!name)      { this.showError('请填写名称');      return null; }
        if (!basemodel) { this.showError('请填写 BaseModel'); return null; }
        if (!signature) { this.showError('请填写 Signature'); return null; }
        return { name, basemodel, signature,
                 enabled: get('enabled') === 'true',
                 openai_base_url: get('openai_base_url'),
                 openai_api_key:  get('openai_api_key') };
    }

    // ─────────────────────────────────────────
    // 启用 / 禁用 / 删除
    // ─────────────────────────────────────────

    toggleAgent(index) {
        const m = this.config.models[index];
        m.enabled = !m.enabled;
        this.showSuccess(`✓ '${m.name}' 已${m.enabled ? '启用' : '禁用'}（记得保存配置）`);
        this.renderAgentCards();
    }

    deleteAgent(index) {
        const name = this.config.models[index]?.name || '未命名';
        if (!confirm(`确定要删除智能体 '${name}' 吗？`)) return;
        this.config.models.splice(index, 1);
        this.showSuccess(`✓ '${name}' 已删除（记得保存配置）`);
        this.renderAgentCards();
    }

    // ─────────────────────────────────────────
    // 编辑运行规则
    // ─────────────────────────────────────────

    showEditRulesDialog() {
        const modal = this.createModal('编辑运行规则', this.createRulesForm(), true);
        document.body.appendChild(modal);
        modal.querySelector('.btn-save')?.addEventListener('click', () => this.saveRules(modal));
    }

    createRulesForm() {
        const ac = this.config.agent_config || {};
        const lc = this.config.log_config   || {};
        const dr = this.config.date_range   || {};
        const form = document.createElement('div');
        form.className = 'add-form';
        form.innerHTML = `
            <h4 class="form-section-title">📅 日期范围</h4>
            <div class="form-row">
                <div class="form-group">
                    <label>开始日期</label>
                    <input type="text" class="form-input" name="init_date"
                           value="${dr.init_date || ''}" placeholder="2026-03-01">
                </div>
                <div class="form-group">
                    <label>结束日期</label>
                    <input type="text" class="form-input" name="end_date"
                           value="${dr.end_date || ''}" placeholder="2026-03-10">
                </div>
            </div>

            <h4 class="form-section-title">⚙ Agent 配置</h4>
            <div class="form-row">
                <div class="form-group">
                    <label>max_steps</label>
                    <input type="number" class="form-input" name="max_steps" value="${ac.max_steps ?? 3}">
                </div>
                <div class="form-group">
                    <label>max_retries</label>
                    <input type="number" class="form-input" name="max_retries" value="${ac.max_retries ?? 3}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>base_delay (秒)</label>
                    <input type="number" step="0.1" class="form-input" name="base_delay" value="${ac.base_delay ?? 1.0}">
                </div>
                <div class="form-group">
                    <label>initial_cash</label>
                    <input type="number" class="form-input" name="initial_cash" value="${ac.initial_cash ?? 1000000}">
                </div>
            </div>

            <h4 class="form-section-title">📁 日志 / 数据路径</h4>
            <div class="form-group">
                <label>model_data_path</label>
                <input type="text" class="form-input" name="model_data_path" value="${lc.model_data_path || ''}">
            </div>
            <div class="form-group">
                <label>Ashare_data_path</label>
                <input type="text" class="form-input" name="Ashare_data_path" value="${lc.Ashare_data_path || ''}">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Ashare_symbols（股票组名）</label>
                    <input type="text" class="form-input" name="Ashare_symbols" value="${lc.Ashare_symbols || ''}">
                </div>
                <div class="form-group">
                    <label>BAR_MODE</label>
                    <select class="form-input" name="BAR_MODE">
                        <option ${lc.BAR_MODE === 'daily'  ? 'selected' : ''}>daily</option>
                        <option ${lc.BAR_MODE === 'hourly' ? 'selected' : ''}>hourly</option>
                    </select>
                </div>
            </div>

            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                <button class="btn btn-save btn-primary">保存规则</button>
            </div>
        `;
        return form;
    }

    saveRules(modal) {
        const get = n => modal.querySelector(`[name="${n}"]`)?.value?.trim() || '';
        this.config.date_range   = { init_date: get('init_date'), end_date: get('end_date') };
        this.config.agent_config = {
            max_steps:    Number(get('max_steps')),
            max_retries:  Number(get('max_retries')),
            base_delay:   parseFloat(get('base_delay')),
            initial_cash: parseFloat(get('initial_cash'))
        };
        this.config.log_config = {
            ...this.config.log_config,
            model_data_path:  get('model_data_path'),
            Ashare_data_path: get('Ashare_data_path'),
            Ashare_symbols:   get('Ashare_symbols'),
            BAR_MODE:         get('BAR_MODE')
        };
        this.showSuccess('✓ 运行规则已更新（请点击「💾 保存配置」写入磁盘）');
        modal.remove();
    }

    // ─────────────────────────────────────────
    // 运行智能体（SSE 流式）
    // ─────────────────────────────────────────

    async runAgent() {
        if (this.isRunning) { this.showError('智能体正在运行中，请稍候…'); return; }
        const enabledCount = (this.config.models || []).filter(m => m.enabled).length;
        if (enabledCount === 0) { this.showError('没有启用的智能体，请至少启用一个'); return; }
        if (!confirm(`确认运行？将依次启动 MCP 服务和 ${enabledCount} 个智能体。`)) return;

        const saved = await this.saveConfigToDisk(true);
        if (!saved) { this.showError('保存配置失败，已中止运行'); return; }

        const panel    = document.getElementById('terminal-panel');
        const body     = document.getElementById('terminal-body');
        const prog     = document.getElementById('terminal-progress');
        const dot      = document.getElementById('terminal-status-dot');
        const statusTx = document.getElementById('terminal-status-text');
        const titleTx  = document.getElementById('terminal-title-text');
        const runBtn   = document.getElementById('btn-run-agent');

        panel.style.display = 'block';
        body.innerHTML = '';
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        this.isRunning       = true;
        runBtn.disabled      = true;
        runBtn.textContent   = '⏳ 运行中…';
        dot.className        = 'terminal-status-dot dot-running';
        statusTx.textContent = '运行中…';
        titleTx.textContent  = '终端输出 — mcp_services_start.py → main_client.py';
        prog.style.display   = 'block';

        this.appendTerminalLine('▶ 开始执行任务序列', 'info');
        this.appendTerminalLine(`  配置文件: ${this.configPathForBackend}`, 'dim');
        this.appendTerminalLine('  步骤 1/2: python mcp_services_start.py', 'dim');
        this.appendTerminalLine(`  步骤 2/2: python main_client.py ${this.configPathForBackend}`, 'dim');
        this.appendTerminalLine('─'.repeat(52), 'dim');

        try {
            const res = await fetch('http://127.0.0.1:9999/run-agent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config_path: this.configPathForBackend })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const ct = res.headers.get('content-type') || '';
            if (ct.includes('text/event-stream')) {
                await this.consumeSSE(res, dot, statusTx);
            } else {
                this.renderBatchResult(await res.json(), dot, statusTx);
            }
        } catch (err) {
            this.appendTerminalLine(`✗ 无法连接到服务: ${err.message}`, 'error');
            this.appendTerminalLine('  请先运行: python docs/save_stocks_server.py', 'dim');
            dot.className = 'terminal-status-dot dot-error';
            statusTx.textContent = '连接失败';
            this.showError('无法连接到本地服务 (127.0.0.1:9999)');
        } finally {
            prog.style.display   = 'none';
            this.isRunning       = false;
            runBtn.disabled      = false;
            runBtn.textContent   = '▶ 运行';
            body.scrollTop       = body.scrollHeight;
        }
    }

    async consumeSSE(response, dot, statusTx) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const raw of lines) {
                const line = raw.trim();
                if (!line || line === ':') continue;
                if (line.startsWith('data:')) {
                    const payload = line.slice(5).trim();
                    if (payload === '[DONE]') {
                        dot.className = 'terminal-status-dot dot-ok';
                        statusTx.textContent = '完成';
                        this.appendTerminalLine('─'.repeat(52), 'dim');
                        this.appendTerminalLine('✓ 全部任务执行完毕', 'ok');
                        this.showSuccess('✓ 智能体运行完成');
                        return;
                    }
                    try { this.handleSSEEvent(JSON.parse(payload), dot, statusTx); }
                    catch { this.appendTerminalLine(payload, 'default'); }
                }
            }
        }
        dot.className = 'terminal-status-dot dot-ok';
        statusTx.textContent = '完成';
    }

    handleSSEEvent(event, dot, statusTx) {
        switch (event.type) {
            case 'stage':
                this.appendTerminalLine('─'.repeat(52), 'dim');
                this.appendTerminalLine(`▶ ${event.message}`, 'info');
                break;
            case 'stdout': this.appendTerminalLine(event.line, 'default'); break;
            case 'stderr': this.appendTerminalLine(event.line, 'error');   break;
            case 'success':
                this.appendTerminalLine(`✓ ${event.message}`, 'ok');
                dot.className = 'terminal-status-dot dot-ok';
                statusTx.textContent = event.message || '完成';
                break;
            case 'error':
                this.appendTerminalLine(`✗ ${event.message}`, 'error');
                dot.className = 'terminal-status-dot dot-error';
                statusTx.textContent = '失败';
                this.showError(event.message);
                break;
            default:
                if (event.message) this.appendTerminalLine(event.message, 'default');
        }
    }

    renderBatchResult(result, dot, statusTx) {
        (result.steps || []).forEach(step => {
            this.appendTerminalLine(`▶ ${step.label}`, 'info');
            if (step.stdout) step.stdout.split('\n').forEach(l => l.trim() && this.appendTerminalLine(l, 'default'));
            if (step.stderr) step.stderr.split('\n').forEach(l => l.trim() && this.appendTerminalLine(l, 'error'));
            const ok = step.returncode === 0;
            this.appendTerminalLine(ok ? '✓ exit 0' : `✗ exit ${step.returncode}`, ok ? 'ok' : 'error');
        });
        const allOk = result.success !== false;
        dot.className = `terminal-status-dot ${allOk ? 'dot-ok' : 'dot-error'}`;
        statusTx.textContent = allOk ? '完成' : '失败';
        allOk ? this.showSuccess('✓ 智能体运行完成') : this.showError('执行失败，请查看终端输出');
    }

    appendTerminalLine(text, type = 'default') {
        const body = document.getElementById('terminal-body');
        if (!body) return;
        const line = document.createElement('div');
        line.className = `terminal-line terminal-line--${type}`;
        line.textContent = text;
        body.appendChild(line);
        body.scrollTop = body.scrollHeight;
    }

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
        header.innerHTML = `<h3>${title}</h3>
            <button class="btn-close" onclick="this.closest('.modal').remove()">✕</button>`;
        const body = document.createElement('div');
        body.className = 'modal-body';
        body.appendChild(content);
        dialog.appendChild(header);
        dialog.appendChild(body);
        modal.appendChild(overlay);
        modal.appendChild(dialog);
        return modal;
    }

    showNotification(msg, type) {
        const n = document.createElement('div');
        n.className = `notification notification-${type}`;
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => { n.classList.add('fade-out'); setTimeout(() => n.remove(), 300); }, 3500);
    }
    showError(msg)   { this.showNotification(msg, 'error'); }
    showSuccess(msg) { this.showNotification(msg, 'success'); }

    setupEventListeners() {
        document.getElementById('btn-add-agent')
            ?.addEventListener('click', () => this.showAddAgentDialog());
        document.getElementById('btn-edit-rules')
            ?.addEventListener('click', () => this.showEditRulesDialog());
        document.getElementById('btn-save-cfg')
            ?.addEventListener('click', () => this.saveConfigToDisk(false));
        document.getElementById('btn-run-agent')
            ?.addEventListener('click', () => this.runAgent());
    }
}

let agentManager;
document.addEventListener('DOMContentLoaded', () => { agentManager = new AgentManager(); });