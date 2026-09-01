/**
 * market-display.js
 * A股大盘行情展示前端逻辑
 * 功能：行情列表（含颜色/拖拽排序/中文名）、热力图、因子分布、数据更新
 */

const API       = '';
const DATA_BASE = './data/Astocks';
const META_URL  = `${DATA_BASE}/meta.json`;
const DATES_URL = `${DATA_BASE}/dates.json`;
const LATEST_URL = `${DATA_BASE}/latest.json`;

// ── 列定义（顺序 = 初始显示顺序）────────────────────────────────────────
// sticky: 固定列类名；badge: 显示徽章；colorFn: 返回颜色类名
const COL_DEFS = [
  { key:'ts_code',       label:'股票代码',   w:'110px', sticky:'msc',  fmt:v=>v||'—',                          colorFn:()=>'',        always:true },
  { key:'name',          label:'名称',       w:'80px',  sticky:'msc2', fmt:v=>v||'—',                          colorFn:()=>'',        always:true },
  { key:'pct_chg',       label:'涨跌幅',     w:'90px',  fmt:v=>fmtPct(v),                                      colorFn:v=>clr(v),     badge:true,  defaultOn:true },
  { key:'close',         label:'最新价',     w:'80px',  fmt:v=>fmtN(v,2),                                      colorFn:v=>clr(v),     defaultOn:true },
  { key:'change',        label:'涨跌额',     w:'76px',  fmt:v=>fmtN(v,2),                                      colorFn:v=>clr(v),     defaultOn:true },
  { key:'open',          label:'开盘',       w:'76px',  fmt:v=>fmtN(v,2),                                      colorFn:(v,row)=>openClr(v,row), defaultOn:true },
  { key:'high',          label:'最高',       w:'76px',  fmt:v=>fmtN(v,2),                                      colorFn:()=>'mkt-up',  defaultOn:true },
  { key:'low',           label:'最低',       w:'76px',  fmt:v=>fmtN(v,2),                                      colorFn:()=>'mkt-dn',  defaultOn:true },
  { key:'vol',           label:'成交量(手)', w:'100px', fmt:v=>fmtBig(v),                                      colorFn:()=>'',        defaultOn:true },
  { key:'amount',        label:'成交额(万)', w:'100px', fmt:v=>fmtBig(v!=null?v/1000:null),                   colorFn:()=>'',        defaultOn:true },
  { key:'pe_ttm',        label:'PE(TTM)',    w:'80px',  fmt:v=>fmtN(v,1),                                      colorFn:()=>'',        defaultOn:true },
  { key:'pb',            label:'PB',         w:'70px',  fmt:v=>fmtN(v,2),                                      colorFn:()=>'',        defaultOn:true },
  { key:'turnover_rate', label:'换手率(%)',  w:'84px',  fmt:v=>fmtN(v,2),                                      colorFn:()=>'',        defaultOn:true },
  { key:'total_mv',      label:'总市值(亿)', w:'100px', fmt:v=>fmtBig(v!=null?v/10000:null),                  colorFn:()=>'',        defaultOn:true },
  { key:'circ_mv',       label:'流通市值',   w:'100px', fmt:v=>fmtBig(v!=null?v/10000:null),                  colorFn:()=>'' },
  { key:'mom_5',         label:'动量5日',    w:'80px',  fmt:v=>fmtPct(v!=null?v*100:null),                    colorFn:v=>clr(v) },
  { key:'mom_20',        label:'动量20日',   w:'80px',  fmt:v=>fmtPct(v!=null?v*100:null),                    colorFn:v=>clr(v) },
  { key:'volatility_20', label:'波动率20',   w:'80px',  fmt:v=>v!=null?(v*100).toFixed(2)+'%':'—',            colorFn:()=>'' },
  { key:'ma20_dev',      label:'均线偏离',   w:'80px',  fmt:v=>fmtPct(v!=null?v*100:null),                    colorFn:v=>clr(v) },
  { key:'vol_ratio',     label:'量比',       w:'70px',  fmt:v=>fmtN(v,2),                                      colorFn:()=>'' },
  { key:'amount_ma5',    label:'额均5日',    w:'90px',  fmt:v=>fmtBig(v!=null?v/1000:null),                   colorFn:()=>'' },
];

// 可切换列（非 always=true）
let toggleCols = COL_DEFS.filter(c=>!c.always);
// 当前显示顺序（包含 always 列 + 已启用的 toggle 列）
let colOrder = [
  ...COL_DEFS.filter(c=>c.always),
  ...toggleCols.filter(c=>c.defaultOn),
];

