"""
routers/webapp.py — the embedded DRIP operator console (served at /app).

A zero-build single-file SPA served by the API itself and wired to the REAL
endpoints (no demo fallback): ABM signals + dedup ingest, buying-committee
coverage, journey orchestration + tick, sales engagement (replies / hot leads /
step A/B), cohort analytics, developer platform (API keys, webhooks), and PDPL
compliance (export / consent / erase). Complements the external Lovable UI
(which carries the CRM record/board/quote surfaces).
"""
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["webapp"])

_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DRIP — Operator Console</title>
<style>
:root{--bg:#0d1512;--panel:#13201b;--card:#182821;--line:#24382f;--text:#e6efe9;
--dim:#8fa89b;--green:#2f9e6e;--gold:#d4a941;--red:#c65454;--blue:#5b8dd6;
font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);min-height:100vh}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;background:var(--panel);
border-bottom:1px solid var(--line)}
header h1{font-size:17px}header h1 span{color:var(--gold)}
header .env{margin-left:auto;font-size:12px;color:var(--dim)}
nav{display:flex;gap:4px;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap}
nav button{background:none;border:1px solid transparent;color:var(--dim);padding:7px 14px;
border-radius:8px;cursor:pointer;font-size:13.5px}
nav button.on{background:var(--card);color:var(--text);border-color:var(--line)}
main{padding:22px;max-width:1180px;margin:0 auto}
.grid{display:grid;gap:14px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h3{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.kpi{font-size:26px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{color:var(--dim);text-align:left;font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line)}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11.5px}
.b-green{background:#1d3a2c;color:#7fd6a8}.b-gold{background:#3a321d;color:#e8c96f}
.b-red{background:#3a1d1d;color:#e89a9a}.b-blue{background:#1d2a3a;color:#9ec1ec}.b-dim{background:#20302a;color:var(--dim)}
input,select,textarea{background:var(--bg);border:1px solid var(--line);color:var(--text);
padding:8px 10px;border-radius:8px;font-size:13.5px;width:100%}
label{font-size:12px;color:var(--dim);display:block;margin:8px 0 4px}
button.act{background:var(--green);border:none;color:#fff;padding:8px 16px;border-radius:8px;
cursor:pointer;font-size:13.5px;margin-top:10px}
button.act.gold{background:var(--gold);color:#1c1608}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;
font-size:12px;overflow:auto;max-height:260px;margin-top:10px;color:#b9d0c4}
.bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden;margin:4px 0}
.bar i{display:block;height:100%;background:var(--green)}
.role{display:inline-block;margin:3px 6px 3px 0;padding:5px 12px;border-radius:8px;font-size:12.5px;border:1px dashed var(--line);color:var(--dim)}
.role.ok{border-style:solid;border-color:var(--green);color:#9fd9bd;background:#16281f}
.muted{color:var(--dim);font-size:12.5px}
h2{font-size:16px;margin-bottom:12px}
.tabpane{display:none}.tabpane.on{display:block}
</style></head>
<body>
<header><h1>◆ DRIP <span>Operator Console</span></h1>
<div class="env" id="env">connected to this API</div>
<button onclick="toggleRTL()" title="العربية / English" style="background:none;border:1px solid var(--line);color:var(--dim);padding:6px 10px;border-radius:8px;cursor:pointer">ع/EN</button>
<div id="authbox" style="display:flex;gap:6px;align-items:center">
 <input id="au_email" placeholder="email" style="width:150px;padding:6px 8px">
 <input id="au_pw" type="password" placeholder="password" style="width:120px;padding:6px 8px">
 <button class="act" style="margin:0;padding:6px 12px" onclick="doLogin()">Sign in</button>
 <span id="au_state" class="muted"></span>
</div></header>
<nav id="nav"></nav>
<main id="main"></main>
<script>
const TABS=["Home","Search","Signals","Committee","Journeys","Engagement","Analytics","Email","Admin","Compliance","Parity"];
const nav=document.getElementById('nav'),main=document.getElementById('main');
const H=(s)=>{const d=document.createElement('div');d.innerHTML=s;return d};
/* Arabic/RTL layout toggle (persisted). Full i18n strings come with the
   dedicated UI build; layout + direction support lands now. */
function toggleRTL(){
  const rtl=document.documentElement.dir!=='rtl';
  document.documentElement.dir=rtl?'rtl':'ltr';
  document.documentElement.lang=rtl?'ar':'en';
  localStorage.setItem('drip_rtl',rtl?'1':'0');
}
if(localStorage.getItem('drip_rtl')==='1'){document.documentElement.dir='rtl';document.documentElement.lang='ar';}

let TOKEN=localStorage.getItem('drip_token')||null;
async function api(method,path,body){
  const h={'Content-Type':'application/json'};
  if(TOKEN)h['Authorization']='Bearer '+TOKEN;
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  let j=null;try{j=await r.json()}catch(e){}
  if(r.status===401)document.getElementById('au_state').textContent='sign-in required';
  return {ok:r.ok,status:r.status,data:j};
}
async function doLogin(){
  const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:document.getElementById('au_email').value,
                         password:document.getElementById('au_pw').value})});
  const j=await r.json().catch(()=>({}));
  if(r.ok&&j.access_token){TOKEN=j.access_token;localStorage.setItem('drip_token',TOKEN);
    document.getElementById('au_state').textContent='✓ '+(j.role||'signed in');loadHome&&loadHome();}
  else document.getElementById('au_state').textContent=j.detail||'login failed';
}
if(TOKEN)document.getElementById('au_state').textContent='✓ token saved';
function show(name){
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.textContent===name));
  document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('on',p.id==='tab'+name));
  loaders[name]&&loaders[name]();
}
TABS.forEach(t=>{const b=document.createElement('button');b.textContent=t;b.onclick=()=>show(t);nav.appendChild(b);
  const p=document.createElement('div');p.className='tabpane';p.id='tab'+t;main.appendChild(p);});

