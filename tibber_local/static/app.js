/* Local dashboard: no external libraries, analytics, or credential persistence in JS. */
const $ = id => document.getElementById(id);
const fmt = (v, digits=2) => v == null ? '—' : new Intl.NumberFormat('en-GB', {maximumFractionDigits:digits, minimumFractionDigits:digits}).format(v);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
let initialized = false, busy = false, lastSignature = '', data, status, requestId = 0;
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Request failed');
  return value;
}
function error(e) { $('status').textContent=e.message; $('status').className='error'; }
async function action(path, body) { try { await request(path,body); await poll(); await load(); } catch(e) {error(e);} }
function plot(id, labels, series, {bars=false, digits=1}={}) {
  const width=700,height=260,p={l:64,r:16,t:12,b:40},w=width-p.l-p.r,h=height-p.t-p.b;
  const values=series.flatMap(s=>s.values).filter(v=>v!=null&&Number.isFinite(v));
  if (!values.length) {$(id).innerHTML='<p class="empty">No comparable data in this selection</p>';return;}
  let lo=Math.min(0,...values),hi=Math.max(0,...values); if(hi===lo)hi=lo+1;
  const extra=(hi-lo)*.12;hi+=extra;if(lo<0)lo-=extra;
  const x=i=>p.l+(i+.5)*w/labels.length,y=v=>p.t+(hi-v)/(hi-lo)*h;
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc($(id).parentElement.querySelector('h3').textContent)}">`;
  for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;svg+=`<line class="gridline" x1="${p.l}" y1="${y(v)}" x2="${width-p.r}" y2="${y(v)}"/><text x="${p.l-10}" y="${y(v)+4}" text-anchor="end">${fmt(v,digits)}</text>`;}
  series.forEach((s,j)=>{
    if(bars){s.values.forEach((v,i)=>{if(v==null)return;const bw=Math.min(22,w/labels.length/(series.length+1));const bx=x(i)+(j-series.length/2)*bw;svg+=`<rect x="${bx}" y="${Math.min(y(v),y(0))}" width="${bw*.88}" height="${Math.abs(y(v)-y(0))}" fill="${s.color}"><title>${esc(labels[i])} · ${esc(s.name)}: ${fmt(v)}</title></rect>`;});}
    else {let path='',open=false;s.values.forEach((v,i)=>{if(v==null){open=false;return;}path+=`${open?'L':'M'}${x(i)},${y(v)} `;open=true;});svg+=`<path class="series" stroke="${s.color}" d="${path}"/>`;s.values.forEach((v,i)=>{if(v!=null)svg+=`<circle cx="${x(i)}" cy="${y(v)}" r="${labels.length>50?2:3}" fill="${s.color}"><title>${esc(labels[i])} · ${esc(s.name)}: ${fmt(v,3)}</title></circle>`;});}
  });
  const step=Math.max(1,Math.ceil(labels.length/12));labels.forEach((label,i)=>{if(i%step===0)svg+=`<text x="${x(i)}" y="${height-12}" text-anchor="middle">${esc(label)}</text>`;});
  $(id).innerHTML=svg+'</svg>';
}
function table(id, headers, rows) {$(id).innerHTML=`<thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>`;}
function render() {
  const d=data,s=d.summary,c=d.currency;
  const cards=[['Consumption',fmt(s.kwh,1)+' kWh',`${s.known_consumption_hours} observed hours`],['Recorded API cost',fmt(s.api_cost)+' '+c,'Variable consumption cost; not an invoice'],['Hourly − unweighted benchmark',fmt(s.hourly_minus_mean)+' '+c,s.hourly_minus_mean==null?'Needs a complete price month':'Research benchmark; not the billed SLP tariff'],['Scenario coverage',fmt(s.comparable_hours,0)+' hours',`${s.matched_price_hours} hours matched to prices`]];
  $('cards').innerHTML=cards.map(([name,v,note])=>`<article class="card"><h3>${esc(name)}</h3><div class="value">${esc(v)}</div><p>${esc(note)}</p></article>`).join('');
  plot('cost-chart',d.monthly.map(m=>m.month.slice(2)),[{name:'Hourly scenario',color:'#397de0',values:d.monthly.map(m=>m.monthly_mean_cost==null?null:m.hourly_cost)},{name:'Unweighted benchmark',color:'#19a59d',values:d.monthly.map(m=>m.monthly_mean_cost)}],{bars:true});
  plot('daily-chart',d.daily.map(r=>r.day.slice(5)),[{name:'Consumption kWh',color:'#397de0',values:d.daily.map(r=>r.kwh)}]);
  table('monthly-table',['Month','Hours / full month','kWh',`API cost · ${c}`,`Hourly · ${c}`,`Unweighted benchmark · ${c}`,'Hourly − benchmark',`Known rate cost · ${c}`,'Price pattern'],d.monthly.map(m=>[m.month,`${m.hours} / ${m.expected_hours}`,fmt(m.kwh,1),fmt(m.api_cost),fmt(m.hourly_cost),fmt(m.monthly_mean_cost),fmt(m.hourly_minus_mean),fmt(m.custom_cost),`${m.applied_price_count} distinct API prices`]));
  const series=field=>[false,true].map((weekend,i)=>({name:weekend?'Weekend':'Weekday',color:i?'#19a59d':'#397de0',values:d.profiles.filter(p=>p.weekend===weekend).map(p=>p[field])}));
  plot('profile-chart',Array.from({length:24},(_,i)=>String(i).padStart(2,'0')),series('mean_kwh'),{digits:2});
  plot('price-chart',Array.from({length:24},(_,i)=>String(i).padStart(2,'0')),series('mean_price'),{digits:2});
  const ms=[...new Set(d.heatmap.map(r=>r.month))],width=1100,cell=38,row=25,left=90,height=ms.length*row+35;
  const max=Math.max(.001,...d.heatmap.map(r=>r.kwh??0));
  let svg=`<svg viewBox="0 0 ${width} ${Math.max(60,height)}" role="img" aria-label="Mean consumption by month and hour">`;
  for(let i=0;i<24;i++)svg+=`<text x="${left+i*cell+cell/2}" y="15" text-anchor="middle">${i}</text>`;
  ms.forEach((m,i)=>svg+=`<text x="78" y="${35+i*row}" text-anchor="end">${m}</text>`);
  d.heatmap.forEach(r=>{const t=(r.kwh??0)/max;const fill=r.kwh==null?'#edf1f7':`rgb(${Math.round(233-190*t)},${Math.round(243-122*t)},${Math.round(255-42*t)})`;const label=`${r.month}, ${r.hour}:00: ${fmt(r.kwh,3)} kWh, ${r.samples} observations`;svg+=`<rect class="focus-cell" tabindex="0" aria-label="${esc(label)}" x="${left+r.hour*cell}" y="${22+ms.indexOf(r.month)*row}" width="${cell-2}" height="${row-2}" rx="3" fill="${fill}"><title>${esc(label)}</title></rect>`;});
  $('heatmap').innerHTML=ms.length?svg+'</svg>':'<p class="empty">No history in this selection</p>';
  table('peak-table',['Local start (UTC offset)','kWh','Price / kWh'],d.peaks.map(r=>[r.start.replace('T',' '),fmt(r.kwh,3),fmt(r.price,4)]));
  const qa=[['Saved range',`${d.coverage.first??'—'} to ${d.coverage.last??'—'}`],['Timezone',d.timezone],['Saved hourly intervals',fmt(d.coverage.saved_hours,0)],['Missing intervals between records',d.coverage.gap_hours],['Selected matched hours',s.matched_price_hours],['Last API refresh',status.last_refresh??'Not refreshed'],['Max applied vs series price gap',fmt(s.max_price_rounding_difference,6)+' / kWh']];
  $('quality').innerHTML=qa.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('coverage').textContent=`${d.coverage.first??'No history'} – ${d.coverage.last??'—'} · ${fmt(d.coverage.saved_hours,0)} saved hours · ${d.timezone}`;
}
async function load(){try{
  const currentRequest=++requestId;
  const params=new URLSearchParams({year:$('year').value,month:$('month').value,daytype:$('daytype').value});
  const result=await request('/api/analysis?'+params);
  if(currentRequest!==requestId)return;
  data=result;
  if(!initialized&&data.years.length){$('year').innerHTML='<option value="all">All years</option>'+data.years.map(y=>`<option>${esc(y)}</option>`).join('');$('year').value=data.years.includes('2025')?'2025':data.years.at(-1);initialized=true;return load();}
  render();
}catch(e){error(e);}}
async function poll(){try{
  status=await request('/api/status');busy=status.running;
  $('mode').textContent=status.demo?'SYNTHETIC DEMO · no household data':'Private local history';
  $('status').textContent=status.error||status.message; $('status').className=status.error?'error':'';
  $('refresh').disabled=busy||status.demo; $('full-refresh').disabled=busy||status.demo;
  $('interval').value=String(status.refresh_hours);$('start').value=status.start;
  if(!status.configured&&!status.demo)$('setup').hidden=false;
  const signature=JSON.stringify([status.last_refresh,busy,status.error]);
  if(lastSignature&&signature!==lastSignature&&!busy)await load();lastSignature=signature;
}catch(e){error(e);}}
$('month').innerHTML+=[...months].map((m,i)=>`<option value="${String(i+1).padStart(2,'0')}">${m}</option>`).join('');
['year','month','daytype'].forEach(id=>$(id).addEventListener('change',load));
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b===button));
  ['history','patterns','quality'].forEach(p=>$(p+'-page').hidden=p!==button.dataset.page);
  const copy={history:['What does the timing of consumption cost?','Recorded API costs and transparent tariff scenarios'],patterns:['How does your household use electricity?','Historical patterns first; feasible load shifting comes next'],quality:['What is included in this comparison?','Coverage, update settings and analytical boundaries']}[button.dataset.page];$('page-title').textContent=copy[0];$('subtitle').textContent=copy[1];
}));
$('connection').addEventListener('click',()=>$('setup').hidden=!$('setup').hidden);
$('refresh').addEventListener('click',()=>action('/api/refresh',{}));
$('full-refresh').addEventListener('click',()=>action('/api/refresh',{full:true}));
$('interval').addEventListener('change',()=>action('/api/settings',{hours:Number($('interval').value)}));
$('connect-form').addEventListener('submit',async e=>{e.preventDefault();try{const body=$('token').value?{token:$('token').value}:{};$('token').value='';const result=await request('/api/connect',body);$('home').innerHTML=result.homes.map(h=>`<option value="${h.index}">${esc(h.label)} · ${esc(h.timezone)}</option>`).join('');$('home-form').hidden=false;$('status').textContent='Connected. Choose a home and history start date.';}catch(e){error(e);}});
$('home-form').addEventListener('submit',async e=>{e.preventDefault();await action('/api/setup',{home:Number($('home').value),start:$('start').value});if(!status?.error)$('setup').hidden=true;});
$('rate-form').addEventListener('submit',e=>{e.preventDefault();action('/api/rate',{month:$('rate-month').value,rate:$('rate').value});});
(async()=>{await poll();await load();setInterval(poll,3000);})();
