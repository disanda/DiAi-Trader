let competition = {data: [], leaderboard: []};
let selectedAgentId = null;
let selectedDate = null;
let selectedPrediction = null;
const classNames = {strong_down:'强跌', down:'下跌', up:'上涨', strong_up:'强涨'};
function esc(value){return String(value==null?'':value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function dateText(value){const v=String(value||'');return v.length===8?`${v.slice(0,4)}-${v.slice(4,6)}-${v.slice(6)}`:v||'--';}
function directionClass(value){return value==='up'?'pc-up':'pc-down';}
function directionText(value){return value==='up'?'上涨':'下跌';}
function accuracy(value){return value==null?'待验证':`${Number(value).toFixed(1)}%`;}

async function loadCompetition(){
  const meta=document.getElementById('pcMeta'); meta.textContent='正在读取预测和验证结果...';
  try{
    const response=await fetch('/predict-results',{cache:'no-store'}); const payload=await response.json();
    if(!response.ok||!payload.success)throw new Error(payload.error||'请求失败');
    competition={data:payload.data||[],leaderboard:payload.leaderboard||[]};
    if(competition.leaderboard.length){selectedAgentId=selectedAgentId||competition.leaderboard[0].agent_id;}
    renderLeaderboard();
    meta.textContent=competition.leaderboard.length?`共 ${competition.leaderboard.length} 个参赛智能体，按总体二分类正确率排序`:'尚无测试结果';
  }catch(error){meta.textContent=`加载失败：${error.message}`;document.getElementById('pcLeaderboard').innerHTML='<div class="pc-empty">无法读取结果。请先运行 predict/run_test.py。</div>';document.getElementById('pcDetail').innerHTML='<div class="pc-empty">暂无详情</div>';}
}

function renderLeaderboard(){
  const rows=competition.leaderboard;
  document.getElementById('pcAgents').textContent=rows.length;
  document.getElementById('pcRuns').textContent=rows.reduce((sum,item)=>sum+item.run_count,0);
  document.getElementById('pcVerified').textContent=rows.reduce((sum,item)=>sum+item.verified_predictions,0);
  const latest=rows.reduce((max,item)=>item.latest_prediction_date&&item.latest_prediction_date>max?item.latest_prediction_date:max,'');
  document.getElementById('pcDate').textContent=dateText(latest);
  if(!rows.length){document.getElementById('pcLeaderboard').innerHTML='<div class="pc-empty">尚无预测结果。配置 test_config.json 后运行测试脚本。</div>';document.getElementById('pcDetail').innerHTML='<div class="pc-empty">点击排行榜中的智能体查看预测详情</div>';return;}
  document.getElementById('pcLeaderboard').innerHTML=`<table class="pc-table"><thead><tr><th>排名</th><th>参赛智能体</th><th>预测批次</th><th>已验证</th><th>总体二分类正确率</th><th>总体四分类正确率</th><th>状态</th></tr></thead><tbody>${rows.map((item,index)=>`<tr class="${item.agent_id===selectedAgentId?'active':''}" onclick="showAgent('${esc(item.agent_id)}')"><td><span class="pc-rank rank-${Math.min(item.rank,3)}">${item.rank}</span></td><td><b>${esc(item.agent_name)}</b></td><td>${item.run_count} 天</td><td>${item.verified_predictions}/${item.total_predictions}</td><td class="score">${accuracy(item.direction_accuracy)}</td><td class="score">${accuracy(item.candle_accuracy)}</td><td>${item.pending_predictions?`<span class="pc-pending">${item.pending_predictions} 待验证</span>`:'<span class="pc-done">已完成</span>'}</td></tr>`).join('')}</tbody></table>`;
  showAgent(selectedAgentId);
}

function getAgentRuns(agentId){return competition.data.filter(item=>item.agent_id===agentId).sort((a,b)=>String(a.prediction_date).localeCompare(String(b.prediction_date)));}
function showAgent(agentId){
  selectedAgentId=agentId; const summary=competition.leaderboard.find(item=>item.agent_id===agentId); const runs=getAgentRuns(agentId); if(!summary||!runs.length)return;
  selectedDate=selectedDate&&runs.some(item=>item.prediction_date===selectedDate)?selectedDate:runs[runs.length-1].prediction_date;
  const run=runs.find(item=>item.prediction_date===selectedDate)||runs[runs.length-1]; selectedDate=run.prediction_date;
  selectedPrediction=null;
  document.querySelectorAll('#pcLeaderboard tbody tr').forEach((row,index)=>row.classList.toggle('active',competition.leaderboard[index].agent_id===agentId));
  renderRun(run,summary,runs);
}

function renderRun(run,summary,runs){
  const predictions=(run.predictions||[]).filter(item=>item.prediction); selectedPrediction=selectedPrediction&&predictions.includes(selectedPrediction)?selectedPrediction:predictions[0];
  const verified=predictions.filter(item=>item.verification); const dir=verified.length?verified.filter(item=>item.verification.direction_correct).length/verified.length*100:null; const candle=verified.length?verified.filter(item=>item.verification.candle_correct).length/verified.length*100:null;
  const dateOptions=runs.map(item=>`<option value="${esc(item.prediction_date)}" ${item.prediction_date===run.prediction_date?'selected':''}>${dateText(item.prediction_date)}</option>`).join('');
  document.getElementById('pcDetail').innerHTML=`<div class="pc-detail-head"><div class="pc-detail-title"><div><h3>${esc(run.agent_name)}</h3><p>总体已验证 ${summary.verified_predictions}/${summary.total_predictions}</p></div><label>预测日期<select id="pcDateSelect" onchange="changeDate(this.value)">${dateOptions}</select></label></div></div><div class="pc-detail-body"><div class="pc-detail-metrics"><span>总体二分类 <b>${accuracy(summary.direction_accuracy)}</b></span><span>总体四分类 <b>${accuracy(summary.candle_accuracy)}</b></span></div><div class="pc-run-meta">${dateText(run.prediction_date)} · 当日 ${verified.length}/${predictions.length} 已验证 · 二分类 ${accuracy(dir)} · 四分类 ${accuracy(candle)}</div><div class="pc-detail-list">${predictions.map((item,index)=>`<button class="pc-prediction-item ${item===selectedPrediction?'active':''}" onclick="showPrediction(${index})"><span><b>${esc(item.name||item.ts_code)}</b><small>${esc(item.ts_code)}</small></span><span class="${directionClass(item.prediction.direction)}">${directionText(item.prediction.direction)} · ${classNames[item.prediction.candle_class]||item.prediction.candle_class}</span><span>${item.verification?(item.verification.direction_correct?'正确':'错误'):'待验证'}</span></button>`).join('')}</div></div>`;
  renderPredictionDetail(selectedPrediction);
}

function changeDate(date){selectedDate=date;const summary=competition.leaderboard.find(item=>item.agent_id===selectedAgentId);const run=getAgentRuns(selectedAgentId).find(item=>item.prediction_date===date);if(run)renderRun(run,summary,getAgentRuns(selectedAgentId));}
function showPrediction(index){const run=getAgentRuns(selectedAgentId).find(item=>item.prediction_date===selectedDate);selectedPrediction=(run.predictions||[]).filter(item=>item.prediction)[index];renderRun(run,competition.leaderboard.find(item=>item.agent_id===selectedAgentId),getAgentRuns(selectedAgentId));}
function renderPredictionDetail(item){if(!item)return;const prediction=item.prediction,actual=item.actual,verification=item.verification;const body=document.querySelector('.pc-detail-body');body.insertAdjacentHTML('beforeend',`<div class="pc-detail-focus"><h4>${esc(item.name||item.ts_code)}</h4><p>数据截止：${dateText(item.as_of_date)} · ${item.lookback?item.lookback.length:0} 个交易日</p><div class="pc-detail-item"><label>预测</label><p>${directionText(prediction.direction)} / ${classNames[prediction.candle_class]||prediction.candle_class} · 置信度 ${Number(prediction.confidence||0).toFixed(0)}%</p></div><div class="pc-detail-item"><label>实际结果</label><p>${actual?`${directionText(actual.direction)} / ${classNames[actual.candle_class]} · ${Number(actual.pct_chg).toFixed(2)}% · ${verification.direction_correct?'二分类正确':'二分类错误'}，${verification.candle_correct?'四分类正确':'四分类错误'}`:'目标日数据尚未到达，等待验证'}</p></div><div class="pc-detail-item"><label>预测依据</label><p>${esc(prediction.rationale||'未提供')}</p></div><div class="pc-detail-item"><label>大盘与板块分析</label><p>${esc(prediction.market_analysis||'未提供')}</p></div></div>`);}
loadCompetition();