/* ── Home (executive dashboard) ── */
document.getElementById('tabHome').innerHTML=`
<h2>Executive Dashboard</h2>
<div class="grid g3" id="hm_kpis"></div>
<div class="grid g2" style="margin-top:14px">
 <div class="card"><h3>Hot leads</h3><div id="hm_hot" class="muted">—</div></div>
 <div class="card"><h3>Email performance (90d)</h3><div id="hm_email" class="muted">—</div></div>
</div>`;
async function loadHome(){
  const r=await api('GET','/dashboard/executive');
  if(!r.ok){document.getElementById('hm_kpis').innerHTML='<div class="card">error</div>';return}
  const d=r.data;
  const kpi=(t,v,s)=>'<div class="card"><h3>'+t+'</h3><div class="kpi">'+v+'</div><div class="muted">'+(s||'')+'</div></div>';
  document.getElementById('hm_kpis').innerHTML=
    kpi('Pipeline',d.pipeline_sar,d.open_deals+' open deals · weighted '+d.weighted_sar)+
    kpi('Accounts',d.accounts,d.contacts.toLocaleString()+' contacts')+
    kpi('Signals this week',d.signals_this_week,'')+
    kpi('Active journeys',d.active_journey_enrollments,'enrollments in flight')+
    kpi('Open tasks',d.tasks_open,'')+
    kpi('Suppressions',d.suppressions,'send-safe list');
  document.getElementById('hm_hot').innerHTML=d.hot_leads.length?
    d.hot_leads.map(h=>'<div>'+h.person_id.slice(0,8)+' — <span class="badge b-gold">'+h.score+'</span></div>').join(''):
    'no engagement rows yet';
  document.getElementById('hm_email').innerHTML=
    'sends: <b>'+d.email.sends+'</b> · open rate: <b>'+d.email.open_rate+'%</b> · click rate: <b>'+d.email.click_rate+'%</b>';
}

