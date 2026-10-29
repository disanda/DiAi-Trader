const managerState = { groups: [], markets: [], names: {}, market: 'astocks', selectedId: null, running: false, symbolPage: 1, symbolQuery: '' };

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const formatTime = value => value ? String(value).replace('T', ' ') : '--';
const parseSymbols = value => [...new Set(String(value || '').split(/[\s,，;；]+/).map(item => item.trim().toUpperCase()).filter(Boolean))];

function showToast(message, kind = 'ok') {
  const toast = $('toast');
  toast.textContent = message;
  toast.className = `toast show ${kind}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.className = 'toast', 2800);
}

async function loadGroups(preferredId) {
  try {
    const response = await fetch(`/symbol-groups?ts=${Date.now()}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.success) throw new Error(payload.error || '读取失败');
    managerState.groups = payload.groups || [];
    managerState.markets = payload.markets || [];
    managerState.names = payload.names || {};
    const available = managerState.groups.filter(group => group.market === managerState.market);
    managerState.selectedId = preferredId && managerState.groups.some(group => group.id === preferredId)
      ? preferredId
      : (available.some(group => group.id === managerState.selectedId) ? managerState.selectedId : available[0]?.id || null);
    render();
  } catch (error) {
    $('subjectMeta').textContent = `加载失败：${error.message}`;
    $('groupList').innerHTML = '<div class="empty-compact">无法连接标的管理服务</div>';
  }
}

function render() {
  const totalSymbols = new Set(managerState.groups.flatMap(group => group.symbols)).size;
  $('subjectMeta').textContent = `${managerState.groups.length} 个标的组 · ${totalSymbols} 个不重复代码 · 数据统一存放于三类市场目录`;
  $('marketSwitch').innerHTML = managerState.markets.map(market => `<button type="button" class="${market.id === managerState.market ? 'active' : ''}" data-market="${market.id}">${escapeHtml(market.name)}</button>`).join('');
  const groups = managerState.groups.filter(group => group.market === managerState.market);
  $('groupCount').textContent = groups.length;
  $('groupList').innerHTML = groups.length ? groups.map(group => `
    <button type="button" class="subject-group ${group.id === managerState.selectedId ? 'active' : ''}" data-group="${escapeHtml(group.id)}">
      <span><b>${escapeHtml(group.name)}</b><small>${escapeHtml(group.key)}</small></span><em>${group.symbols.length}</em>
    </button>`).join('') : '<div class="empty-compact">该市场还没有标的</div>';
  renderDetail();
  renderDownloadGroups();
}

function renderDetail() {
  const group = managerState.groups.find(item => item.id === managerState.selectedId);
  if (!group) {
    $('subjectDetail').innerHTML = '<div class="empty-state"><i class="ti ti-list-search"></i><span>选择左侧标的查看总览</span></div>';
    return;
  }
  $('subjectDetail').innerHTML = `
    <div class="detail-head"><div><span class="market-label">${escapeHtml(group.market_label)}</span><h3>${escapeHtml(group.name)}</h3><p>${escapeHtml(group.data_base)}/symbols/${escapeHtml(group.key)}.json</p></div><button class="btn-edit" type="button" id="btnEditGroup"><i class="ti ti-edit"></i>编辑</button></div>
    <div class="overview-grid"><div><span>市场类型</span><strong>${escapeHtml(group.market_label)}</strong></div><div><span>股票 / 指数总数</span><strong>${group.symbols.length}</strong></div><div><span>创建时间</span><strong>${formatTime(group.created_at)}</strong></div><div><span>最近编辑</span><strong>${formatTime(group.updated_at)}</strong></div></div>
    <div class="symbol-section"><div class="symbol-section-head"><h4>代码清单</h4><label><i class="ti ti-search"></i><input id="symbolSearch" type="search" placeholder="筛选代码" value="${escapeHtml(managerState.symbolQuery)}"></label></div><div class="symbol-list" id="symbolList"></div><div class="symbol-pager" id="symbolPager"></div></div>`;
  renderSymbols(group.symbols, managerState.symbolQuery);
  $('btnEditGroup').addEventListener('click', () => openGroupModal(group));
  $('symbolSearch').addEventListener('input', event => { managerState.symbolQuery = event.target.value; managerState.symbolPage = 1; renderSymbols(group.symbols, managerState.symbolQuery); });
}

