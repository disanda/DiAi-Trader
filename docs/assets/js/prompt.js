/**
 * prompt.js — 提示词管理页面逻辑
 * 负责：加载/保存自定义提示词 JSON、切换 Tab、系统提示词展示
 */

const API = '';

// ── 系统提示词（只读，不可修改）────────────────────────────────────────────
// 每个 Tab 对应不同的系统提示词来源，切换 Tab 时同步更新展示内容。
const SYSTEM_PROMPTS = {
    strategy: `【来源：agent/agent_prompt/agent_prompt_astock.py — agent_system_prompt_astock】

你是一位A股散户，你的长期目标是：
 > 通过优化资产投资组合，最大化资产收益。

─── 思考标准 ───────────────────────────────────────────────────
• 通过调用可用工具，思考可交易品种当前价格和未来收益情况（股票、ETF、期货）
• 读取当前持仓和当前价格，并自主完成交易
• 更新估值并调整每个交易标的持仓权重（如策略需要）

─── A股交易规则 ─────────────────────────────────────────────────
1. 股票代码格式：symbol 参数必须包含 .SH 或 .SZ 后缀
2. 分清1手与1股：A股 1手 = 100股，买卖以手为单位
   • 科创板（688开头）最小买卖单位 200股（2手）
3. T+1 结算规则：当天买入的股票不能当天卖出
   • 跨境ETF、债券ETF、黄金ETF、货币ETF 及股指期货支持 T+0

─── 重要行为要求 ─────────────────────────────────────────────────
• 必须实际调用 buy() 或 sell() 工具，不要只给出建议
• 禁止编造错误信息，工具失败时如实报告真实错误
• 每天买入次数限制在 5 次以内，注重交易质量而非数量

─── 动态注入内容（运行时填充）───────────────────────────────────
• 当前时间 {date}
• 当前持仓 {positions}
• 持仓价值（上一时间点收盘价）{yesterday_close_price}
• 当前买入价格 {today_buy_price}
• 上一时间段收益 {current_profit}

─── 用户自定义交易策略 ───────────────────────────────────────────
↓ 在下方「自定义提示词」区域编辑，启用后自动追加到此处 ↓`,

    journal: `【来源：agent/base_agent_astock.py — _write_daily_journal】

今日交易已结束。请跟你的交易思路，撰写一份《交易复盘日志》。要求：
1. 今日交易操作记录，及整体交易策略。
2. 概述目前持仓（含各股仓位、价值和当前现金量），概述短-中-长线策略。
3. 当前持仓资产的止盈止损点，对持有资产可能存在的风险进行预警。
4. 如果过去交易策略存在不足，需指出并给出改进方法。
5. 下一阶段调仓意向。
6. 你觉得有必要记录的其他信息。

若 今日《交易复盘日志》的部分内容与昨日内容接近，则简略撰写，总体字数控制在500字左右。
若 今日《交易复盘日志》相对昨日内容改变较大，则需在日志标题后注明「有重要更新」，且字数不限制。
这份日志将作为你长期交易的核心记录，日志撰写格式采用 Markdown。

─── 用户自定义日志格式 ───────────────────────────────────────────
↓ 在下方「自定义提示词」区域编辑，启用后自动追加到此处 ↓`,
};

// ── State ──────────────────────────────────────────────────────────────────
let currentTab = 'strategy';   // 'strategy' | 'journal'
let prompts = [];               // 当前 tab 的提示词列表
let selectedIdx = null;         // 当前选中条目的索引（null = 无选中）
let isDirty = false;            // 编辑器是否有未保存改动

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    renderSysPrompt();
    loadPrompts();
});

// ── System prompt (read-only display) ─────────────────────────────────────
function renderSysPrompt() {
    document.getElementById('sysPromptText').textContent = SYSTEM_PROMPTS[currentTab];
}

function toggleSysPanel() {
    const body = document.getElementById('sysPanelBody');
    const icon = document.getElementById('sysToggleIcon');
    const isOpen = body.classList.toggle('open');
    icon.textContent = isOpen ? '▼ 收起' : '▶ 展开查看';
}

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(tab) {
    if (isDirty && !confirmDiscard()) return;

    currentTab = tab;
    selectedIdx = null;
    isDirty = false;

    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tab);
    });

    renderSysPrompt();
    loadPrompts();
}

// ── Load prompts from server ───────────────────────────────────────────────
async function loadPrompts() {
    renderList([]);                     // show loading state
    document.getElementById('promptList').innerHTML =
        '<li class="loading-indicator"><span class="dot-pulse"></span> 加载中…</li>';

    try {
        const res = await fetch(`${API}/load-prompts?type=${currentTab}`);
        const json = await res.json();
        if (!json.success) throw new Error(json.error || '加载失败');
        prompts = Array.isArray(json.prompts) ? json.prompts : [];
    } catch (e) {
        prompts = [];
        showToast('无法连接服务器，请确认 bs_server.py 已启动', 'error');
    }

    renderList(prompts);
    showEditor(null);
}