/* ── Search (global) ── */
document.getElementById('tabSearch').innerHTML=`
<h2>Global Search</h2>
<div class="card"><input id="gs_q" placeholder="Search companies, contacts, deals, campaigns, signals, tasks, quotes, journeys, workflows, api keys…"
 onkeydown="if(event.key==='Enter')doSearch()">
 <button class="act" onclick="doSearch()">Search everything</button>
 <div id="gs_out" style="margin-top:14px" class="muted">—</div></div>`;
async function doSearch(){
  const r=await api('GET','/search?q='+encodeURIComponent(v('gs_q')));
  if(!r.ok){document.getElementById('gs_out').textContent='error';return}
  const res=r.data.results, kinds=Object.keys(res);
  document.getElementById('gs_out').innerHTML=kinds.length?
   kinds.map(k=>'<h3 style="margin:12px 0 6px;color:var(--gold);font-size:12px;text-transform:uppercase">'+k+'</h3>'+
     res[k].map(h=>'<div>'+h.label+(h.sub?' <span class="muted">· '+h.sub+'</span>':'')+'</div>').join('')).join(''):
   'no matches for "'+r.data.query+'"';
}

/* ── Email analytics ── */
document.getElementById('tabEmail').innerHTML=`
<h2>Email Analytics</h2>
<div class="grid g3" id="em_kpis"></div>
<div class="card" style="margin-top:14px"><h3>Per-campaign comparison</h3><div id="em_tbl" class="muted">—</div></div>
<div class="card" style="margin-top:14px"><h3>Google Analytics 4</h3><div id="em_ga4" class="muted">—</div></div>`;
async function loadEmail(){
  const r=await api('GET','/analytics/email');
  if(r.ok){const d=r.data,t=d.totals,ra=d.rates;
   const kpi=(a,b,c)=>'<div class="card"><h3>'+a+'</h3><div class="kpi">'+b+'</div><div class="muted">'+(c||'')+'</div></div>';
   document.getElementById('em_kpis').innerHTML=
    kpi('Sent',t.sent,'delivered '+t.delivered+' ('+ra.delivery_rate+'%)')+
    kpi('Open rate',ra.open_rate+'%',t.unique_opens+' unique / '+t.opens+' total')+
    kpi('Click rate',ra.click_rate+'%','CTOR '+ra.ctor+'% · CTR '+ra.ctr+'%')+
    kpi('Replies',t.replies,'')+
    kpi('Bounces',t.bounces,ra.bounce_rate+'%')+
    kpi('Unsubs',t.unsubscribes,ra.unsubscribe_rate+'%');
   document.getElementById('em_tbl').innerHTML=d.per_campaign.length?
    '<table><tr><th>Campaign</th><th>Sent</th><th>Opens</th><th>Clicks</th><th>Open %</th><th>Click %</th></tr>'+
    d.per_campaign.map(c=>'<tr><td>'+c.campaign+'</td><td>'+c.sent+'</td><td>'+c.unique_opens+'</td><td>'+c.unique_clicks+'</td><td>'+c.open_rate+'</td><td>'+c.click_rate+'</td></tr>').join('')+'</table>':
    'no campaign sends in window';}
  const g=await api('GET','/analytics/ga4/status');
  if(g.ok){document.getElementById('em_ga4').innerHTML=g.data.configured?
    '<span class="badge b-green">live</span> '+g.data.measurement_id:
    '<span class="badge b-dim">dry-run</span> '+g.data.how_to_enable;}
}