function renderSymbols(symbols, query) {
  const keyword = String(query || '').trim().toUpperCase();
  const filtered = symbols.filter(symbol => !keyword || symbol.includes(keyword));
  const pageSize = 200, pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  managerState.symbolPage = Math.min(managerState.symbolPage, pages);
  const offset = (managerState.symbolPage - 1) * pageSize;
  const visible = filtered.slice(offset, offset + pageSize);
  $('symbolList').innerHTML = visible.length ? visible.map((symbol, index) => `<div><span>${offset + index + 1}</span><b>${escapeHtml(symbol)}</b><small>${escapeHtml(managerState.names[symbol] || '名称待补充')}</small></div>`).join('') : '<div class="empty-compact">没有匹配的代码</div>';
  $('symbolPager').innerHTML = `<span>${filtered.length ? `${offset + 1}-${offset + visible.length}` : '0'} / ${filtered.length}</span><div><button type="button" data-page="prev" title="上一页" ${managerState.symbolPage <= 1 ? 'disabled' : ''}><i class="ti ti-chevron-left"></i></button><em>${managerState.symbolPage} / ${pages}</em><button type="button" data-page="next" title="下一页" ${managerState.symbolPage >= pages ? 'disabled' : ''}><i class="ti ti-chevron-right"></i></button></div>`;
  $('symbolPager').querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => { managerState.symbolPage += button.dataset.page === 'next' ? 1 : -1; renderSymbols(symbols, query); }));
}

function selectMarket(market) {
  managerState.market = market;
  managerState.selectedId = managerState.groups.find(group => group.market === market)?.id || null;
  managerState.symbolPage = 1;
  managerState.symbolQuery = '';
  render();
}

function openGroupModal(group = null) {
  const isEdit = Boolean(group);
  $('groupModalTitle').textContent = isEdit ? '编辑标的' : '新增标的';
  $('groupOriginalKey').value = group?.key || '';
  $('groupMarket').value = group?.market || managerState.market;
  $('groupMarket').disabled = isEdit;
  $('groupKey').value = group?.key || '';
  $('groupKey').readOnly = isEdit;
  $('groupName').value = group?.name || '';
  $('groupSymbols').value = group?.symbols.join('\n') || '';
  $('groupFormHint').textContent = isEdit ? '文件标识和所属市场创建后不可修改。' : '文件标识仅支持字母、数字、点、短横线和下划线。';
  openModal('groupModal');
  setTimeout(() => $(isEdit ? 'groupName' : 'groupKey').focus(), 0);
}

async function saveGroup(event) {
  event.preventDefault();
  const symbols = parseSymbols($('groupSymbols').value);
  if (!symbols.length) return showToast('请至少填写一个代码', 'error');
  const payload = { market: $('groupMarket').value, id: $('groupKey').value.trim(), name: $('groupName').value.trim(), symbols };
  const submit = event.submitter;
  submit.disabled = true;
  try {
    const response = await fetch('/symbol-group', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || '保存失败');
    closeModal('groupModal');
    managerState.market = result.market;
    await loadGroups(result.id);
    showToast(`已保存 ${result.name}（${result.symbols.length} 个代码）`);
  } catch (error) { showToast(error.message, 'error'); }
  finally { submit.disabled = false; }
}