// ── Render sidebar list ────────────────────────────────────────────────────
function renderList(list) {
    const ul = document.getElementById('promptList');
    if (!list.length) {
        ul.innerHTML = '<li style="padding:20px 16px; color:var(--text-dim); font-size:12px; text-align:center">暂无提示词，点击「新建」添加</li>';
        return;
    }

    ul.innerHTML = list.map((p, i) => `
        <li class="prompt-item ${selectedIdx === i ? 'selected' : ''}" onclick="selectPrompt(${i})">
            <div class="prompt-item-info">
                <div class="prompt-item-title">${escHtml(p.title || '未命名')}</div>
                <div class="prompt-item-preview">${escHtml((p.content || '').slice(0, 60)) || '（无内容）'}</div>
            </div>
            ${p.active
                ? '<span class="badge-active">已启用</span>'
                : '<span class="badge-off">未启用</span>'}
        </li>
    `).join('');
}

// ── Select a prompt for editing ────────────────────────────────────────────
function selectPrompt(idx) {
    if (isDirty && !confirmDiscard()) return;
    selectedIdx = idx;
    isDirty = false;
    renderList(prompts);
    showEditor(prompts[idx]);
}

function showEditor(prompt) {
    const empty  = document.getElementById('emptyState');
    const wrap   = document.getElementById('editorWrap');

    if (!prompt) {
        empty.style.display = 'flex';
        wrap.style.display  = 'none';
        return;
    }

    empty.style.display = 'none';
    wrap.style.display  = 'flex';

    document.getElementById('editTitle').value   = prompt.title   || '';
    document.getElementById('editContent').value = prompt.content || '';

    updateToggleBtn(prompt.active);

    document.getElementById('metaStatus').textContent =
        prompt.active ? '✅ 已启用 — 将追加到系统提示词末尾' : '⚪ 未启用';

    // mark dirty on input
    ['editTitle', 'editContent'].forEach(id => {
        const el = document.getElementById(id);
        el.oninput = () => { isDirty = true; };
    });
}

function updateToggleBtn(active) {
    const btn = document.getElementById('btnToggle');
    if (active) {
        btn.textContent = '✅ 已启用';
        btn.className   = 'btn btn-toggle-active';
    } else {
        btn.textContent = '启用';
        btn.className   = 'btn btn-toggle-off';
    }
}

// ── New prompt ─────────────────────────────────────────────────────────────
function newPrompt() {
    if (isDirty && !confirmDiscard()) return;

    const newItem = {
        id:      Date.now(),
        title:   '',
        content: '',
        active:  false,
    };
    prompts.push(newItem);
    selectedIdx = prompts.length - 1;
    isDirty = false;

    renderList(prompts);
    showEditor(newItem);

    // Focus title input
    setTimeout(() => document.getElementById('editTitle').focus(), 50);
}

// ── Toggle active state ────────────────────────────────────────────────────
function toggleActive() {
    if (selectedIdx === null) return;
    prompts[selectedIdx].active = !prompts[selectedIdx].active;
    updateToggleBtn(prompts[selectedIdx].active);
    document.getElementById('metaStatus').textContent =
        prompts[selectedIdx].active
            ? '✅ 已启用 — 将追加到系统提示词末尾'
            : '⚪ 未启用';
    isDirty = true;
    renderList(prompts);
}

// ── Save prompt ────────────────────────────────────────────────────────────
async function savePrompt() {
    if (selectedIdx === null) return;

    const title   = document.getElementById('editTitle').value.trim();
    const content = document.getElementById('editContent').value;

    if (!title) { showToast('请填写提示词标题', 'error'); return; }

    prompts[selectedIdx].title   = title;
    prompts[selectedIdx].content = content;

    await persistPrompts();
    isDirty = false;
    renderList(prompts);

    document.getElementById('metaStatus').textContent =
        prompts[selectedIdx].active ? '✅ 已启用 — 将追加到系统提示词末尾' : '⚪ 未启用';
}

// ── Delete prompt ──────────────────────────────────────────────────────────
async function deletePrompt() {
    if (selectedIdx === null) return;
    const name = prompts[selectedIdx].title || '该提示词';
    if (!confirm(`确定要删除「${name}」吗？`)) return;

    prompts.splice(selectedIdx, 1);
    selectedIdx = null;
    isDirty = false;

    await persistPrompts();
    renderList(prompts);
    showEditor(null);
}

// ── Persist to server ──────────────────────────────────────────────────────
async function persistPrompts() {
    try {
        const res = await fetch(`${API}/save-prompt`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ type: currentTab, prompts }),
        });
        const json = await res.json();
        if (!json.success) throw new Error(json.error || '保存失败');
        showToast('保存成功 ✓', 'success');
    } catch (e) {
        showToast(`保存失败：${e.message}`, 'error');
    }
}

// ── Helpers ────────────────────────────────────────────────────────────────
function confirmDiscard() {
    return confirm('有未保存的改动，确定要放弃吗？');
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

let toastTimer = null;
function showToast(msg, type = 'success') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className   = `show ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = type; }, 2800);
}
