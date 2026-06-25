/**
 * market-display.js
 * 中证2000 行情展示前端逻辑
 * 功能：行情列表（含颜色/拖拽排序/中文名）、热力图、因子分布、数据更新
 */

const API       = 'http://127.0.0.1:9999';
const DATA_URL  = './data/SCI2K/merged.json';

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
let rawData={}, allStocks=[], filteredStocks=[];
let curDate='', curPage=1, pageSize=50;
let sortKey='pct_chg', sortAsc=false;
let factorChartInst=null;

// ── Tab 切换 ──────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.mkt-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.mkt-tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  btn.classList.add('active');
  if(name==='heatmap') renderHeatmap();
  if(name==='factor')  renderFactorChart();
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
    const r = await fetch(DATA_URL);
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const json = await r.json();

    const meta = json.meta||{};
    document.getElementById('mktMeta').textContent =
      `${meta.index_code||'CSI2000'} · 成分股 ${meta.stock_count||'—'} 只 · 更新于 ${meta.updated_at||'—'}`;

    rawData = json.data||{};

    // 收集所有交易日
    const dates = new Set();
    for(const recs of Object.values(rawData))
      for(const rec of recs) if(rec.trade_date) dates.add(rec.trade_date);

    const sortedDates = [...dates].sort().reverse();
    const sel = document.getElementById('mktDate');
    sel.innerHTML = sortedDates.map(d=>`<option value="${d}">${d}</option>`).join('');
    curDate = sortedDates[0]||'';
    sel.onchange = ()=>{ curDate=sel.value; buildList(); };

    initColToggleBar();
    buildList();
  } catch(e){
    document.getElementById('mktTbody').innerHTML=
      `<tr><td colspan="20" class="mkt-msg" style="color:var(--mkt-up)">
        加载失败：${e.message}<br>
        <small style="color:#8b949e">请确认 data/SCI2K/merged.json 存在</small>
      </td></tr>`;
    document.getElementById('mktMeta').textContent='加载失败';
  }
}

function buildList(){
  allStocks=[];
  for(const [code, recs] of Object.entries(rawData)){
    const rec = recs.find(r=>r.trade_date===curDate) || recs[recs.length-1];
    if(rec) allStocks.push({ts_code:code, ...rec});
  }
  applyFilter();
}

function applyFilter(){
  const q   = document.getElementById('mktSearch').value.toLowerCase().trim();
  const dir = document.getElementById('mktDir').value;
  filteredStocks = allStocks.filter(s=>{
    if(q && !s.ts_code.toLowerCase().includes(q) && !(s.name||'').toLowerCase().includes(q)) return false;
    if(dir==='up'   && !(s.pct_chg>0))  return false;
    if(dir==='down' && !(s.pct_chg<0))  return false;
    if(dir==='flat' && s.pct_chg!==0)   return false;
    return true;
  });
  doSort(); updateStats(); curPage=1; render();
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
    document.getElementById('mktTbody').innerHTML = slice.map(row=>`<tr>${
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
  a.download = `CSI2000_${curDate}.csv`;
  a.click();
}

// ── 更新数据（SSE）────────────────────────────────────────────────────────
function triggerUpdate(){
  const btn     = document.getElementById('btnUpdate');
  const drawer  = document.getElementById('updateDrawer');
  const logEl   = document.getElementById('updateLog');

  if(btn.classList.contains('running')) return;

  // 本月初作为 start_date
  const today = new Date();
  const start = `${today.getFullYear()}${String(today.getMonth()+1).padStart(2,'0')}01`;

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

  const es = new EventSource(API+'/update-sci2k-sse?start='+start);
  // 由于 EventSource 不支持 POST，改用 fetch + ReadableStream
  es.close();

  fetch(API+'/update-sci2k', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
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
      return `<div style="width:${sz}px;height:${sz}px;background:${bg};border-radius:4px;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        font-size:${sz<40?9:11}px;color:${txt};overflow:hidden;cursor:default;flex-shrink:0"
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

// ── 启动 ──────────────────────────────────────────────────────────────────
loadData();