// ── 格式化工具 ────────────────────────────────────────────────────────────
function fmtN(v,d=2){ return v!=null?Number(v).toFixed(d):'—' }
function fmtPct(v){
  if(v==null) return '—';
  const n=Number(v);
  return (n>0?'+':'')+n.toFixed(2)+'%';
}
function fmtBig(v){
  if(v==null) return '—';
  v=Number(v);
  if(Math.abs(v)>=10000) return (v/10000).toFixed(1)+'万';
  if(Math.abs(v)>=1000)  return (v/1000).toFixed(1)+'千';
  return v.toFixed(0);
}
// 红涨绿跌
function clr(v){ return v==null?'':v>0?'mkt-up':v<0?'mkt-dn':'mkt-flat' }
// 开盘颜色：高开红色，低开绿色，平开灰色
function openClr(open, row){
  if(open==null || row.pre_close==null) return '';
  return open > row.pre_close ? 'mkt-up' : open < row.pre_close ? 'mkt-dn' : 'mkt-flat';
}

// ── 状态 ──────────────────────────────────────────────────────────────────
let allStocks=[], filteredStocks=[];
let curDate='', curPage=1, pageSize=50;
let sortKey='pct_chg', sortAsc=false;
let factorChartInst=null;
let marketFactorChart=null;
let stockGroups = [], activeGroupId = '__all__', activeAssetBase = DATA_BASE;
function escapeHtml(value){ return String(value).replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch])); }

async function loadStockGroups(){
  try{
    const res = await fetch(`${API}/astocks-symbol-groups`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    stockGroups = Array.isArray(payload.groups) ? payload.groups : [];
  }catch(e){
    stockGroups = [];
    console.warn('股票分组未加载：', e.message);
  }
  renderStockGroups();
}

function renderStockGroups(){
  const host = document.getElementById('stockGroupList');
  if(!host) return;
  const groups = [{id:'__all__', name:'全部A股', symbols:[]}].concat(stockGroups);
  host.innerHTML = groups.map(group => `<button type="button" class="group-item ${group.id===activeGroupId?'active':''}" data-group-id="${escapeHtml(group.id)}"><span>${escapeHtml(group.name)}</span><span class="group-count">${group.id==='__all__' ? allStocks.length : group.symbols.length}</span></button>`).join('');
  host.querySelectorAll('[data-group-id]').forEach(button => {
    button.onclick = async () => {
      activeGroupId = button.dataset.groupId;
      const group = stockGroups.find(item => item.id === activeGroupId);
      activeAssetBase = activeGroupId === '__all__' ? DATA_BASE : (group && group.data_base ? group.data_base : DATA_BASE);
      window.ASTOCKS_ACTIVE_ASSET_BASE = activeAssetBase;
      await loadAssetSnapshot();
      applyFilter();
    };
  });
}

async function loadAssetSnapshot(){
  const base = activeAssetBase || DATA_BASE;
  try{
    const [latestResponse, datesResponse] = await Promise.all([fetch(`${base}/latest.json`), fetch(`${base}/dates.json`)]);
    if(!latestResponse.ok) throw new Error(`HTTP ${latestResponse.status}`);
    const payload = await latestResponse.json();
    allStocks = payload.data || [];
    const date = payload.date || '';
    const selector = document.getElementById('mktDate');
    if(datesResponse.ok){
      const datesPayload = await datesResponse.json();
      const dates = [...(datesPayload.dates || [])].sort().reverse();
      selector.innerHTML = dates.map(item => `<option value="${item}">${item}</option>`).join('');
      selector.value = date || dates[0] || '';
    } else if(date && selector.value !== date){
      selector.value = date;
    }
  }catch(error){
    allStocks=[];
    document.getElementById('mktMeta').textContent = `数据加载失败：${error.message}`;
  }
}

function activeSymbols(){
  const group = stockGroups.find(item => item.id === activeGroupId);
  return activeGroupId === '__all__' ? null : new Set(group ? group.symbols : []);
}

// ── Tab 切换 ──────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.mkt-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.mkt-tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  btn.classList.add('active');
  if(name==='indices') loadIndices();
  if(name==='factors') loadMarketFactors();
}

