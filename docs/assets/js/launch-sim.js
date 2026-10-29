class LaunchSimulationPage {
  constructor() {
    this.settings = { trading: null, prediction: null };
    this.active = 'trading';
    this.running = false;
    this.mount();
    this.load();
  }

  mount() {
    document.title = '启动模拟 | DiAi 自交易系统';
    document.querySelectorAll('.nav-link[href="run_agent.html"]').forEach(link => {
      link.textContent = '启动模拟';
    });
    const main = document.querySelector('main');
    main.className = 'launch-shell';
    main.innerHTML = `
      <header class="launch-head"><div><h2>启动模拟</h2><p>分别配置模拟交易与预测任务的规则、模型及 API 环境变量。</p></div></header>
      <nav class="launch-tabs" aria-label="设置模块">
        <button class="launch-tab active" data-tab="trading">交易设置</button>
        <button class="launch-tab" data-tab="prediction">预测设置</button>
      </nav>
      <section class="launch-panel active" data-panel="trading">
        <div class="launch-grid">
          <section class="launch-card"><div class="launch-card-head"><h3>交易规则</h3><span>configs/astock_config_day.json</span></div><div class="launch-card-body">
            <div class="launch-form-grid">
              <div class="launch-field"><label>开始日期</label><input name="date_range.init_date" type="date"></div>
              <div class="launch-field"><label>结束日期</label><input name="date_range.end_date" type="date"></div>
              <div class="launch-field"><label>最大 Agent 步数</label><input name="agent_config.max_steps" type="number" min="1"></div>
              <div class="launch-field"><label>最大重试次数</label><input name="agent_config.max_retries" type="number" min="0"></div>
              <div class="launch-field"><label>重试间隔（秒）</label><input name="agent_config.base_delay" type="number" min="0" step="0.1"></div>
              <div class="launch-field"><label>初始资金</label><input name="agent_config.initial_cash" type="number" min="0" step="1000"></div>
              <div class="launch-field"><label>标的组名称</label><input name="log_config.Ashare_symbols" type="text"></div>
              <div class="launch-field"><label>行情周期</label><select name="log_config.BAR_MODE"><option value="daily">日线</option><option value="hourly">小时线</option></select></div>
              <div class="launch-field full"><label>交易日志目录</label><input name="log_config.model_data_path" type="text"></div>
              <div class="launch-field full"><label>行情数据目录</label><input name="log_config.Ashare_data_path" type="text"></div>
            </div>
            <div class="launch-prompt-box"><h4>运行提示词</h4><p>系统提示词固定启用；在这里选择本次模拟使用的自定义提示词。</p><div class="launch-prompt-grid"><div><label>交易策略提示词</label><div id="strategyPromptOptions" class="launch-prompt-options"></div></div><div><label>日志格式提示词</label><div id="journalPromptOptions" class="launch-prompt-options"></div></div></div></div>
            <div class="launch-actions"><button class="launch-btn" data-save="trading">保存交易设置</button><button class="launch-btn primary" id="runSimulation">启动模拟</button></div>
          </div></section>
          <section class="launch-card"><div class="launch-card-head"><h3>交易模型（LLM）</h3><button class="launch-btn" data-add-model="trading">＋ 添加模型</button></div><div class="launch-card-body"><div class="launch-model-list" id="tradingModels"></div><p class="launch-hint">这里只保存私钥环境变量名，不保存私钥内容。请在项目根目录 .env 中自行填写对应密钥。</p></div></section>
        </div>
      </section>
      <section class="launch-panel" data-panel="prediction">
        <div class="launch-grid">
          <section class="launch-card"><div class="launch-card-head"><h3>预测规则</h3><span>predict_v2/config.json</span></div><div class="launch-card-body">
            <div class="launch-form-grid">
              <div class="launch-field"><label>指定预测日期（可留空使用日期范围）</label><input name="prediction_date" type="date"></div>
              <div class="launch-field"><label>回看交易日数</label><input name="lookback_days" type="number" min="1"></div>
              <div class="launch-field"><label>预测范围开始</label><input name="prediction_start_date" type="date"></div>
              <div class="launch-field"><label>预测范围结束</label><input name="prediction_end_date" type="date"></div>
              <div class="launch-field"><label>请求超时（秒）</label><input name="request_timeout_seconds" type="number" min="1"></div>
              <div class="launch-field"><label>新闻检索</label><select name="use_news_search"><option value="true">启用</option><option value="false">关闭</option></select></div>
              <div class="launch-field"><label>新闻最大条数</label><input name="news_max_results" type="number" min="0"></div>
              <div class="launch-field"><label>新闻时间范围</label><input name="news_time_range" type="text"></div>
              <div class="launch-field"><label>新闻内容截取字符数</label><input name="news_raw_chars" type="number" min="0"></div>
              <div class="launch-field"><label>新闻检索模板</label><input name="news_query" type="text"></div>
            </div>
            <div class="launch-prompt-box"><h4>预测提示词</h4><p>预测系统提示词固定启用；请选择一个预测风格。</p><div id="predictionPromptOptions" class="launch-prompt-options single"></div></div>
            <div class="launch-actions"><button class="launch-btn" data-save="prediction">保存预测设置</button><button class="launch-btn primary" id="runPrediction">开始预测</button></div>
          </div></section>
          <section class="launch-card"><div class="launch-card-head"><h3>预测模型（LLM）</h3><button class="launch-btn" data-add-model="prediction">＋ 添加模型</button></div><div class="launch-card-body"><div class="launch-model-list" id="predictionModels"></div><p class="launch-hint">预测模型的普通配置保存在 predict_v2/config.json；请在项目根目录 .env 中填写模型对应的私钥环境变量。</p></div></section>
        </div>
      </section>
      <section class="launch-terminal" id="simTerminal"><div class="launch-terminal-head"><strong>运行输出</strong><button class="launch-btn" id="closeTerminal">关闭</button></div><div class="launch-terminal-body" id="simOutput"></div></section>
      <div class="launch-notice" id="launchNotice" role="status"></div><div class="launch-modal-backdrop" id="modelModal" aria-hidden="true"><form class="launch-modal" id="modelForm"><div class="launch-modal-head"><h3>添加模型</h3><button type="button" data-close-model>×</button></div><div class="launch-form-grid"><div class="launch-field"><label>模型名称</label><input name="name" required></div><div class="launch-field"><label>Base model</label><input name="basemodel" required></div><div class="launch-field"><label>Signature</label><input name="signature"></div><div class="launch-field"><label>API Base URL</label><input name="openai_base_url"></div><div class="launch-field full"><label>私钥环境变量名</label><input name="api_key_env" pattern="[A-Za-z_][A-Za-z0-9_]*" placeholder="留空则自动生成，例如 DIAI_SIM_GLM_4_5_API_KEY"><small>仅填写环境变量名，不要填写私钥内容；保存后请打开项目根目录 .env 自行填写密钥。</small></div></div><div class="launch-actions"><button type="button" data-close-model>取消</button><button class="launch-btn primary">保存模型</button></div></form></div>`;
    document.querySelectorAll('.launch-tab').forEach(button => button.addEventListener('click', () => this.switchTab(button.dataset.tab)));
    document.querySelectorAll('[data-save]').forEach(button => button.addEventListener('click', () => this.save(button.dataset.save)));
    document.querySelectorAll('[data-add-model]').forEach(button => button.addEventListener('click', () => this.addModel(button.dataset.addModel)));
    document.getElementById('runSimulation').textContent = '开始交易';
    document.getElementById('runSimulation').addEventListener('click', () => this.run());
    document.getElementById('runPrediction').addEventListener('click', () => this.runPrediction());
    document.getElementById('closeTerminal').addEventListener('click', () => document.getElementById('simTerminal').classList.remove('open'));
    document.body.addEventListener('click', event => {
      const remove = event.target.closest('[data-remove-model]');
      if (remove) this.removeModel(remove.dataset.removeModel, Number(remove.dataset.index));
      if (event.target.closest('[data-close-model]')) this.closeModelModal();
      const head = event.target.closest('.launch-model-head'); if (head && !event.target.closest('button,input,label')) head.parentElement.classList.toggle('expanded');
    });
    document.getElementById('modelForm').addEventListener('submit', event => { event.preventDefault(); this.saveModelModal(); });
    this.mountPredictionSymbolControls();
  }

  async load() {
    try {
      const response = await fetch('/launch-settings', { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
      this.settings = result.data;
      this.fillFields('trading'); this.fillFields('prediction');
      this.renderPromptSettings();
      this.renderModels('trading'); this.renderModels('prediction');
      this.loadPredictionGroups(); this.renderPredictionSymbolSummary();
    } catch (error) { this.notice(`无法读取设置：${error.message}`, true); }
  }

  renderPromptSettings() {
    const options = this.settings.prompt_options || {};
    const selection = this.settings.trading.prompt_selection || {};
    const selected = (key, id) => (selection[key] || []).map(String).includes(String(id));
    const renderChecks = (hostId, key) => {
      const host = document.getElementById(hostId); if (!host) return;
      host.innerHTML = (options[key] || []).map(item => `<label><input type="checkbox" data-prompt-kind="${key}" value="${this.escape(item.id)}" ${selected(key, item.id) ? 'checked' : ''}><span>${this.escape(item.title)}</span></label>`).join('') || '<em>暂无可选提示词</em>';
    };
    renderChecks('strategyPromptOptions', 'strategy'); renderChecks('journalPromptOptions', 'journal');
    const host = document.getElementById('predictionPromptOptions'), current = this.settings.prediction.prompt_profile;
    if (host) host.innerHTML = (options.prediction_style || []).map(item => `<label><input type="radio" name="prompt_profile" value="${this.escape(item.id)}" ${String(current) === String(item.id) ? 'checked' : ''}><span>${this.escape(item.title)}</span></label>`).join('') || '<em>暂无预测风格</em>';
  }

  escape(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  switchTab(section) {
    this.active = section;
    document.querySelectorAll('.launch-tab').forEach(item => item.classList.toggle('active', item.dataset.tab === section));
    document.querySelectorAll('.launch-panel').forEach(item => item.classList.toggle('active', item.dataset.panel === section));
  }

  mountPredictionSymbolControls() {
    const panel = document.querySelector('[data-panel="prediction"]');
    const grid = panel?.querySelector('.launch-form-grid');
    if (!grid) return;
    const field = document.createElement('div');
    field.className = 'launch-field';
    field.innerHTML = '<label>预测标的</label><button type="button" class="launch-btn launch-symbol-button" id="predictionSymbolsButton"><i class="ti ti-adjustments-horizontal"></i><span id="predictionSymbolsSummary">配置预测标的</span></button>';
    grid.appendChild(field);
    const modal = document.createElement('div');
    modal.className = 'launch-modal-backdrop'; modal.id = 'predictionSymbolsModal'; modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = '<div class="launch-modal launch-symbol-modal"><div class="launch-modal-head"><h3>预测标的</h3><button type="button" data-close-symbols>×</button></div><div class="launch-form-grid"><div class="launch-field"><label>标的类型</label><select id="predictionAssetType"><option value="stock">股票</option><option value="index">指数</option><option value="etf">ETF</option></select></div><div class="launch-field"><label>从已有标的组载入</label><select id="predictionGroupSelect"><option value="">手工输入</option></select></div><div class="launch-field full"><label>预测代码</label><textarea id="predictionSymbolsInput" rows="7" placeholder="每行一个代码，或用逗号分隔"></textarea><small>选择标的组后可继续手工增删代码；保存后写入 predict_v2/config.json。</small></div></div><div class="launch-actions"><button type="button" data-close-symbols>取消</button><button type="button" class="launch-btn primary" id="savePredictionSymbols">保存预测标的</button></div></div>';
    document.body.appendChild(modal);
    document.getElementById('predictionSymbolsButton').addEventListener('click', () => this.openPredictionSymbols());
    document.getElementById('savePredictionSymbols').addEventListener('click', () => this.savePredictionSymbols());
    modal.addEventListener('click', event => { if (event.target === modal || event.target.closest('[data-close-symbols]')) this.closePredictionSymbols(); });
  }

  async loadPredictionGroups() {
    try {
      const response = await fetch('/symbol-groups', { cache: 'no-store' });
      const payload = await response.json();
      const select = document.getElementById('predictionGroupSelect');
      if (!response.ok || !payload.success || !select) return;
      select.innerHTML = '<option value="">手工输入</option>' + (payload.groups || []).map(group => `<option value="${this.escape(group.id)}">${this.escape(group.market_label)} · ${this.escape(group.name)}（${group.symbols.length}）</option>`).join('');
      select.addEventListener('change', () => {
        const group = (payload.groups || []).find(item => item.id === select.value);
        if (!group) return;
        document.getElementById('predictionAssetType').value = group.market === 'etfs' ? 'etf' : 'stock';
        document.getElementById('predictionSymbolsInput').value = group.symbols.join('\n');
      });
    } catch (_) {}
  }

  openPredictionSymbols() {
    const data = this.settings.prediction || {};
    document.getElementById('predictionAssetType').value = data.asset_type || 'index';
    document.getElementById('predictionSymbolsInput').value = (data.symbols || []).join('\n');
    const modal = document.getElementById('predictionSymbolsModal'); modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false');
  }

  closePredictionSymbols() {
    const modal = document.getElementById('predictionSymbolsModal'); modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true');
  }

  savePredictionSymbols() {
    const raw = document.getElementById('predictionSymbolsInput').value;
    const symbols = [...new Set(raw.split(/[\s,，;；]+/).map(value => value.trim().toUpperCase()).filter(Boolean))];
    if (!symbols.length) return this.notice('请至少填写一个预测标的代码', true);
    this.settings.prediction.asset_type = document.getElementById('predictionAssetType').value;
    this.settings.prediction.symbols = symbols;
    this.renderPredictionSymbolSummary(); this.closePredictionSymbols();
  }

  renderPredictionSymbolSummary() {
    const data = this.settings.prediction || {}, symbols = data.symbols || [];
    const node = document.getElementById('predictionSymbolsSummary');
    if (node) node.textContent = `${data.asset_type || 'index'} · ${symbols.length} 个标的`;
  }

  fillFields(section) {
    const panel = document.querySelector(`[data-panel="${section}"]`), data = this.settings[section] || {};
    panel.querySelectorAll('[name]').forEach(input => {
      const path = input.name.split('.'); let value = data;
      for (const key of path) value = value?.[key];
      if (input.type === 'checkbox') input.checked = Boolean(value);
      else if (input.type === 'radio') input.checked = String(input.value) === String(value);
      else if (input.tagName === 'SELECT' && typeof value === 'boolean') input.value = String(value);
      else if (input.type === 'date' && /^\d{8}$/.test(String(value || ''))) input.value = `${String(value).slice(0,4)}-${String(value).slice(4,6)}-${String(value).slice(6,8)}`;
      else input.value = value ?? '';
    });
  }

  envName(section, model, index) {
    if (model.api_key_env) return model.api_key_env;
    const slug = String(model.signature || model.name || `model_${index}`).toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 48) || `MODEL_${index}`;
    return `${section === 'trading' ? 'DIAI_SIM' : 'DIAI_PREDICT'}_${slug}_${index}_API_KEY`;
  }

  renderModels(section) {
    const host = document.getElementById(`${section}Models`), models = this.settings[section]?.models || [];
    host.innerHTML = models.map((model, index) => {
      model.api_key_env = this.envName(section, model, index);
      const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
      return `<article class="launch-model" data-model-section="${section}" data-index="${index}">
        <div class="launch-model-head"><strong>${esc(model.name || `模型 ${index + 1}`)}</strong><div class="launch-model-controls"><label><input type="checkbox" data-model-field="enabled" ${model.enabled === false ? '' : 'checked'}> 启用</label><button class="launch-delete" data-remove-model="${section}" data-index="${index}">移除</button></div></div>
        <div class="launch-form-grid">
          <div class="launch-field"><label>模型名称</label><input data-model-field="name" value="${esc(model.name)}"></div>
          <div class="launch-field"><label>Base model</label><input data-model-field="basemodel" value="${esc(model.basemodel)}"></div>
          <div class="launch-field"><label>Signature</label><input data-model-field="signature" value="${esc(model.signature)}"></div>
          <div class="launch-field"><label>API Base URL</label><input data-model-field="openai_base_url" value="${esc(model.openai_base_url)}"></div>
          <div class="launch-field full"><label>私钥环境变量名</label><input data-model-field="api_key_env" value="${esc(model.api_key_env)}" pattern="[A-Za-z_][A-Za-z0-9_]*"><small>请在项目根目录 .env 中填写 ${esc(model.api_key_env)}=你的密钥${model.has_api_key ? '（当前已检测到）' : ''}</small></div>
          ${section === 'prediction' ? `<div class="launch-field"><label>Temperature</label><input type="number" step="0.1" data-model-field="temperature" value="${esc(model.temperature ?? '')}"></div><div class="launch-field"><label>JSON mode</label><select data-model-field="json_mode"><option value="false" ${model.json_mode ? '' : 'selected'}>关闭</option><option value="true" ${model.json_mode ? 'selected' : ''}>开启</option></select></div>` : ''}
        </div></article>`;
    }).join('') || '<p class="launch-hint">还没有模型配置，请添加一个模型。</p>';
  }

  addModel(section) {
    this.modalSection = section; const modal = document.getElementById('modelModal');
    modal.querySelector('form').reset(); modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false'); return;
  }
  closeModelModal() { const modal = document.getElementById('modelModal'); modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true'); }
  saveModelModal() {
    const form = document.getElementById('modelForm'), section = this.modalSection; if (!section || !form.reportValidity()) return;
    const value = key => form.elements[key]?.value?.trim() || ''; const models = this.settings[section].models ||= []; const index = models.length;
    const model = {name:value('name'), basemodel:value('basemodel'), signature:value('signature') || `model_${index + 1}`, enabled:true, openai_base_url:value('openai_base_url'), api_key_env:value('api_key_env')};
    model.api_key_env = this.envName(section, model, index); models.push(model); this.renderModels(section); this.closeModelModal();
  }

  removeModel(section, index) {
    this.settings[section].models.splice(index, 1); this.renderModels(section);
  }

  collect(section) {
    const panel = document.querySelector(`[data-panel="${section}"]`), data = this.settings[section];
    panel.querySelectorAll('[name]').forEach(input => {
      if (input.type === 'radio' && !input.checked) return;
      const keys = input.name.split('.'); let target = data;
      for (const key of keys.slice(0, -1)) target = target[key] ||= {};
      let value = input.value;
      if (input.type === 'number') value = value === '' ? null : Number(value);
      if (input.tagName === 'SELECT' && (value === 'true' || value === 'false')) value = value === 'true';
      target[keys.at(-1)] = value;
    });
    if (section === 'trading') {
      data.prompt_selection = { strategy: [], journal: [] };
      panel.querySelectorAll('[data-prompt-kind]:checked').forEach(input => data.prompt_selection[input.dataset.promptKind].push(input.value));
    }
    panel.querySelectorAll('.launch-model').forEach(card => {
      const index = Number(card.dataset.index), model = data.models[index];
      card.querySelectorAll('[data-model-field]').forEach(input => {
        let value = input.type === 'checkbox' ? input.checked : input.value.trim();
        if (input.dataset.modelField === 'temperature' && value !== '') value = Number(value);
        if (input.dataset.modelField === 'json_mode') value = value === 'true';
        model[input.dataset.modelField] = value;
      });
      model.api_key_env = this.envName(section, model, index);
    });
    return { data };
  }

  async save(section, quiet = false) {
    const { data } = this.collect(section);
    try {
      const response = await fetch('/launch-settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ section, data }) });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
      this.renderModels(section);
      if (!quiet) this.notice(`${section === 'trading' ? '交易设置' : '预测设置'}已保存。请打开项目根目录 .env，填写模型对应的私钥环境变量。`);
      return true;
    } catch (error) { this.notice(`保存失败：${error.message}`, true); return false; }
  }

  async run() {
    if (this.running) return;
    if (!(await this.save('trading', true))) return;
    const enabled = (this.settings.trading.models || []).filter(model => model.enabled !== false);
    if (!enabled.length) return this.notice('请至少启用一个交易模型。', true);
    if (!window.confirm(`即将按交易设置启动模拟，共 ${enabled.length} 个启用模型。是否继续？`)) return;
    this.running = true;
    const terminal = document.getElementById('simTerminal'), output = document.getElementById('simOutput');
    terminal.classList.add('open'); output.textContent = '正在启动…\n'; terminal.scrollIntoView({behavior:'smooth', block:'nearest'});
    try {
      const response = await fetch('/run-agent', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({config_path:'configs/astock_config_day.json'}) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const {value, done} = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
        const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
        for (const block of blocks) for (const line of block.split('\n')) if (line.startsWith('data:')) {
          const raw = line.slice(5).trim(); if (!raw || raw === '[DONE]') continue;
          const event = JSON.parse(raw), text = event.message || event.line || '';
          if (text) { output.textContent += `${text}\n`; output.scrollTop = output.scrollHeight; }
        }
        if (done) break;
      }
      this.notice('模拟任务已结束。');
    } catch (error) { output.textContent += `\n运行失败：${error.message}\n`; this.notice(`运行失败：${error.message}`, true); }
    finally { this.running = false; }
  }

  async runPrediction() {
    if (this.running) return;
    if (!(await this.save('prediction', true))) return;
    const settings = this.settings.prediction || {};
    const symbols = settings.symbols || [];
    if (!symbols.length) return this.notice('请先配置至少一个预测标的', true);
    const predictionModels = settings.models?.length ? settings.models : [settings.model || {}];
    if (!predictionModels.some(model => model.enabled !== false)) {
      return this.notice('请启用预测模型后再开始预测', true);
    }
    const dateDescription = settings.prediction_date || `${settings.prediction_start_date} 至 ${settings.prediction_end_date}`;
    if (!window.confirm(`即将对 ${symbols.length} 个标的运行预测（${dateDescription}）。是否继续？`)) return;
    this.running = true;
    await this.streamTask('/run-prediction', {}, '预测任务');
    this.running = false;
  }

  async streamTask(url, payload, title) {
    const terminal = document.getElementById('simTerminal'), output = document.getElementById('simOutput');
    terminal.classList.add('open'); output.textContent = '正在启动...\n'; terminal.scrollIntoView({behavior:'smooth', block:'nearest'});
    try {
      const response = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || `HTTP ${response.status}`);
      }
      if (!response.body) throw new Error('当前浏览器不支持流式任务日志');
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '', failed = false;
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
        const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
        for (const block of blocks) for (const line of block.split('\n')) if (line.startsWith('data:')) {
          const raw = line.slice(5).trim(); if (!raw || raw === '[DONE]') continue;
          const event = JSON.parse(raw), text = event.message || event.line || '';
          if (event.type === 'error') failed = true;
          if (text) { output.textContent += `${text}\n`; output.scrollTop = output.scrollHeight; }
        }
        if (done) break;
      }
      this.notice(failed ? `${title}部分失败，请查看运行日志` : `${title}已完成`, failed);
    } catch (error) {
      output.textContent += `\n运行失败：${error.message}\n`;
      this.notice(`运行失败：${error.message}`, true);
    }
  }

  notice(message, error = false) {
    const node = document.getElementById('launchNotice'); if (!node) return;
    node.textContent = message; node.className = `launch-notice show${error ? ' error' : ''}`;
    clearTimeout(this.noticeTimer); this.noticeTimer = setTimeout(() => node.classList.remove('show'), 3500);
  }
}

document.addEventListener('DOMContentLoaded', () => { window.launchSimulationPage = new LaunchSimulationPage(); });