function renderDownloadGroups() {
  const select = $('downloadGroup');
  if (!select) return;
  select.innerHTML = managerState.groups.map(group => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.market_label)} · ${escapeHtml(group.name)}（${group.symbols.length}）</option>`).join('');
  if (managerState.selectedId) select.value = managerState.selectedId;
  syncDownloadAsset();
}

function suggestedAsset(group) {
  if (!group) return 'astock';
  if (group.market === 'etfs') return 'etf';
  if (group.market === 'usstocks') return 'us-market';
  return 'astock';
}

function syncDownloadAsset() {
  if ($('downloadSource').value !== 'group') return;
  const group = managerState.groups.find(item => item.id === $('downloadGroup').value);
  $('downloadAsset').value = suggestedAsset(group);
}

function openDownloadModal() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1);
  const local = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  $('downloadStart').value ||= local(start);
  $('downloadEnd').value ||= local(now);
  renderDownloadGroups();
  openModal('downloadModal');
}

function toggleDownloadSource() {
  const manual = $('downloadSource').value === 'manual';
  $('downloadGroupField').hidden = manual;
  $('downloadSymbolsField').hidden = !manual;
  if (!manual) syncDownloadAsset();
}

async function submitDownload(event) {
  event.preventDefault();
  const group = managerState.groups.find(item => item.id === $('downloadGroup').value);
  const symbols = $('downloadSource').value === 'group' ? (group?.symbols || []) : parseSymbols($('downloadSymbols').value);
  if (!symbols.length) return showToast('请选择标的或输入代码', 'error');
  closeModal('downloadModal');
  await runStreamTask('/quick-download-data', { asset_type: $('downloadAsset').value, symbols, start_date: $('downloadStart').value, end_date: $('downloadEnd').value }, '快速下载数据');
}

async function runStreamTask(url, payload, title) {
  if (managerState.running) return showToast('已有数据任务正在运行', 'error');
  managerState.running = true;
  $('btnGlobalUpdate').disabled = true;
  $('btnQuickDownload').disabled = true;
  $('jobLogTitle').textContent = title;
  $('jobLogBody').textContent = '';
  $('jobLog').classList.add('open');
  try {
    const response = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload || {}) });
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || `请求失败（${response.status}）`); }
    if (!response.body) throw new Error('浏览器不支持流式任务日志');
    const reader = response.body.getReader(), decoder = new TextDecoder('utf-8');
    let buffer = '', succeeded = false, failed = false;
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
      for (const block of blocks) for (const line of block.split('\n')) if (line.startsWith('data:')) {
        const raw = line.slice(5).trim(); if (!raw || raw === '[DONE]') continue;
        const item = JSON.parse(raw); appendLog(item);
        if (item.type === 'success') succeeded = true;
        if (item.type === 'error') failed = true;
      }
      if (done) break;
    }
    showToast(failed ? '数据任务部分失败，请查看日志' : (succeeded ? '数据任务已完成' : '数据任务已结束'), failed ? 'error' : 'ok');
  } catch (error) { appendLog({type:'error', message:error.message}); showToast(error.message, 'error'); }
  finally { managerState.running = false; $('btnGlobalUpdate').disabled = false; $('btnQuickDownload').disabled = false; }
}

function appendLog(item) {
  const prefix = item.type === 'stage' ? '[阶段] ' : item.type === 'success' ? '[完成] ' : item.type === 'error' || item.type === 'stderr' ? '[错误] ' : '';
  const text = item.message || item.line || '';
  if (!text) return;
  $('jobLogBody').textContent += `${prefix}${text}\n`;
  $('jobLogBody').scrollTop = $('jobLogBody').scrollHeight;
}

function openModal(id) { $(id).dataset.open = 'true'; document.body.style.overflow = 'hidden'; }
function closeModal(id) { if (managerState.running && id === 'downloadModal') return; $(id).dataset.open = 'false'; document.body.style.overflow = ''; }

$('marketSwitch').addEventListener('click', event => { const button = event.target.closest('[data-market]'); if (button) selectMarket(button.dataset.market); });
$('groupList').addEventListener('click', event => { const button = event.target.closest('[data-group]'); if (button) { managerState.selectedId = button.dataset.group; managerState.symbolPage = 1; managerState.symbolQuery = ''; render(); } });
$('btnAddGroup').addEventListener('click', () => openGroupModal());
$('btnQuickDownload').addEventListener('click', openDownloadModal);
$('btnGlobalUpdate').addEventListener('click', () => runStreamTask('/update-market-data', {}, '全局数据更新'));
$('groupForm').addEventListener('submit', saveGroup);
$('btnGlobalUpdate').addEventListener('click', event => {
  event.preventDefault();
  event.stopImmediatePropagation();
  if (!window.confirm('即将对本地已有的股票、ETF 和指数数据进行增量更新至最新。是否继续？')) return;
  runStreamTask('/update-market-data', {}, '全局数据更新');
}, true);
$('downloadForm').addEventListener('submit', submitDownload);
$('downloadSource').addEventListener('change', toggleDownloadSource);
$('downloadGroup').addEventListener('change', syncDownloadAsset);
$('closeJobLog').addEventListener('click', () => $('jobLog').classList.remove('open'));
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => closeModal(button.dataset.close)));
document.querySelectorAll('.subject-modal').forEach(modal => modal.addEventListener('click', event => { if (event.target === modal) closeModal(modal.id); }));
document.addEventListener('keydown', event => { if (event.key === 'Escape') document.querySelectorAll('.subject-modal[data-open="true"]').forEach(modal => closeModal(modal.id)); });

toggleDownloadSource();
loadGroups();