/* ── Parity (capability registry) ── */
document.getElementById('tabParity').innerHTML=`
<h2>Feature Parity Dashboard</h2>
<div class="grid g2">
 <div class="card"><h3>Competitor parity (avg %)</h3><div id="pa_comp">—</div></div>
 <div class="card"><h3>Platform completion</h3><div id="pa_sum">—</div></div>
</div>
<div class="card" style="margin-top:14px"><h3>Top gaps (planned / blocked-external)</h3><div id="pa_gaps">—</div></div>
<div class="card" style="margin-top:14px"><h3>Module completion</h3><div id="pa_mod">—</div></div>`;
async function loadParity(){
  const r=await api('GET','/platform/parity');
  if(!r.ok)return;
  const d=r.data;
  document.getElementById('pa_comp').innerHTML=Object.entries(d.competitor_parity)
   .map(([k,v])=>'<div style="margin:5px 0">'+k+' <span class="muted">'+v+'%</span><div class="bar"><i style="width:'+v+'%"></i></div></div>').join('');
  document.getElementById('pa_sum').innerHTML='<div class="kpi">'+d.summary.completion_pct+'%</div>'+
   '<div class="muted">'+d.summary.total_capabilities+' capabilities · '+
   JSON.stringify(d.summary.by_status).replace(/[{}"]/g,'').replaceAll(',',' · ')+'</div>';
  document.getElementById('pa_gaps').innerHTML='<table><tr><th>Module</th><th>Feature</th><th>Status</th><th>Sprint</th></tr>'+
   d.top_gaps.map(g=>'<tr><td>'+g.module+'</td><td>'+g.feature+'</td><td><span class="badge '+(g.status==='blocked-external'?'b-red':'b-dim')+'">'+g.status+'</span></td><td>'+g.sprint+'</td></tr>').join('')+'</table>';
  document.getElementById('pa_mod').innerHTML=Object.entries(d.modules)
   .map(([k,m])=>'<div style="margin:5px 0">'+k+' <span class="muted">'+m.complete+'/'+m.features+'</span><div class="bar"><i style="width:'+m.completion_pct+'%"></i></div></div>').join('');
}

/* ── Signals ── */
document.getElementById('tabSignals').innerHTML=`
<h2>Signal Intelligence</h2>
<div class="grid g2">
 <div class="card"><h3>Ingest signal (deduped)</h3>
  <label>Org ID</label><input id="sg_org" placeholder="org uuid">
  <label>Type</label><select id="sg_type"><option>tender</option><option>regulatory</option><option>news</option><option>hiring</option></select>
  <label>Source</label><input id="sg_src" value="SAMA">
  <label>Title</label><input id="sg_title" placeholder="New core-banking RFP">
  <button class="act" onclick="ingestSignal()">Ingest</button>
  <pre id="sg_out">—</pre></div>
 <div class="card"><h3>Score account</h3>
  <label>Org ID</label><input id="sc_org" placeholder="org uuid">
  <button class="act gold" onclick="scoreAccount()">Score</button>
  <pre id="sc_out">—</pre></div>
</div>`;
async function ingestSignal(){
  const r=await api('POST','/abm/signals/ingest',{org_id:v('sg_org'),signal_type:v('sg_type'),
    source:v('sg_src'),title:v('sg_title')});
  out('sg_out',r);}
async function scoreAccount(){out('sc_out',await api('POST','/abm/accounts/'+v('sc_org')+'/score'));}

/* ── Committee ── */
document.getElementById('tabCommittee').innerHTML=`
<h2>Buying Committee</h2>
<div class="grid g2">
 <div class="card"><h3>Infer committee for org</h3>
  <label>Org ID</label><input id="cm_org" placeholder="org uuid">
  <button class="act" onclick="inferCm()">Infer roles</button><pre id="cm_out">—</pre></div>
 <div class="card"><h3>Coverage</h3>
  <div id="cm_cov"><span class="muted">Run coverage after inferring.</span></div>
  <button class="act gold" onclick="covCm()">Check coverage</button></div>
</div>`;
async function inferCm(){out('cm_out',await api('POST','/abm/committee/'+v('cm_org')+'/infer'));}
async function covCm(){
  const r=await api('GET','/abm/committee/'+v('cm_org')+'/coverage');
  if(!r.ok){document.getElementById('cm_cov').innerHTML='<span class="badge b-red">'+r.status+'</span>';return}
  const d=r.data,roles=["economic_buyer","executive_sponsor","champion","technical_buyer","user"];
  document.getElementById('cm_cov').innerHTML=
   '<div class="kpi">'+d.coverage_pct+'%</div><div class="bar"><i style="width:'+d.coverage_pct+'%"></i></div>'+
   roles.map(x=>'<span class="role '+(d.roles_covered.includes(x)?'ok':'')+'">'+x.replace('_',' ')+'</span>').join('')+
   (d.single_threaded?'<div style="margin-top:8px"><span class="badge b-red">single-threaded</span></div>':'')+
   '<div class="muted" style="margin-top:6px">'+d.members+' members · '+d.engaged_members+' engaged</div>';}

/* ── Journeys ── */
document.getElementById('tabJourneys').innerHTML=`
<h2>Marketing Journeys</h2>
<div class="grid g2">
 <div class="card"><h3>Create demo journey (send → wait → branch)</h3>
  <label>Name</label><input id="jn_name" value="Onboarding KSA">
  <button class="act" onclick="mkJourney()">Create</button>
  <label>Enroll person id</label><input id="jn_person" placeholder="person uuid or any id">
  <button class="act" onclick="enroll()">Enroll</button><pre id="jn_out">—</pre></div>
 <div class="card"><h3>Runner</h3>
  <button class="act gold" onclick="tick()">Run tick (advance due)</button>
  <pre id="jn_tick">—</pre>
  <label>Journey id → enrollments</label><input id="jn_id2">
  <button class="act" onclick="enrs()">List enrollments</button><pre id="jn_enr">—</pre></div>
</div>`;
let lastJourney=null;
async function mkJourney(){
  const nodes=[{id:"n1",type:"send",content:"welcome",next:"n2"},
   {id:"n2",type:"wait",hours:24,next:"n3"},
   {id:"n3",type:"branch",on:"opened",yes:"n4",no:"n5"},
   {id:"n4",type:"send",content:"thanks",next:"n6"},
   {id:"n5",type:"send",content:"nudge",next:"n6"},{id:"n6",type:"exit"}];
  const r=await api('POST','/mkt/journeys',{name:v('jn_name'),nodes});
  if(r.ok){lastJourney=r.data.id;document.getElementById('jn_id2').value=r.data.id}
  out('jn_out',r);}
async function enroll(){out('jn_out',await api('POST','/mkt/journeys/'+lastJourney+'/enroll',{person_id:v('jn_person')||'demo-person'}));}
async function tick(){out('jn_tick',await api('POST','/mkt/journeys/tick'));}
async function enrs(){out('jn_enr',await api('GET','/mkt/journeys/'+v('jn_id2')+'/enrollments'));}

/* ── Engagement ── */
document.getElementById('tabEngagement').innerHTML=`
<h2>Sales Engagement</h2>
<div class="grid g2">
 <div class="card"><h3>Handle reply (sentiment → action)</h3>
  <label>Person ID</label><input id="en_pid">
  <label>Reply text</label><textarea id="en_txt" rows="2">Interested, let's schedule a demo</textarea>
  <button class="act" onclick="reply()">Process reply</button><pre id="en_out">—</pre></div>
 <div class="card"><h3>Hot leads</h3>
  <button class="act gold" onclick="hot()">Refresh</button><div id="en_hot"></div></div>
</div>
<div class="card" style="margin-top:14px"><h3>Step A/B</h3>
 <label>Step id</label><input id="ab_step" value="step-1">
 <button class="act" onclick="abReg()">Register A/B variants</button>
 <button class="act gold" onclick="abPick()">Pick variant</button>
 <pre id="ab_out">—</pre></div>`;
async function reply(){out('en_out',await api('POST','/sales/replies',{person_id:v('en_pid'),text:v('en_txt')}));}
async function hot(){
  const r=await api('GET','/sales/hot-leads');
  document.getElementById('en_hot').innerHTML=!r.ok?'err':(r.data.length?'<table><tr><th>Name</th><th>Score</th><th>O/C/R</th></tr>'+
   r.data.map(l=>'<tr><td>'+(l.name||l.person_id)+'</td><td><span class="badge b-gold">'+l.engagement_score+'</span></td><td>'+l.opens+'/'+l.clicks+'/'+l.replies+'</td></tr>').join('')+'</table>':'<span class="muted">no engagement rows yet</span>');}
async function abReg(){out('ab_out',await api('POST','/sales/steps/'+v('ab_step')+'/variants',{variants:[{key:"A",label:"short"},{key:"B",label:"long"}]}));}
async function abPick(){out('ab_out',await api('GET','/sales/steps/'+v('ab_step')+'/pick'));}

/* ── Analytics ── */
document.getElementById('tabAnalytics').innerHTML=`
<h2>Analytics</h2>
<div class="grid g2">
 <div class="card"><h3>Time series</h3>
  <label>Event type</label><input id="an_ev" value="signup">
  <button class="act" onclick="ts()">Query</button><pre id="an_ts">—</pre></div>
 <div class="card"><h3>Cohort retention</h3>
  <label>Cohort event</label><input id="an_c" value="signup">
  <label>Return event</label><input id="an_r" value="active">
  <button class="act gold" onclick="coh()">Compute</button><pre id="an_coh">—</pre></div>
</div>`;
async function ts(){out('an_ts',await api('GET','/analytics/timeseries?event_type='+v('an_ev')+'&since_days=28&bucket_days=7'));}
async function coh(){out('an_coh',await api('GET','/analytics/cohort-retention?cohort_event='+v('an_c')+'&return_event='+v('an_r')));}

/* ── Admin ── */
document.getElementById('tabAdmin').innerHTML=`
<h2>Developer Platform</h2>
<div class="grid g2">
 <div class="card"><h3>API keys</h3>
  <label>Name</label><input id="ak_name" value="integration key">
  <button class="act" onclick="mkKey()">Create (shown once)</button>
  <button class="act gold" onclick="lsKeys()">List</button><pre id="ak_out">—</pre></div>
 <div class="card"><h3>Webhook subscriptions</h3>
  <label>URL</label><input id="wh_url" value="https://example.invalid/hook">
  <label>Event types (csv, blank = all)</label><input id="wh_ev" value="deal.won">
  <button class="act" onclick="mkSub()">Subscribe</button><pre id="wh_out">—</pre></div>
</div>`;
async function mkKey(){out('ak_out',await api('POST','/dev/api-keys',{name:v('ak_name'),scopes:["crm.read"]}));}
async function lsKeys(){out('ak_out',await api('GET','/dev/api-keys'));}
async function mkSub(){
  const ev=v('wh_ev').trim();out('wh_out',await api('POST','/dev/webhooks',{url:v('wh_url'),event_types:ev?ev.split(','):[]}));}

/* ── Compliance ── */
document.getElementById('tabCompliance').innerHTML=`
<h2>PDPL Compliance</h2>
<div class="grid g3">
 <div class="card"><h3>Export subject</h3><label>Person ID</label><input id="cp_e">
  <button class="act" onclick="cpExp()">Export</button><pre id="cp_eo">—</pre></div>
 <div class="card"><h3>Consent</h3><label>Person ID</label><input id="cp_c">
  <select id="cp_cs"><option>granted</option><option>withdrawn</option></select>
  <button class="act gold" onclick="cpCon()">Set</button><pre id="cp_co">—</pre></div>
 <div class="card"><h3>Erase subject</h3><label>Person ID</label><input id="cp_d">
  <button class="act" style="background:var(--red)" onclick="cpDel()">Erase (PDPL)</button><pre id="cp_do">—</pre></div>
</div>`;
async function cpExp(){out('cp_eo',await api('GET','/compliance/subjects/'+v('cp_e')+'/export'));}
async function cpCon(){out('cp_co',await api('POST','/compliance/subjects/'+v('cp_c')+'/consent',{status:v('cp_cs')}));}
async function cpDel(){out('cp_do',await api('POST','/compliance/subjects/'+v('cp_d')+'/erase'));}

function v(id){return document.getElementById(id).value}
function out(id,r){document.getElementById(id).textContent=JSON.stringify(r.data??('HTTP '+r.status),null,1)}
const loaders={Home:loadHome,Engagement:hot,Email:loadEmail,Parity:loadParity};
show('Home');
</script></body></html>"""


@router.get("/legacy", response_class=HTMLResponse, include_in_schema=False)
def operator_console():
    """Transition alias: the pre-OS operator console (superseded by DRIP OS at /)."""
    return HTMLResponse(_PAGE)


_PORTAL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DRIP — Platform Home</title>
<style>
:root{--bg:#0d1512;--card:#182821;--line:#24382f;--text:#e6efe9;--dim:#8fa89b;
--green:#2f9e6e;--gold:#d4a941;font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);min-height:100vh;display:flex;
flex-direction:column;align-items:center;padding:48px 20px}
h1{font-size:30px;margin-bottom:6px}h1 span{color:var(--gold)}
p.sub{color:var(--dim);margin-bottom:36px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
gap:16px;max-width:900px;width:100%}
a.card{display:block;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:22px;text-decoration:none;color:var(--text);
transition:border-color .15s}
a.card:hover{border-color:var(--green)}
a.card .ico{font-size:26px}a.card h3{margin:10px 0 6px;font-size:16px}
a.card p{color:var(--dim);font-size:13px;line-height:1.45}
.tag{display:inline-block;margin-top:10px;font-size:11px;padding:2px 9px;
border-radius:99px;background:#1d3a2c;color:#7fd6a8}
.tag.ext{background:#3a321d;color:#e8c96f}
footer{margin-top:36px;color:var(--dim);font-size:12.5px}
</style></head><body>
<h1>◆ DRIP <span>Platform</span></h1>
<p class="sub">Decimal Technologies · ABM operating system for KSA banking</p>
<div class="grid">
<a class="card" href="/app"><div class="ico">🎛️</div><h3>Operator Console</h3>
<p>Signals, buying committees, journeys, sales engagement, analytics, API keys, PDPL compliance — live on your Postgres data.</p>
<span class="tag">this server</span></a>
<a class="card" href="http://127.0.0.1:5050" target="_blank"><div class="ico">📇</div><h3>BD Contact Dashboard</h3>
<p>Your 8,000+ bank contacts: tiers, outreach tracking, flow maps, per-bank pages, Excel import/export.</p>
<span class="tag">this machine · port 5050</span></a>
<a class="card" href="https://drip-saudi-abm.lovable.app" target="_blank"><div class="ico">📊</div><h3>CRM Workspace</h3>
<p>Accounts, contacts, deal kanban, SAR quotes (CPQ) — the polished cloud UI. Demo data until pointed at this API.</p>
<span class="tag ext">cloud · lovable.app</span></a>
<a class="card" href="/docs" target="_blank"><div class="ico">🧩</div><h3>API Reference</h3>
<p>Every endpoint across all 26 routers — CRM, marketing, ABM, workflow, analytics, developer platform, compliance.</p>
<span class="tag">this server</span></a>
<a class="card" href="/health/ready" target="_blank"><div class="ico">💚</div><h3>Health</h3>
<p>Liveness/readiness probes and Prometheus metrics for monitoring.</p>
<span class="tag">this server</span></a>
</div>
<footer>Email transport is dry-run (send-safe). C-suite contacts always require human review.</footer>
</body></html>"""


@router.get("/legacy-portal", response_class=HTMLResponse, include_in_schema=False)
def portal():
    """Transition alias: the pre-OS launcher (superseded by DRIP OS at /)."""
    return HTMLResponse(_PORTAL)