async function loadMarketFactors(){
  const cards=document.getElementById('factorCards');
  try{
    const res=await fetch('/market-factors'); if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const points=(await res.json()).data||[]; const last=points.at(-1)||{};
    const defs=[['turnover_ratio','成交额 / 总市值','percent'],['crowding','交易拥挤度','percent'],['margin_ratio','两融余额 / 总市值','percent'],['deposit_ratio','居民存款 / 总市值','percent']];
    const fmtFactor=(v,kind)=>v==null?'待导入':`${(v*100).toFixed(2)}%`;
    cards.innerHTML=defs.map(([key,label])=>`<div class="factor-card"><label>${label}</label><strong>${fmtFactor(last[key])}</strong><small>${last.date||'-'} · ${key==='margin_ratio'||key==='deposit_ratio'?'需要导入宏观序列':'由 A 股日行情计算'}</small></div>`).join('');
    if(!window.Chart||!points.length) return;
    if(marketFactorChart) marketFactorChart.destroy();
    marketFactorChart=new Chart(document.getElementById('marketFactorCanvas'),{type:'line',data:{labels:points.map(p=>p.date),datasets:[{label:'成交额/总市值',data:points.map(p=>p.turnover_ratio==null?null:p.turnover_ratio*100),borderColor:'#58a6ff',tension:.25},{label:'交易拥挤度',data:points.map(p=>p.crowding==null?null:p.crowding*100),borderColor:'#f2cc60',tension:.25},{label:'两融/总市值',data:points.map(p=>p.margin_ratio==null?null:p.margin_ratio*100),borderColor:'#f85149',tension:.25},{label:'居民存款/总市值',data:points.map(p=>p.deposit_ratio==null?null:p.deposit_ratio*100),borderColor:'#3fb950',tension:.25}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#c9d1d9'}}},scales:{x:{ticks:{color:'#8b949e',maxTicksLimit:12},grid:{color:'#30363d'}},y:{ticks:{color:'#8b949e',callback:v=>v+'%'},grid:{color:'#30363d'}}}}});
  }catch(error){ cards.innerHTML=`<div class="factor-card"><label>市场因子</label><strong>加载失败</strong><small>${escapeHtml(error.message)}</small></div>`; }
}

let marketFactorPoints = [];
let activeMarketFactor = 'turnover_ratio';

async function loadMarketFactors(){
  const cards = document.getElementById('factorCards');
  try{
    const response = await fetch('/market-factors');
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    marketFactorPoints = (await response.json()).data || [];
    const last = marketFactorPoints.at(-1) || {};
    const defs = [
      ['turnover_ratio','成交额 / 总市值','#58a6ff','由 A 股日行情计算'],
      ['crowding','交易拥挤度','#f2cc60','成交额前 5% 个股占比'],
      ['margin_ratio','两融余额 / 总市值','#f85149','待导入宏观序列'],
      ['deposit_ratio','居民存款 / 总市值','#3fb950','待导入宏观序列']
    ];
    cards.innerHTML = defs.map(([key,label,color,note]) => `<div class="factor-card"><label>${label}</label><strong style="color:${last[key]==null?'#8b949e':color}">${last[key]==null?'待导入':(last[key]*100).toFixed(2)+'%'}</strong><small>${last.date||'-'} · ${note}</small></div>`).join('');
    const controls = document.getElementById('factorControls');
    controls.innerHTML = defs.map(([key,label,color]) => `<button type="button" data-factor="${key}" style="--factor-color:${color}">${label}</button>`).join('');
    controls.querySelectorAll('[data-factor]').forEach(button => button.onclick = () => { activeMarketFactor=button.dataset.factor; renderMarketFactorChart(); });
    renderMarketFactorChart();
  }catch(error){ cards.innerHTML=`<div class="factor-card"><label>市场因子</label><strong>加载失败</strong><small>${escapeHtml(error.message)}</small></div>`; }
}

function renderMarketFactorChart(){
  const config = {
    turnover_ratio:{label:'成交额 / 总市值',color:'#58a6ff',note:'市场整体交易活跃度'},
    crowding:{label:'交易拥挤度',color:'#f2cc60',note:'成交额前 5% 个股的成交额占比'},
    margin_ratio:{label:'两融余额 / 总市值',color:'#f85149',note:'待导入两融余额宏观时间序列'},
    deposit_ratio:{label:'居民存款 / 总市值',color:'#3fb950',note:'待导入居民存款宏观时间序列'}
  }[activeMarketFactor];
  const host=document.getElementById('marketFactorHost'), tip=document.getElementById('marketFactorTooltip');
  document.getElementById('marketFactorTitle').textContent=config.label;
  document.getElementById('marketFactorFoot').textContent=`${config.note} · 鼠标滚轮缩放，拖动平移`;
  document.querySelectorAll('[data-factor]').forEach(button=>button.classList.toggle('active',button.dataset.factor===activeMarketFactor));
  if(marketFactorChart && marketFactorChart.remove) marketFactorChart.remove();
  if(!window.LightweightCharts || !host) return;
  marketFactorChart=LightweightCharts.createChart(host,{width:host.clientWidth,height:host.clientHeight,layout:{background:{color:'#0b1020'},textColor:'#9aa9bd'},grid:{vertLines:{color:'rgba(139,148,158,.12)'},horzLines:{color:'rgba(139,148,158,.12)'}},rightPriceScale:{borderColor:'#303846'},timeScale:{borderColor:'#303846'},crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
  const series=marketFactorChart.addLineSeries({color:config.color,lineWidth:2,priceFormat:{type:'custom',formatter:value=>`${value.toFixed(2)}%`},priceLineVisible:false});
  const values=marketFactorPoints.filter(point=>point[activeMarketFactor]!=null).map(point=>({time:`${point.date.slice(0,4)}-${point.date.slice(4,6)}-${point.date.slice(6)}`,value:point[activeMarketFactor]*100}));
  series.setData(values); marketFactorChart.timeScale().fitContent();
  const byTime=new Map(marketFactorPoints.map(point=>[`${point.date.slice(0,4)}-${point.date.slice(4,6)}-${point.date.slice(6)}`,point]));
  marketFactorChart.subscribeCrosshairMove(param=>{const point=byTime.get(String(param.time));if(!param.point||!point||point[activeMarketFactor]==null){tip.style.display='none';return;}tip.innerHTML=`<b>${point.date}</b><br>${config.label}: <strong style="color:${config.color}">${(point[activeMarketFactor]*100).toFixed(2)}%</strong><br><span>数据口径：${config.note}</span>`;tip.style.display='block';tip.style.left=`${Math.min(host.clientWidth-tip.offsetWidth-10,Math.max(10,param.point.x+14))}px`;tip.style.top=`${Math.min(host.clientHeight-tip.offsetHeight-10,Math.max(10,param.point.y+14))}px`;});
}

async function loadIndices(){
  const body = document.getElementById('indexTbody');
  if(!body) return;
  body.innerHTML='<tr><td colspan="10" class="mkt-msg">正在加载指数数据…</td></tr>';
  try{
    const res = await fetch(`${API}/astocks-indices`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    const rows = payload.data || [];
    if(!rows.length){ body.innerHTML='<tr><td colspan="10" class="mkt-msg">暂无指数数据，请点击更新数据。</td></tr>'; return; }
    body.innerHTML = rows.map(row=>`<tr onclick="window.ASTOCKSChartCard && window.ASTOCKSChartCard.openIndex('${row.ts_code}')"><td>${row.ts_code}</td><td>${row.name||'-'}</td><td class="${clr(row.pct_chg)}">${fmtN(row.close)}</td><td class="${clr(row.change)}">${fmtN(row.change)}</td><td><span class="badge ${row.pct_chg>0?'badge-up':row.pct_chg<0?'badge-dn':'badge-fl'}">${fmtPct(row.pct_chg)}</span></td><td>${fmtN(row.open)}</td><td class="mkt-up">${fmtN(row.high)}</td><td class="mkt-dn">${fmtN(row.low)}</td><td>${fmtBig(row.vol)}</td><td>${fmtBig(row.amount)}</td></tr>`).join('');
  }catch(error){ body.innerHTML=`<tr><td colspan="10" class="mkt-msg">指数数据加载失败：${escapeHtml(error.message)}</td></tr>`; }
}

// ── 初始化列切换栏（支持拖拽排序）────────────────────────────────────────
function initColToggleBar(){
  const bar = document.getElementById('colToggleBar');
  // 清除旧按钮（保留 label span）
  [...bar.querySelectorAll('.mkt-col-btn')].forEach(b=>b.remove());

  toggleCols.forEach(col=>{
    const btn = document.createElement('button');
    btn.className = 'mkt-col-btn' + (colOrder.find(c=>c.key===col.key)?' on':'');
    btn.textContent = col.label;
    btn.dataset.key = col.key;
    btn.draggable = true;

    btn.onclick = () => toggleCol(btn, col);

    // 拖拽排序
    btn.addEventListener('dragstart', e=>{
      e.dataTransfer.setData('text/plain', col.key);
      btn.style.opacity='.4';
    });
    btn.addEventListener('dragend', ()=>{ btn.style.opacity='1'; });
    btn.addEventListener('dragover', e=>{ e.preventDefault(); btn.classList.add('drag-over'); });
    btn.addEventListener('dragleave', ()=>btn.classList.remove('drag-over'));
    btn.addEventListener('drop', e=>{
      e.preventDefault();
      btn.classList.remove('drag-over');
      const fromKey = e.dataTransfer.getData('text/plain');
      if(fromKey===col.key) return;
      // 在 toggleCols 里交换位置
      const fi = toggleCols.findIndex(c=>c.key===fromKey);
      const ti = toggleCols.findIndex(c=>c.key===col.key);
      if(fi<0||ti<0) return;
      const [moved] = toggleCols.splice(fi,1);
      toggleCols.splice(ti,0,moved);
      rebuildColOrder();
      initColToggleBar();
      render();
    });

    bar.appendChild(btn);
  });
}

function toggleCol(btn, col){
  const idx = colOrder.findIndex(c=>c.key===col.key);
  if(idx>=0){
    // 至少保留1个非固定列
    if(colOrder.filter(c=>!c.always).length<=1) return;
    colOrder.splice(idx,1);
    btn.classList.remove('on');
  } else {
    colOrder.push(col);
    rebuildColOrder();
    btn.classList.add('on');
  }
  render();
}

function rebuildColOrder(){
  // always 列在前，然后按 toggleCols 顺序排
  const alwaysCols = COL_DEFS.filter(c=>c.always);
  const enabledKeys = new Set(colOrder.filter(c=>!c.always).map(c=>c.key));
  colOrder = [...alwaysCols, ...toggleCols.filter(c=>enabledKeys.has(c.key))];
}

// ── 加载数据 ──────────────────────────────────────────────────────────────
async function loadData(){
  document.getElementById('mktTbody').innerHTML='<tr><td colspan="20" class="mkt-msg">加载中…</td></tr>';
  try{
    const [metaRes, datesRes, latestRes] = await Promise.all([fetch(META_URL), fetch(DATES_URL), fetch(LATEST_URL)]);
    if(!metaRes.ok || !datesRes.ok || !latestRes.ok) throw new Error('Market data partitions are unavailable');
    if(false)
      throw new Error('分段数据未生成，请先运行 --build-partitions');

    const [meta, datesPayload, latestPayload] = await Promise.all([metaRes.json(), datesRes.json(), latestRes.json()]);
    document.getElementById('mktMeta').textContent =
      `A股大盘 · 上市股票 ${meta.stock_count||'—'} 只 · 更新于 ${meta.updated_at||'—'}`;

    const sortedDates = [...(datesPayload.dates||[])].sort().reverse();
    const sel = document.getElementById('mktDate');
    sel.innerHTML = sortedDates.map(d=>`<option value="${d}">${d}</option>`).join('');
    curDate = latestPayload.date || sortedDates[0] || '';
    sel.value = curDate;
    sel.onchange = async ()=>{
      curDate=sel.value;
      await loadDate(curDate);
    };

    initColToggleBar();
    await loadStockGroups();
    allStocks = latestPayload.data||[];
    applyFilter();
  } catch(e){
    document.getElementById('mktTbody').innerHTML=
      `<tr><td colspan="20" class="mkt-msg" style="color:var(--mkt-up)">
        加载失败：${e.message}<br>
        <small style="color:#8b949e">请先生成 data/Astocks/dates.json 和 daily/ 分段文件</small>
      </td></tr>`;
    document.getElementById('mktMeta').textContent='加载失败';
  }
}

async function loadDate(date){
  document.getElementById('mktTbody').innerHTML='<tr><td colspan="20" class="mkt-msg">加载行情中…</td></tr>';
  try{
    const response = await fetch(`${activeAssetBase || DATA_BASE}/daily/${date}.json`);
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    allStocks = payload.data||[];
  } catch(e){
    allStocks=[];
    document.getElementById('mktMeta').textContent = `日期 ${date} 加载失败：${e.message}`;
  }
  applyFilter();
}

function applyFilter(){
  const q   = document.getElementById('mktSearch').value.toLowerCase().trim();
  const dir = document.getElementById('mktDir').value;
  const symbols = activeSymbols();
  filteredStocks = allStocks.filter(s=>{
    if(symbols && !symbols.has(s.ts_code)) return false;
    if(q && !s.ts_code.toLowerCase().includes(q) && !(s.name||'').toLowerCase().includes(q)) return false;
    if(dir==='up'   && !(s.pct_chg>0))  return false;
    if(dir==='down' && !(s.pct_chg<0))  return false;
    if(dir==='flat' && s.pct_chg!==0)   return false;
    return true;
  });
  doSort(); updateStats(); curPage=1; render(); renderStockGroups();
}

function doSort(){
  filteredStocks.sort((a,b)=>{
    const av=a[sortKey], bv=b[sortKey];
    if(av==null&&bv==null) return 0;
    if(av==null) return 1; if(bv==null) return -1;
    return sortAsc?(av>bv?1:-1):(av<bv?1:-1);
  });
}

function setSort(key){
  if(sortKey===key) sortAsc=!sortAsc; else{sortKey=key;sortAsc=false;}
  doSort(); curPage=1; render();
}

function updateStats(){
  const up  = filteredStocks.filter(s=>s.pct_chg>0).length;
  const dn  = filteredStocks.filter(s=>s.pct_chg<0).length;
  const fl  = filteredStocks.filter(s=>s.pct_chg===0).length;
  const avg = filteredStocks.length
    ? filteredStocks.reduce((a,s)=>a+(s.pct_chg||0),0)/filteredStocks.length : 0;
  const amt = filteredStocks.reduce((a,s)=>a+(s.amount||0),0);

  document.getElementById('sTot').textContent = filteredStocks.length;
  document.getElementById('sUp').textContent  = up;
  document.getElementById('sDn').textContent  = dn;
  document.getElementById('sFl').textContent  = fl;
  const avgEl = document.getElementById('sAvg');
  avgEl.textContent = (avg>0?'+':'')+avg.toFixed(2)+'%';
  avgEl.className   = 'mkt-stat-val '+(avg>0?'mkt-up':avg<0?'mkt-dn':'mkt-flat');
  document.getElementById('sAmt').textContent = fmtBig(amt/100000000);
}

function render(){
  const total = Math.max(1,Math.ceil(filteredStocks.length/pageSize));
  curPage = Math.min(curPage,total);
  const slice = filteredStocks.slice((curPage-1)*pageSize, curPage*pageSize);

  // 表头
  document.getElementById('mktThead').innerHTML = `<tr>${colOrder.map(col=>{
    const s = sortKey===col.key;
    return `<th class="${col.sticky||''} ${s?'sorted':''}" style="width:${col.w||'80px'}"
              onclick="setSort('${col.key}')">
              ${col.label}<span class="si">${s?(sortAsc?'↑':'↓'):'⇅'}</span></th>`;
  }).join('')}</tr>`;

  // 表体
  if(!slice.length){
    document.getElementById('mktTbody').innerHTML='<tr><td colspan="20" class="mkt-msg">暂无数据</td></tr>';
  } else {
    document.getElementById('mktTbody').innerHTML = slice.map(row=>`<tr class="stock-click-row" data-symbol="${row.ts_code}" onclick="window.ASTOCKSChartCard && window.ASTOCKSChartCard.openStock('${row.ts_code}')">${
      colOrder.map(col=>{
        const v = row[col.key];
        const cc = col.colorFn(v, row);
        const tdCls = [col.sticky||'', cc].filter(Boolean).join(' ');
        let cell;
        if(col.badge && v!=null){
          const bc = v>0?'badge-up':v<0?'badge-dn':'badge-fl';
          cell = `<span class="badge ${bc}">${col.fmt(v)}</span>`;
        } else {
          cell = `<span class="${cc}">${col.fmt(v)}</span>`;
        }
        return `<td class="${tdCls}" title="${v!=null?v:''}">${cell}</td>`;
      }).join('')
    }</tr>`).join('');
  }

  const pg = document.getElementById('mktPg');
  pg.style.display = 'flex';
  document.getElementById('pgCur').textContent   = curPage;
  document.getElementById('pgTot').textContent   = total;
  document.getElementById('pgTotal').textContent = `共 ${filteredStocks.length} 条`;
  document.getElementById('pgPrev').disabled     = curPage<=1;
  document.getElementById('pgNext').disabled     = curPage>=total;
}

function changePage(d){ curPage+=d; render(); }

// ── 导出 CSV ──────────────────────────────────────────────────────────────
function exportCSV(){
  if(!filteredStocks.length) return;
  const header = colOrder.map(c=>c.label).join(',');
  const rows   = filteredStocks.map(s=>
    colOrder.map(c=>{ const v=s[c.key]; return v!=null?String(v):''; }).join(',')
  );
  const blob = new Blob(['\uFEFF'+[header,...rows].join('\n')],{type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `A股大盘_${curDate}.csv`;
  a.click();
}

// ── 更新数据（SSE）────────────────────────────────────────────────────────
function triggerUpdate(){
  const btn     = document.getElementById('btnUpdate');
  const drawer  = document.getElementById('updateDrawer');
  const logEl   = document.getElementById('updateLog');

  if(btn.classList.contains('running')) return;

  const today = new Date();
  const start = '20250101';

  btn.classList.add('running');
  btn.innerHTML = '<i class="ti ti-loader"></i> 更新中…';
  drawer.classList.add('open');
  logEl.innerHTML = '';

  function appendLog(cls, text){
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = text;
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
  }

  appendLog('log-stage', `▶ 开始更新 ${start} → ${today.toISOString().slice(0,10).replace(/-/g,'')}`);

  const es = new EventSource(API+'/update-astocks-sse?start='+start);
  // 由于 EventSource 不支持 POST，改用 fetch + ReadableStream
  es.close();

  fetch(API+'/update-astocks', {
    method:'POST',
    headers:{'Content-Type':'text/plain;charset=UTF-8'},
    body: JSON.stringify({start_date: start})
  }).then(res=>{
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    function read(){
      reader.read().then(({done, value})=>{
        if(done){
          btn.classList.remove('running');
          btn.innerHTML = '<i class="ti ti-cloud-download"></i> 更新数据至今日';
          appendLog('log-success','✓ 更新完成，请点击「刷新」重新加载数据');
          return;
        }
        buf += decoder.decode(value, {stream:true});
        const lines = buf.split('\n');
        buf = lines.pop();
        lines.forEach(line=>{
          if(!line.startsWith('data: ')) return;
          const raw = line.slice(6).trim();
          if(raw==='[DONE]') return;
          try{
            const obj = JSON.parse(raw);
            if(obj.type==='stage')   appendLog('log-stage',   '▶ '+obj.message);
            else if(obj.type==='success') appendLog('log-success','✓ '+obj.message);
            else if(obj.type==='error')   appendLog('log-error',  '✗ '+obj.message);
            else if(obj.line)             appendLog('log-line',    obj.line);
          } catch(e){}
        });
        read();
      }).catch(err=>{
        appendLog('log-error','连接中断：'+err.message);
        btn.classList.remove('running');
        btn.innerHTML = '<i class="ti ti-cloud-download"></i> 更新数据至今日';
      });
    }
    read();
  }).catch(err=>{
    appendLog('log-error','请求失败：'+err.message+'（请确认 bs_server.py 已启动）');
    btn.classList.remove('running');
    btn.innerHTML = '<i class="ti ti-cloud-download"></i> 更新数据至今日';
  });
}

// ── 热力图 ────────────────────────────────────────────────────────────────
function renderHeatmap(){
  const wrap = document.getElementById('heatmapWrap');
  if(!allStocks.length){ wrap.innerHTML='<p style="color:#8b949e;padding:20px">请先加载数据</p>'; return; }

  const maxMv = Math.max(...allStocks.map(s=>s.total_mv||0));
  const maxPct = Math.max(...allStocks.map(s=>Math.abs(s.pct_chg||0)));

  wrap.innerHTML = allStocks
    .filter(s=>s.total_mv>0)
    .sort((a,b)=>(b.total_mv||0)-(a.total_mv||0))
    .slice(0,300)   // 只显示前300，避免卡顿
    .map(s=>{
      const sz  = Math.max(28, Math.sqrt((s.total_mv||0)/maxMv)*120);
      const pct = s.pct_chg||0;
      const ratio = Math.min(1, Math.abs(pct)/maxPct);
      const r = pct>0 ? Math.round(180*ratio+40) : 40;
      const g = pct<0 ? Math.round(160*ratio+40) : 40;
      const b = 40;
      const bg = `rgb(${r},${g},${b})`;
      const txt = pct===0?'#aaa':pct>0?'#ffb3b0':'#b3ffbe';
      return `<div onclick="window.ASTOCKSChartCard && window.ASTOCKSChartCard.openStock('${s.ts_code}')" style="width:${sz}px;height:${sz}px;background:${bg};border-radius:4px;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        font-size:${sz<40?9:11}px;color:${txt};overflow:hidden;cursor:pointer;flex-shrink:0"
        title="${s.ts_code} ${s.name||''} ${fmtPct(pct)}">
        <div style="font-weight:600;white-space:nowrap;overflow:hidden;max-width:90%;text-overflow:ellipsis">${s.name||s.ts_code}</div>
        ${sz>=40?`<div style="font-size:10px;margin-top:2px">${fmtPct(pct)}</div>`:''}
      </div>`;
    }).join('');
}

// ── 因子分布柱状图 ────────────────────────────────────────────────────────
function renderFactorChart(){
  const key = document.getElementById('factorSelect').value;
  const vals = allStocks.map(s=>s[key]).filter(v=>v!=null&&isFinite(v));
  if(!vals.length){ document.getElementById('factorStat').textContent='暂无数据'; return; }

  const min  = Math.min(...vals);
  const max  = Math.max(...vals);
  const mean = vals.reduce((a,b)=>a+b,0)/vals.length;
  const std  = Math.sqrt(vals.reduce((a,b)=>a+(b-mean)**2,0)/vals.length);

  // 分20个区间
  const bins = 20;
  const step = (max-min)/bins||1;
  const counts = Array(bins).fill(0);
  const colors = [];
  vals.forEach(v=>{ const i=Math.min(bins-1,Math.floor((v-min)/step)); counts[i]++; });

  const labels = counts.map((_,i)=>{
    const lo=(min+i*step), hi=(min+(i+1)*step);
    return `${lo.toFixed(2)}~${hi.toFixed(2)}`;
  });

  // 涨跌幅用红绿色，其他用蓝色渐变
  for(let i=0;i<bins;i++){
    const mid = min+(i+0.5)*step;
    if(key==='pct_chg'||key==='mom_5'||key==='mom_20'||key==='ma20_dev'){
      colors.push(mid>0?'rgba(248,81,73,.7)':'rgba(63,185,80,.7)');
    } else {
      colors.push(`rgba(56,139,253,${0.4+0.5*(i/bins)})`);
    }
  }

  const ctx = document.getElementById('factorCanvas').getContext('2d');
  if(factorChartInst) factorChartInst.destroy();
  factorChartInst = new Chart(ctx,{
    type:'bar',
    data:{
      labels,
      datasets:[{data:counts,backgroundColor:colors,borderWidth:0}]
    },
    options:{
      responsive:true,
      plugins:{legend:{display:false}},
      scales:{
        x:{ticks:{color:'#8b949e',font:{size:10}},grid:{color:'#30363d'}},
        y:{ticks:{color:'#8b949e'},grid:{color:'#30363d'}}
      }
    }
  });

  const col = COL_DEFS.find(c=>c.key===key);
  document.getElementById('factorStat').textContent =
    `${col?.label||key} — 均值：${mean.toFixed(4)}  标准差：${std.toFixed(4)}  样本数：${vals.length}`;
}

// ── 事件绑定 ──────────────────────────────────────────────────────────────
document.getElementById('mktSearch').addEventListener('input', applyFilter);
document.getElementById('mktDir').addEventListener('change', applyFilter);
const updateDrawer = document.getElementById('updateDrawer');
if(updateDrawer) document.querySelector('.mkt-tabs').after(updateDrawer);

// ── 启动 ──────────────────────────────────────────────────────────────────
// Index factor browser
let factorIndexItems = [];
let activeFactorIndex = null;
const factorLabels = {
  close:'收盘价', open:'开盘价', high:'最高价', low:'最低价', pre_close:'昨收价', change:'涨跌额', pct_chg:'涨跌幅(%)',
  vol:'成交量', amount:'成交额', amount_ratio_5d:'成交额/5日均值', volume_ratio:'成交量比', turnover_ma5:'成交额5日均值', liangbi:'量比',
  ma_5:'MA5', ma_10:'MA10', ma_20:'MA20', ma_60:'MA60', ma_120:'MA120', ma_250:'MA250', change_5d_pct:'5日涨幅(%)',
  change_10d_pct:'10日涨幅(%)', change_20d_pct:'20日涨幅(%)', change_60d_pct:'60日涨幅(%)', change_120d_pct:'120日涨幅(%)', change_250d_pct:'250日涨幅(%)',
  ytd_pct:'年初至今(%)', macd_dif:'MACD DIF', macd_dea:'MACD DEA', macd_hist:'MACD 柱', kdj_k:'KDJ K', kdj_d:'KDJ D', kdj_j:'KDJ J',
  rsi_6:'RSI6', rsi_12:'RSI12', boll_mid:'布林中轨', boll_upper:'布林上轨', boll_lower:'布林下轨', boll_pct_b:'布林位置', amplitude_pct:'振幅(%)',
  realized_vol_20d_pct:'20日实现波动率(%)', rps_20:'RPS20', rps_120:'RPS120', rps_250:'RPS250', above_ma20:'站上MA20', above_ma60:'站上MA60', ma20_above_ma60:'MA20>MA60',
  macd_golden_cross:'MACD金叉', macd_dead_cross:'MACD死叉', up_streak:'连续上涨天数', down_streak:'连续下跌天数', n_day_high_20:'20日新高', n_day_low_20:'20日新低'
};
function formatFactorValue(value){
  if(value == null || value === '') return '-';
  if(typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/0+$/,'').replace(/\.$/,'');
  return String(value);
}
async function loadMarketFactors(){
  const list = document.getElementById('factorIndexList');
  if(!list) return;
  list.innerHTML = '<div class="factor-empty">正在加载指数…</div>';
  try{
    const response = await fetch('/astocks-factor-index');
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    factorIndexItems = (await response.json()).data || [];
    list.innerHTML = factorIndexItems.length ? factorIndexItems.map((item,index)=>`<button type="button" data-factor-symbol="${escapeHtml(item.ts_code)}" class="${index===0?'active':''}"><span><b>${escapeHtml(item.name||item.ts_code)}</b><small>${escapeHtml(item.ts_code)}</small></span><small>${item.dates.length}日</small></button>`).join('') : '<div class="factor-empty">暂无已保存指数因子</div>';
    list.querySelectorAll('[data-factor-symbol]').forEach(button=>button.onclick=()=>selectFactorIndex(button.dataset.factorSymbol));
    if(factorIndexItems.length) selectFactorIndex(factorIndexItems[0].ts_code);
  }catch(error){ list.innerHTML = `<div class="factor-empty">加载失败：${escapeHtml(error.message)}</div>`; }
}
async function selectFactorIndex(symbol){
  activeFactorIndex = factorIndexItems.find(item=>item.ts_code===symbol) || null;
  if(!activeFactorIndex) return;
  document.querySelectorAll('[data-factor-symbol]').forEach(button=>button.classList.toggle('active',button.dataset.factorSymbol===symbol));
  const title = document.getElementById('factorDetailTitle');
  const selector = document.getElementById('factorDateSelect');
  selector.disabled = false;
  selector.innerHTML = activeFactorIndex.dates.slice().reverse().map(date=>`<option value="${date}">${date}</option>`).join('');
  title.textContent = `${activeFactorIndex.name || symbol} (${symbol})`;
  selector.onchange = ()=>loadFactorDetail(symbol, selector.value);
  await loadFactorDetail(symbol, selector.value);
}
async function loadFactorDetail(symbol,date){
  const body = document.getElementById('factorDetailBody');
  body.innerHTML = '<tr><td colspan="2" class="factor-empty">正在加载因子…</td></tr>';
  try{
    const response = await fetch(`/astocks-factor?symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(date)}`);
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const factors = payload.data && payload.data.factors ? payload.data.factors : {};
    const rows = Object.entries(factors);
    body.innerHTML = rows.length ? rows.map(([key,value])=>`<tr><td>${escapeHtml(factorLabels[key] || key)}</td><td>${escapeHtml(formatFactorValue(value))}</td></tr>`).join('') : '<tr><td colspan="2" class="factor-empty">该日期没有因子数据</td></tr>';
  }catch(error){ body.innerHTML = `<tr><td colspan="2" class="factor-empty">加载失败：${escapeHtml(error.message)}</td></tr>`; }
}
loadData();
