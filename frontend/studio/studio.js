/* No build step and no external chart/CDN dependency. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone = value => JSON.parse(JSON.stringify(value));
const state = {domains:[], config:null, page:'simulator', key:'', receipt:null, comparison:null, health:null};
const titles = {
  simulator:['Price simulator','Every price, explained.','Bring context, apply your strategy, and inspect the decision.'],
  strategy:['Strategy lab','Test the change. Then commit.','Draft a strategy, compare its effects, and activate with evidence.'],
  insights:['Decision analytics','See how your strategy behaves.','Follow recent decisions, rule activity, and pricing constraints.'],
  history:['Version history','A history you can return to.','Inspect earlier strategies and restore them as a new version.'],
  models:['Model evidence','Show the evidence behind the model.','Validation results, data provenance, and explicit limitations.']
};
const money = (v,currency=state.config?.studio?.currency || 'INR') => {
  try{return new Intl.NumberFormat('en-IN',{style:'currency',currency,maximumFractionDigits:2}).format(Number(v));}
  catch{return `${currency} ${Number(v).toFixed(2)}`;}
};
const shortDate = x => new Date(x).toLocaleString('en-IN',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
let toastTimer;
function toast(message,bad=false){$('toast').textContent=message;$('toast').className='toast'+(bad?' bad':'');$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
async function task(fn){try{return await fn();}catch(e){toast(e.message,true);}}
async function api(path,options={}){
  const headers={...options.headers};
  if(state.key) headers.Authorization=`Bearer ${state.key}`;
  if(options.body && typeof options.body !== 'string'){headers['Content-Type']='application/json';options={...options,body:JSON.stringify(options.body)};}
  let res;
  try{res=await fetch('/studio-api'+path,{...options,headers});}catch{throw new Error('Cannot reach the server. Check that the Studio startup command is running.');}
  const data=await res.json();
  if(!res.ok) throw new Error((typeof data.detail==='string'?data.detail:'Request failed')+(data.issues?' '+data.issues.map(i=>`${i.field}: ${i.message}`).join('; '):''));
  return data;
}
function busy(button,on,label){button.disabled=on;button.textContent=on?'Working…':label;}
function notice(text){$('notice').textContent=text;$('notice').hidden=!text;}
function selectPage(page){
  state.page=page;document.querySelectorAll('.page').forEach(x=>x.hidden=x.id!=='page-'+page);
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page));
  [$('pageLabel').textContent,$('pageTitle').textContent,$('pageSubtitle').textContent]=titles[page];
  if(page==='insights') task(loadAnalytics);
  if(page==='history') task(loadHistory);
  if(page==='models') task(loadModel);
}
async function loadDomains(preferred){
  const data=await api('/domains');state.domains=data.domains;
  $('domainSelect').innerHTML=data.domains.map(d=>`<option value="${esc(d.domain)}">${esc(d.label)}</option>`).join('');
  if(preferred && data.domains.some(d=>d.domain===preferred)) $('domainSelect').value=preferred;
  $('domainCount').textContent=data.domains.length;
  await loadDomain();
}
async function loadDomain(){
  const domain=$('domainSelect').value;
  const d=await api('/domains/'+encodeURIComponent(domain));state.config=d.config;
  $('ruleCount').textContent=d.config.rules.length;
  $('domainDescription').textContent=d.config.studio.description||'Configure the attributes for this industry.';
  $('candidateJson').value=JSON.stringify(state.config,null,2);
  state.comparison=null;$('comparisonResult').innerHTML='';$('comparisonCases').value='';$('caseSource').textContent='No scenarios loaded';
  renderFields();renderRules();$('conditions').innerHTML='';addCondition();
  $('decisionPanel').innerHTML='<div class="empty-state"><div class="empty-icon">◈</div><h2>A price with a paper trail.</h2><p>Calculate a scenario to inspect each adjustment, the context source, and its reproducible decision record.</p><div class="empty-steps"><span>Context</span><span>Rules</span><span>Explanation</span></div></div>';
  state.receipt=null;
  if(state.page==='insights') await loadAnalytics();
  if(state.page==='history') await loadHistory();
}
function renderFields(){
  const fields=state.config.studio.fields;
  $('scenarioFields').innerHTML=Object.entries(fields).map(([key,f])=>{
    let input;
    if(f.type==='boolean') input=`<select data-context="${esc(key)}"><option value="false" ${f.default===false?'selected':''}>No</option><option value="true" ${f.default===true?'selected':''}>Yes</option></select>`;
    else if(f.options) input=`<select data-context="${esc(key)}">${f.options.map(v=>`<option value="${esc(v)}" ${v===f.default?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
    else input=`<input data-context="${esc(key)}" type="${f.type==='number'?'number':'text'}" value="${esc(f.default??'')}" ${f.min!==undefined?`min="${Number(f.min)}"`:''} ${f.max!==undefined?`max="${Number(f.max)}"`:''} step="${esc(f.step??'any')}" ${f.required?'required':''}>`;
    return `<label>${esc(f.label||key)}${f.unit?` <span class="muted-text">· ${esc(f.unit)}</span>`:''}${input}</label>`;
  }).join('');
  $('useWeather').checked=false;$('useML').checked=false;$('useRaw').checked=false;
  $('weatherOption').hidden=!state.config.studio.signal_bindings?.weather;
  $('mlOption').hidden=!state.config.studio.demand_adapter;
  $('locationFields').hidden=true;$('contextMode').textContent='Manual scenario';
  $('rawContext').value=JSON.stringify(readFields(),null,2);
}
function readFields(){
  const result={};
  document.querySelectorAll('[data-context]').forEach(el=>{
    const key=el.dataset.context,f=state.config.studio.fields[key];
    if(el.value==='' && !f.required)return;
    result[key]=f.type==='number'?Number(el.value):f.type==='boolean'?el.value==='true':el.value;
  });return result;
}
function contextMode(){
  $('locationFields').hidden=!$('useWeather').checked;
  $('contextMode').textContent=[$('useWeather').checked?'Live weather':null,$('useML').checked?'Predicted demand':null].filter(Boolean).join(' + ')||'Manual scenario';
}
function waterfall(r){
  const rows=[{label:'Base price',before:0,after:r.base_price,kind:'base'},...r.steps,{label:'Final price',before:0,after:r.final_price,kind:'total'}];
  const max=Math.max(1,...rows.flatMap(s=>[s.before,s.after]));
  return `<div class="waterfall">${rows.map(s=>{
    const left=Math.min(s.before,s.after)/max*100,width=Math.abs(s.after-s.before)/max*100;
    const type=s.kind==='rule'?(s.delta>=0?'up':'down'):s.kind==='constraint'?'constraint':'total';
    const fields=r.config_snapshot?.studio?.fields||{};
    const matched=(s.conditions||[]).map(c=>`${fields[c.field]?.label||c.field}: ${r.resolved_context[c.field]} ${c.op} ${c.value}`).join(' AND ');
    const label=s.kind==='rule'?(s.label===s.id?(s.conditions.length?matched:'Unconditional rule'):s.label):s.label.replace(/_/g,' ');
    const amount=s.kind==='base'||s.kind==='total'?money(s.after,r.currency):`${s.delta>=0?'+':'−'}${money(Math.abs(s.delta),r.currency)}`;
    return `<div class="wf-row"><div class="wf-label" title="${esc(matched)}">${esc(label)}${s.id?`<small>${esc(s.kind==='rule'?s.id:s.kind)}</small>`:''}</div><div class="wf-track"><span class="wf-bar ${type}" style="left:${left.toFixed(3)}%;width:${width.toFixed(3)}%" title="${esc(money(s.before,r.currency)+' → '+money(s.after,r.currency))}"></span></div><div class="wf-number">${esc(amount)}</div></div>`;
  }).join('')}</div><div class="wf-caption">Bars use one shared price scale. Purple adjustments show applied constraints.</div>`;
}
function renderDecision(r){
  state.receipt=r;
  const change=r.base_price?(r.final_price/r.base_price-1)*100:0;
  $('decisionPanel').innerHTML=`<div class="panel-head"><div><h2>Decision inspector</h2><p>Recorded inputs. Versioned rules. Reproducible result.</p></div><span class="badge green">SAVED</span></div>
    <div class="price-top"><div class="price-eyebrow">CALCULATED PRICE · ${esc(r.domain.replace(/_/g,' '))}</div><div class="price-value">${esc(money(r.final_price,r.currency))}</div><div class="price-sub"><span>${r.base_price?`${change>=0?'↑':'↓'} ${Math.abs(change).toFixed(1)}% ${change>=0?'above':'below'} base price`:'Zero base price'}</span><span>${r.fired_rules.length} rules applied</span></div></div>
    <h3>How the price was built</h3>${waterfall(r)}
    ${r.warnings.map(w=>`<div class="warning">${esc(w)}</div>`).join('')}
    ${Object.entries(r.sources).map(([k,s])=>`<div class="warning ${s.status==='stale'?'':'success'}"><b>${esc(k.replace(/_/g,' '))}</b> · ${esc(s.provider||s.selected_model||s.source)}<br>${s.signal_time?`${esc(shortDate(s.signal_time))} · ${esc(s.status)} · Rain ${s.rain_mm+s.showers_mm} mm`:`Model ${esc(s.model_version)} · Score ${Number(s.demand_score).toFixed(3)}`}<br>${esc(s.attribution||s.note||'')}</div>`).join('')}
    ${r.settlement?`<div class="warning">Configured minimum driver payout: <b>${esc(money(r.settlement.minimum,r.currency))}</b>. ${r.settlement.status==='verified'?'Supplied payout meets the configured minimum.':'Actual payout was not supplied; settlement is not verified.'}</div>`:''}
    <div class="receipt-details"><div class="receipt-grid"><div><small>DECISION ID</small><b>${esc(r.decision_id.slice(0,16))}…</b></div><div><small>EVALUATION DATE</small><b>${esc(r.evaluation_date)} · ${esc(r.timezone)}</b></div><div><small>CONFIGURATION HASH</small><b>${esc(r.config_hash.slice(0,16))}…</b></div><div><small>ENGINE EVALUATION</small><b>${Number(r.engine_latency_ms).toFixed(2)} ms</b></div></div><div class="inline-actions"><button class="button quiet small" id="replayBtn">↶ Replay exactly</button><button class="button quiet small" id="receiptDownload">Download receipt</button></div><div id="replayResult"></div></div>`;
  $('replayBtn').onclick=()=>task(async()=>{const replay=await api(`/decisions/${r.decision_id}/replay`,{method:'POST'});$('replayResult').innerHTML=`<div class="warning ${replay.identical?'success':''}">${replay.identical?'Exact match':'Mismatch detected'} · ${esc(money(replay.replayed_price,r.currency))}. Used the original date and inputs; ${replay.external_calls} external calls.</div>`;});
  $('receiptDownload').onclick=()=>download('decision_'+r.decision_id+'.json',JSON.stringify(r,null,2),'application/json');
}
async function calculate(event){
  event.preventDefault();const button=$('calculateBtn');busy(button,true,'Calculate price →');
  try{
    const body={domain:state.config.domain,context:$('useRaw').checked?JSON.parse($('rawContext').value):readFields(),predict_demand:$('useML').checked};
    if($('evaluationDate').value) body.evaluation_date=$('evaluationDate').value;
    if($('useWeather').checked)body.live_weather={latitude:Number($('latitude').value),longitude:Number($('longitude').value)};
    const r=await api('/price',{method:'POST',body});renderDecision(r);toast('Decision calculated and recorded.');
  }catch(e){toast(e.message,true);}finally{busy(button,false,'Calculate price →');}
}
function conditionText(c){return `${state.config.studio.fields[c.field]?.label||c.field} ${c.op} ${c.value}`;}
function actionText(a){return ({percent_increase:`+${a.value}%`,percent_decrease:`−${a.value}%`,flat_add:`${a.value>=0?'+':''}${money(a.value)}`,flat_set:`Set ${money(a.value)}`})[a.type]||a.type;}
function renderRules(){
  $('rulesTable').innerHTML=state.config.rules.map((r,i)=>`<tr><td><strong>${esc(r.description||r.id)}</strong><small>${esc(r.id)} · ${esc(r.conditions.map(conditionText).join(' AND ')||'Always applies')}</small></td><td>${esc(actionText(r.action))}</td><td><span class="badge">${r.priority}</span></td><td><button class="link-button" data-remove-rule="${i}">Remove in draft</button></td></tr>`).join('');
}
function addCondition(){
  const row=document.createElement('div');row.className='condition-row';
  row.innerHTML=`<label>Attribute<select class="condition-field">${Object.entries(state.config.studio.fields).map(([k,f])=>`<option value="${esc(k)}">${esc(f.label||k)}</option>`).join('')}</select></label><label>Operator<select class="condition-op"><option>&gt;</option><option>&lt;</option><option>&gt;=</option><option>&lt;=</option><option>==</option></select></label><label>Value<input class="condition-value" required></label><button class="icon-button" type="button" aria-label="Remove condition">×</button>`;
  row.querySelector('button').onclick=()=>row.remove();
  row.querySelector('.condition-field').onchange=()=>{
    const f=state.config.studio.fields[row.querySelector('.condition-field').value];
    const input=row.querySelector('.condition-value');input.type=f.type==='number'?'number':'text';input.step='any';input.value=f.default??'';
    if(f.type!=='number')row.querySelector('.condition-op').value='==';
  };$('conditions').appendChild(row);row.querySelector('.condition-field').dispatchEvent(new Event('change'));
}
function addRule(event){
  event.preventDefault();task(()=>{
    const candidate=JSON.parse($('candidateJson').value);
    const conditions=[...document.querySelectorAll('.condition-row')].map(row=>{
      const field=row.querySelector('.condition-field').value,kind=state.config.studio.fields[field].type;
      const raw=row.querySelector('.condition-value').value;
      if(kind==='boolean' && !['true','false'].includes(raw.toLowerCase()))throw new Error('For boolean conditions enter true or false.');
      return {field,op:row.querySelector('.condition-op').value,value:kind==='number'?Number(raw):kind==='boolean'?raw.toLowerCase()==='true':raw};
    });
    const rule={id:$('ruleId').value.trim(),description:$('ruleDescription').value.trim()||$('ruleId').value.trim(),priority:Number($('rulePriority').value),conditions,action:{type:$('actionType').value,value:Number($('actionValue').value)}};
    if($('effectiveFrom').value)rule.effective_from=$('effectiveFrom').value;
    if($('effectiveTo').value)rule.effective_to=$('effectiveTo').value;
    candidate.rules.push(rule);setCandidate(candidate);toast('Rule added to the candidate. Compare before activating.');
  });
}
function invalidateComparison(){state.comparison=null;$('comparisonResult').innerHTML='';}
function setCandidate(candidate){$('candidateJson').value=JSON.stringify(candidate,null,2);invalidateComparison();}
async function loadCases(){const result=await api(`/domains/${state.config.domain}/scenarios`);$('comparisonCases').value=JSON.stringify(result.contexts,null,2);$('caseSource').textContent=result.source;invalidateComparison();}
async function compare(){
  const button=$('compareBtn');busy(button,true,'Compare strategies');
  try{
    const body={domain:state.config.domain,candidate:JSON.parse($('candidateJson').value),contexts:JSON.parse($('comparisonCases').value)};
    if($('evaluationDate').value)body.evaluation_date=$('evaluationDate').value;
    const r=await api('/compare',{method:'POST',body});state.comparison=r;
    $('comparisonResult').innerHTML=`<div class="stat-grid"><div class="stat-card"><small>Scenarios evaluated</small><strong>${r.cases}</strong><p>${r.valid_cases} valid comparisons</p></div><div class="stat-card"><small>Prices changed</small><strong>${r.changed}</strong><p>Of the supplied scenarios</p></div><div class="stat-card"><small>Median price change</small><strong>${esc(money(r.median_change))}</strong><p>Largest |change| ${esc(money(r.largest_absolute_change))}</p></div><div class="stat-card"><small>Review required</small><strong>${r.errors+r.conflicts}</strong><p>${r.errors} errors · ${r.conflicts} conflicts</p></div></div><div class="table-scroll"><table><thead><tr><th>CASE</th><th>CURRENT</th><th>PROPOSED</th><th>CHANGE / RESULT</th></tr></thead><tbody>${r.rows.map(row=>row.error?`<tr><td>${row.case}</td><td colspan="3" class="error-text">${esc(row.error)}</td></tr>`:`<tr><td>${row.case}</td><td>${esc(money(row.current))}</td><td>${esc(money(row.proposed))}</td><td>${esc(money(row.delta))}${row.conflict?' <span class="badge red">Conflict</span>':''}${row.constraints.length?' <span class="badge amber">Limit applied</span>':''}</td></tr>`).join('')}</tbody></table></div><p class="muted-text" style="margin-top:14px">${esc(r.note)} Evaluation date: ${esc(r.evaluation_date)}.</p>${r.conflicts?'<label class="switch-row"><input type="checkbox" id="ackConflicts"><span>I have reviewed the flagged same-priority conflicts.</span></label>':''}<button id="activateBtn" class="button primary" ${r.can_activate?'':'disabled'}>Approve & activate this draft</button>`;
    $('activateBtn').onclick=()=>task(activate);
  }finally{busy(button,false,'Compare strategies');}
}
async function activate(){
  if(!state.key){$('authDialog').showModal();return;}
  if(!state.comparison)return;
  if(!confirm('Activate this tested candidate for future pricing requests? A version snapshot will be saved.'))return;
  const r=await api(`/drafts/${state.comparison.draft_id}/activate`,{method:'POST',body:{acknowledge_conflicts:!!$('ackConflicts')?.checked}});
  await loadDomain();toast(`Strategy activated as version ${r.version}.`);
}
async function generateRule(){
  if(!state.key){$('authDialog').showModal();return;}
  const button=$('copilotBtn');busy(button,true,'Generate a rule draft');
  try{
    const r=await api('/copilot',{method:'POST',body:{domain:state.config.domain,intent:$('intent').value}});
    $('copilotResult').textContent=r.explanation;
    if(r.rule){const candidate=JSON.parse($('candidateJson').value);candidate.rules.push(r.rule);setCandidate(candidate);toast('AI draft validated and added to the candidate. Review and compare it.');}
  }finally{busy(button,false,'Generate a rule draft');}
}
function stat(label,value,detail){return `<div class="stat-card"><small>${esc(label)}</small><strong>${esc(value)}</strong><p>${esc(detail)}</p></div>`;}
function trendChart(rows){
  if(!rows.length)return '<div class="empty-small">Calculate a few scenarios to build a decision trend.</div>';
  const max=Math.max(1,...rows.flatMap(r=>[r.price,r.base]))*1.12,w=630,h=205,p=38;
  const xy=(r,i,key)=>[p+(rows.length===1?.5:i/(rows.length-1))*(w-2*p),h-p-r[key]/max*(h-2*p)];
  const poly=key=>rows.map((r,i)=>xy(r,i,key).map(n=>n.toFixed(2)).join(',')).join(' ');
  let grid='';for(let i=0;i<4;i++){const y=h-p-i*(h-2*p)/3;grid+=`<line x1="${p}" x2="${w-p}" y1="${y}" y2="${y}" stroke="#e9eff0"/><text x="${p-7}" y="${y+3}" text-anchor="end" fill="#87979f" font-size="9">${Math.round(max*i/3)}</text>`;}
  return `<svg class="plot" viewBox="0 0 ${w} ${h}" role="img" aria-label="Final and base prices for recent decisions in chronological order">${grid}<polyline points="${poly('base')}" fill="none" stroke="#b7c5ca" stroke-width="1.5" stroke-dasharray="4 4"/><polyline points="${poly('price')}" fill="none" stroke="#168b7d" stroke-width="2.3"/>${rows.map((r,i)=>{const [x,y]=xy(r,i,'price');return `<circle cx="${x}" cy="${y}" r="3.5" fill="#168b7d"><title>${esc(shortDate(r.time)+' · '+money(r.price))}</title></circle>`;}).join('')}<text x="${p}" y="${h-7}" fill="#87979f" font-size="9">${esc(shortDate(rows[0].time))}</text><text x="${w-p}" y="${h-7}" text-anchor="end" fill="#87979f" font-size="9">${esc(shortDate(rows[rows.length-1].time))}</text></svg>`;
}
async function loadAnalytics(){
  if(!state.key){$('analyticsContent').innerHTML='<div class="panel empty-small">Unlock administration to view saved decision history and analytics. Public visitors can still calculate scenarios.</div>';return;}
  const domain=state.config.domain;
  const [a,recent]=await Promise.all([api('/analytics?domain='+domain),api('/decisions?domain='+domain+'&limit=20')]);
  const rate=a.window_count?(a.conflicts/a.window_count*100).toFixed(1):'0.0';
  $('analyticsContent').innerHTML=`<div class="stat-grid">${stat('Recorded decisions',a.total_decisions,`This industry · latest ${a.window_count} analysed`)}${stat('Average final price',money(a.average_price),'Within the analysed window')}${stat('Conflict rate',rate+'%',`${a.conflicts} of ${a.window_count} decisions`)}${stat('Price limits applied',a.constrained,'Decisions with at least one constraint')}</div><div class="two-column equal"><div class="panel"><div class="panel-head"><div><h2>Recent price decisions</h2><p>Chronological decision order · selected industry</p></div></div><div class="chart-legend"><span><i style="background:#168b7d"></i>Final price</span><span><i style="background:#b7c5ca"></i>Base price</span></div>${trendChart(a.trend)}</div><div class="panel"><div class="panel-head"><div><h2>Which rules fire most?</h2><p>Frequency in the latest ${a.window_count} decisions</p></div></div>${a.rule_frequency.length?a.rule_frequency.slice(0,10).map(f=>`<div class="frequency-row"><span>${esc(f.rule)}</span><div class="frequency-track"><span style="width:${f.count/Math.max(1,...a.rule_frequency.map(x=>x.count))*100}%"></span></div><b>${f.count}</b></div>`).join(''):'<div class="empty-small">No rules have fired yet.</div>'}<p class="muted-text">P95 processing time: ${a.p95_ms.toFixed(2)} ms. ${esc(a.latency_scope)}.</p></div></div><div class="panel"><div class="panel-head"><div><h2>Decision feed</h2><p>Open any record to inspect its context and replay the result.</p></div><button class="button quiet small" id="exportBtn">Export receipts</button></div><div class="table-scroll"><table><thead><tr><th>DECISION</th><th>FINAL PRICE</th><th>RULES</th><th>STATUS</th></tr></thead><tbody>${recent.entries.map(r=>`<tr><td><button class="link-button" data-decision="${r.decision_id}">${esc(r.decision_id.slice(0,12))} ↗</button><small>${esc(shortDate(r.created_at))}</small></td><td>${esc(money(r.final_price,r.currency))}</td><td>${r.fired_rules.length}</td><td><span class="badge ${r.conflict?'red':r.warnings.length?'amber':'green'}">${r.conflict?'Conflict':r.warnings.length?'Review':'Recorded'}</span></td></tr>`).join('')||'<tr><td colspan="4">No decisions recorded yet.</td></tr>'}</tbody></table></div></div>`;
  $('exportBtn').onclick=()=>task(async()=>{const res=await fetch('/studio-api/export?domain='+domain,{headers:{Authorization:'Bearer '+state.key}});if(!res.ok)throw new Error('Export failed.');download('monetize360_decisions.jsonl',await res.text(),'application/x-ndjson');});
}
async function loadHistory(){
  const r=await api(`/domains/${state.config.domain}/versions`);
  $('versionList').innerHTML=r.versions.map(v=>`<div class="version"><div><strong>Version ${v.version}</strong> ${v.matches_current?'<span class="badge green">Matches active</span>':''}<p>${esc(v.action)}</p><small>${esc(shortDate(v.timestamp))} · ${v.rule_count} rules</small></div>${v.matches_current?'':`<button class="button quiet small" data-restore="${v.version}">Restore</button>`}</div>`).join('')||'<div class="empty-small">The first strategy activation will save the baseline and the new version.</div>';
}
async function loadModel(){
  const r=await api('/ml/report');
  if(r.source==='external_adapter'){$('modelContent').innerHTML=`<div class="panel"><h2>Your model adapter is active</h2><p>${esc(r.note)}</p><p>Use your existing evaluation report. This console does not substitute demonstration metrics for your model.</p></div>`;return;}
  const t=r.test_metrics;
  $('modelContent').innerHTML=`<div class="model-note"><b>Transparent demonstration data.</b> ${esc(r.limitations)}</div><div class="stat-grid">${stat('Selected model',r.selected_model,'Lowest mean cross-validation MAE')}${stat('Held-out MAE',t.mae.toFixed(4),`${r.split.test} untouched test samples`)}${stat('Held-out RMSE',t.rmse.toFixed(4),'Demand index scale: 0–1')}${stat('Mean baseline MAE',t.mean_baseline_mae.toFixed(4),'Predicts the training-set mean')}</div><div class="panel"><div class="panel-head"><div><h2>Model selection evidence</h2><p>${esc(r.selection)}</p></div><span class="badge lavender">NUMPY ONLY</span></div><div class="table-scroll"><table><thead><tr><th>MODEL</th><th>CV MAE</th><th>FOLD STD.</th><th>CV RMSE</th></tr></thead><tbody>${r.candidates.map(c=>`<tr><td>${esc(c.model)} ${c.model===r.selected_model?'<span class="badge green">Selected</span>':''}</td><td>${c.cv_mae_mean.toFixed(4)}</td><td>${c.cv_mae_std.toFixed(4)}</td><td>${c.cv_rmse_mean.toFixed(4)}</td></tr>`).join('')}</tbody></table></div><p class="muted-text" style="margin-top:16px">Training: ${r.split.training} · anomaly calibration: ${r.split.anomaly_calibration} · test: ${r.split.test} · seed: ${r.random_seed} · model version: ${esc(r.model_version)}</p></div><div class="two-column equal"><div class="panel"><h2>What the model predicts</h2><p class="muted-text">${esc(r.target)}</p><h3>Input features</h3><p class="muted-text">${r.features.map(esc).join(' · ')}</p><p class="muted-text">The model supplies demand context. Your deterministic rules still calculate the price.</p></div><div class="panel"><h2>Anomaly gate</h2><p class="muted-text">Regularized Mahalanobis distance. ${esc(r.anomaly_threshold_method)}.</p><p class="muted-text">Threshold: ${r.anomaly_threshold.toFixed(3)}. ${esc(r.anomaly_limit)}.</p><p class="muted-text">Flagged predictions require reviewed inputs or an explicit manual scenario.</p></div></div>`;
}
function download(filename,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>selectPage(b.dataset.page));
$('domainSelect').onchange=()=>task(loadDomain);
$('priceForm').onsubmit=calculate;
$('resetScenario').onclick=renderFields;
$('useWeather').onchange=contextMode;$('useML').onchange=contextMode;
$('useRaw').onchange=()=>{if($('useRaw').checked)$('rawContext').value=JSON.stringify(readFields(),null,2);};
$('ruleForm').onsubmit=addRule;$('addCondition').onclick=addCondition;
$('resetCandidate').onclick=()=>setCandidate(state.config);
$('candidateJson').oninput=invalidateComparison;$('comparisonCases').oninput=invalidateComparison;
$('sampleCases').onclick=()=>task(loadCases);$('compareBtn').onclick=()=>task(compare);$('copilotBtn').onclick=()=>task(generateRule);
$('unlockBtn').onclick=()=>{if(state.key){state.key='';$('accessBadge').textContent='Viewer';$('unlockBtn').textContent='Unlock editing';toast('Administration locked.');if(state.page==='insights')task(loadAnalytics);}else $('authDialog').showModal();};
$('authForm').onsubmit=async event=>{event.preventDefault();const previous=state.key;state.key=$('adminKey').value.trim();try{await api('/admin/check');$('adminKey').value='';$('authError').textContent='';$('authDialog').close();$('accessBadge').textContent='Administrator';$('accessBadge').className='badge green';$('unlockBtn').textContent='Lock editing';toast('Administration unlocked.');if(state.page==='insights')await loadAnalytics();}catch(e){state.key=previous;$('authError').textContent=e.message;}};
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
$('importBtn').onclick=()=>state.key?$('importDialog').showModal():$('authDialog').showModal();
$('domainFile').onchange=()=>task(async()=>{const file=$('domainFile').files[0];if(file){if(file.size>500000)throw new Error('Domain file is too large.');$('importJson').value=await file.text();}});
$('caseFile').onchange=()=>task(async()=>{const file=$('caseFile').files[0];if(file){if(file.size>500000)throw new Error('Scenario file is too large.');const data=JSON.parse(await file.text());$('comparisonCases').value=JSON.stringify(Array.isArray(data)?data:data.contexts,null,2);$('caseSource').textContent='Uploaded: '+file.name;invalidateComparison();}});
$('confirmImport').onclick=()=>task(async()=>{const config=JSON.parse($('importJson').value);await api('/domains',{method:'POST',body:{config}});$('importDialog').close();await loadDomains(config.domain);toast('Domain imported. No engine or interface changes needed.');});
document.body.addEventListener('click',event=>{
  const remove=event.target.closest('[data-remove-rule]');if(remove)task(()=>{const candidate=JSON.parse($('candidateJson').value),id=state.config.rules[Number(remove.dataset.removeRule)].id;candidate.rules=candidate.rules.filter(r=>r.id!==id);setCandidate(candidate);toast('Removal added to the candidate. Compare before activating.');});
  const decision=event.target.closest('[data-decision]');if(decision)task(async()=>{const r=await api('/decisions/'+decision.dataset.decision);selectPage('simulator');renderDecision(r);window.scrollTo({top:0,behavior:'smooth'});});
  const restore=event.target.closest('[data-restore]');if(restore)task(async()=>{if(!state.key){$('authDialog').showModal();return;}if(!confirm('Restore this strategy as a new version?'))return;const r=await api(`/domains/${state.config.domain}/rollback/${restore.dataset.restore}`,{method:'POST'});await loadDomain();toast('Restored as version '+r.version);});
});
setInterval(()=>{if(state.page==='insights' && state.key && !document.hidden)task(loadAnalytics);},20000);
task(async()=>{
  state.health=await api('/health');$('connection').textContent='Engine connected';$('engineLabel').textContent='Engine '+state.health.engine_hash.slice(0,12);
  $('mlModeLabel').textContent=state.health.ml_mode==='external_adapter'?'Your configured demand model':'Portable NumPy model · synthetic training data';
  if(!state.health.copilot_configured){$('copilotResult').textContent='Mistral is optional. Add your actual MISTRAL_API_KEY to .env and restart to enable this card.';}
  await loadDomains();
});
