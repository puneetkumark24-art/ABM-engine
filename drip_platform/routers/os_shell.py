"""
routers/os_shell.py — DRIP OS: the single application (HubSpot-style shell).

Replaces the launcher portal + operator console with ONE hash-routed SPA served
at "/": persistent sidebar (full IA), top bar (global search / ⌘K command
palette, notifications, profile/login), shared account context that follows the
user across every module, and 20+ screens bound to the real API. No external
launches, no other ports, no other origins. `/app` redirects here; the old
console stays at `/legacy` during transition.
"""
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["os"])

_OS = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DRIP OS</title>
<style>
:root{--bg:#0d1512;--panel:#111c17;--card:#182821;--line:#24382f;--text:#e6efe9;
--dim:#8fa89b;--green:#2f9e6e;--gold:#d4a941;--red:#c65454;--blue:#5b8dd6;
font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);height:100vh;display:flex;overflow:hidden}
/* ── sidebar ── */
#side{width:218px;min-width:218px;background:var(--panel);border-inline-end:1px solid var(--line);
display:flex;flex-direction:column;overflow-y:auto}
#side .logo{padding:16px 18px;font-weight:700;font-size:16px;border-bottom:1px solid var(--line);cursor:pointer}
#side .logo:hover{background:var(--card)}
#side .logo span{color:var(--gold)}
#side .grp{padding:14px 18px 5px;font-size:13.5px;font-weight:700;letter-spacing:.05em;color:var(--gold);text-transform:uppercase;border-top:1px solid var(--line);margin-top:4px}
#side a{display:block;padding:7px 18px;color:var(--dim);text-decoration:none;font-size:13.5px;border-inline-start:2px solid transparent}
#side a.on{color:var(--text);background:var(--card);border-inline-start-color:var(--gold)}
#side a:hover{color:var(--text)}
/* ── main ── */
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#top{display:flex;align-items:center;gap:10px;padding:10px 18px;background:var(--panel);
border-bottom:1px solid var(--line)}
#gs{flex:1;max-width:520px;background:var(--bg);border:1px solid var(--line);color:var(--text);
padding:8px 12px;border-radius:9px;font-size:13.5px}
#top button{background:none;border:1px solid var(--line);color:var(--dim);padding:7px 11px;
border-radius:8px;cursor:pointer;font-size:13px;position:relative}
#notifdot{position:absolute;top:4px;right:5px;width:7px;height:7px;border-radius:99px;background:var(--red);display:none}
#ctxbar{display:none;align-items:center;gap:10px;padding:7px 18px;background:#16281f;
border-bottom:1px solid var(--line);font-size:13px}
#ctxbar b{color:var(--gold)}
#ctxbar button{background:none;border:none;color:var(--dim);cursor:pointer}
#screen{flex:1;overflow-y:auto;padding:22px}
h2{font-size:17px;margin-bottom:4px} .sub{color:var(--dim);font-size:13px;margin-bottom:16px}
.grid{display:grid;gap:14px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0}
.card h3{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.kpi{font-size:24px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);text-align:start;font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line)}
tr.click{cursor:pointer} tr.click:hover td{background:#1d2f26}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px}
.b-green{background:#1d3a2c;color:#7fd6a8}.b-gold{background:#3a321d;color:#e8c96f}
.b-red{background:#3a1d1d;color:#e89a9a}.b-dim{background:#20302a;color:var(--dim)}.b-blue{background:#1d2a3a;color:#9ec1ec}
input,select,textarea{background:var(--bg);border:1px solid var(--line);color:var(--text);
padding:8px 10px;border-radius:8px;font-size:13px;width:100%}
label{font-size:11.5px;color:var(--dim);display:block;margin:8px 0 4px}
button.act{background:var(--green);border:none;color:#fff;padding:8px 15px;border-radius:8px;cursor:pointer;font-size:13px;margin-top:10px}
button.act.gold{background:var(--gold);color:#1c1608}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:11.5px;overflow:auto;max-height:240px;margin-top:8px;color:#b9d0c4}
.tabs{display:flex;gap:4px;margin:14px 0;flex-wrap:wrap}
.tabs button{background:none;border:1px solid var(--line);color:var(--dim);padding:6px 13px;border-radius:8px;cursor:pointer;font-size:12.5px}
.tabs button.on{background:var(--card);color:var(--text);border-color:var(--gold)}
.bar{height:9px;background:var(--line);border-radius:6px;overflow:hidden;margin:4px 0}
.bar i{display:block;height:100%;background:var(--green)}
.muted{color:var(--dim);font-size:12.5px}
.planned{border:1px dashed var(--line);border-radius:12px;padding:22px;color:var(--dim);font-size:13.5px}
/* palette + notif overlays */
.overlay{position:fixed;inset:0;background:rgba(6,10,8,.72);display:none;z-index:50;justify-content:center;align-items:flex-start;padding-top:9vh}
.overlay.on{display:flex}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;width:min(620px,92vw);max-height:70vh;overflow:auto;padding:14px}
.hit{padding:8px 10px;border-radius:8px;cursor:pointer;font-size:13.5px}
.hit:hover{background:var(--card)} .hit .k{color:var(--gold);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;margin-inline-end:8px}
</style></head><body>
<nav id="side"><div class="logo" onclick="nav('dashboard')" title="Home">◆ DRIP <span>OS</span> <span style="font-size:11px;color:var(--dim)">⌂ home</span></div><div id="navlinks"></div></nav>
<div id="main">
 <div id="top">
  <input id="gs" placeholder="Search everything…  (Ctrl+K)" onfocus="openPalette()" readonly>
  <button onclick="openNotifs()" title="Notifications">🔔<span id="notifdot"></span></button>
  <button onclick="toggleRTL()" title="العربية / English">ع/EN</button>
  <button id="who" onclick="nav('settings')">Sign in</button>
 </div>
 <div id="ctxbar">Working on <b id="ctxname"></b>
  <button onclick="nav('accounts/'+S.account.id)">open 360°</button>
  <button onclick="clearAccount()">✕ clear</button></div>
 <div id="screen"></div>
</div>
<div class="overlay" id="pal"><div class="panel">
 <input id="palq" placeholder="Search accounts, contacts, deals, signals, quotes, journeys…" oninput="palSearch()">
 <div id="palres" style="margin-top:8px"></div></div></div>
<div class="overlay" id="notifs"><div class="panel"><h3 style="color:var(--dim);font-size:12px;margin-bottom:8px">NOTIFICATIONS</h3><div id="notifbody">—</div></div></div>
<script>
/* ═══════════ shared state ═══════════ */
const S={token:localStorage.getItem('drip_token')||null,
         account:JSON.parse(localStorage.getItem('drip_account')||'null')};
function setAccount(id,name){S.account={id,name};localStorage.setItem('drip_account',JSON.stringify(S.account));ctx();}
function clearAccount(){S.account=null;localStorage.removeItem('drip_account');ctx();route();}
function ctx(){
 if(S.account)document.getElementById('ctxname').textContent=S.account.name;
 // visibility is decided by route() (account pages only) — just refresh the name here
 const h=(location.hash||'#/dashboard').slice(2).split('/');
 const onAccount=(h[0]==='accounts'&&h[1])||h[0]==='committee';
 document.getElementById('ctxbar').style.display=(onAccount&&S.account)?'flex':'none';}
async function api(method,path,body){
  const h={'Content-Type':'application/json'};if(S.token)h['Authorization']='Bearer '+S.token;
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  let j=null;try{j=await r.json()}catch(e){}
  if(r.status===401)document.getElementById('who').textContent='Sign in required';
  return {ok:r.ok,status:r.status,data:j};}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toggleRTL(){const r=document.documentElement.dir!=='rtl';
 document.documentElement.dir=r?'rtl':'ltr';document.documentElement.lang=r?'ar':'en';
 localStorage.setItem('drip_rtl',r?'1':'0');}
if(localStorage.getItem('drip_rtl')==='1'){document.documentElement.dir='rtl';document.documentElement.lang='ar';}

/* ═══════════ navigation ═══════════ */
const NAV=[["Home",[["dashboard","Dashboard"]]],
["Intelligence",[["accounts","Accounts"],["contacts","Contacts"],["vendors","Vendors"],["connectors","Connectors"],["initiatives","Initiatives"],["bd","BD Outreach"],["signals","Signals"],["committee","Buying Committee"]]],
["Marketing",[["campaigns","Campaigns"],["journeys","Journeys"],["segments","Segments"],["email","Email Analytics"]]],
["Sales",[["pipeline","Pipeline"],["meetings","Meetings"],["tasks","Tasks"],["sequences","Sequences"]]],
["CRM",[["quotes","Quotes & Products"],["objects","Custom Objects"]]],
["Automation",[["workflow","Workflow"]]],
["AI Center",[["ai","Prompts & Calls"],["agents","Agents"]]],
["Analytics",[["reports","Reports"],["analytics","Cohorts & Trends"],["parity","Feature Parity"]]],
["Admin",[["developer","Developer"],["compliance","Compliance"],["health","Health"],["settings","Settings"]]]];
function buildNav(){const el=document.getElementById('navlinks');
 el.innerHTML=NAV.map(([g,items])=>'<div class="grp">'+g+'</div>'+
  items.map(([r,l])=>`<a href="#/${r}" data-r="${r}">${l}</a>`).join('')).join('');}
function nav(r){location.hash='#/'+r;}
function route(){const h=(location.hash||'#/dashboard').slice(2);const [name,id]=h.split('/');
 document.querySelectorAll('#side a').forEach(a=>a.classList.toggle('on',a.dataset.r===name));
 // context bar ONLY on an account/contact page — hidden everywhere else
 const onAccount=(name==='accounts'&&id)||name==='committee';
 document.getElementById('ctxbar').style.display=(onAccount&&S.account)?'flex':'none';
 const el=document.getElementById('screen');el.innerHTML='<div class="muted">loading…</div>';
 (SCREENS[name]||SCREENS.dashboard)(el,id);}
window.addEventListener('hashchange',route);

/* ═══════════ command palette + notifications ═══════════ */
function openPalette(){document.getElementById('pal').classList.add('on');
 const q=document.getElementById('palq');q.value='';q.focus();document.getElementById('palres').innerHTML='';}
document.addEventListener('keydown',e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openPalette();}
 if(e.key==='Escape')document.querySelectorAll('.overlay').forEach(o=>o.classList.remove('on'));});
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('on')}));
let palT=null;
function palSearch(){clearTimeout(palT);palT=setTimeout(async()=>{
 const q=document.getElementById('palq').value;if(q.length<2)return;
 const r=await api('GET','/search?q='+encodeURIComponent(q));if(!r.ok)return;
 const res=r.data.results,out=[];
 for(const[k,hits]of Object.entries(res))for(const h of hits)
  out.push(`<div class="hit" onclick='palGo("${k}","${h.id}",${JSON.stringify(h.label)})'><span class="k">${k}</span>${esc(h.label)} <span class="muted">${esc(h.sub||'')}</span></div>`);
 document.getElementById('palres').innerHTML=out.join('')||'<div class="muted">no matches</div>';},250);}
function palGo(kind,id,label){document.getElementById('pal').classList.remove('on');
 if(kind==='companies'){setAccount(id,label);nav('accounts/'+id);}
 else if(kind==='contacts')nav('contacts');
 else if(kind==='deals')nav('pipeline');
 else if(kind==='signals')nav('signals');
 else if(kind==='quotes')nav('quotes');
 else if(kind==='journeys')nav('journeys');
 else nav('dashboard');}
async function openNotifs(){document.getElementById('notifs').classList.add('on');
 const[s,d]=await Promise.all([api('GET','/signals'),api('GET','/workflow/dead-letters')]);
 const sigs=(s.data||[]).slice(0,8).map(x=>`<div class="hit" onclick="nav('signals')"><span class="k">signal</span>${esc(x.title)}</div>`).join('');
 const dls=(d.data||[]).slice(0,5).map(x=>`<div class="hit" onclick="nav('workflow')"><span class="k" style="color:var(--red)">dead-letter</span>${esc(x.node_id)}: ${esc(x.error||'')}</div>`).join('');
 document.getElementById('notifbody').innerHTML=(sigs+dls)||'<div class="muted">all quiet</div>';}
async function notifDot(){const d=await api('GET','/workflow/dead-letters');
 if(d.ok&&(d.data||[]).length)document.getElementById('notifdot').style.display='block';}

/* ═══════════ screens ═══════════ */
const SCREENS={};
function kpi(t,v,s){return `<div class="card"><h3>${t}</h3><div class="kpi">${v}</div><div class="muted">${s||''}</div></div>`}

SCREENS.dashboard=async el=>{
 el.innerHTML='<h2>Dashboard</h2><div class="sub">One view of the whole operation.</div><div class="grid g4" id="dk"></div><div class="grid g2" style="margin-top:14px"><div class="card"><h3>Top accounts</h3><div id="dacc"></div></div><div class="card"><h3>Hot leads</h3><div id="dhot" class="muted">—</div></div></div>';
 const r=await api('GET','/dashboard/executive');if(!r.ok)return;const d=r.data;
 document.getElementById('dk').innerHTML=
  kpi('Pipeline',d.pipeline_sar,'weighted '+d.weighted_sar)+kpi('Accounts',d.accounts,d.contacts.toLocaleString()+' contacts')+
  kpi('Signals / week',d.signals_this_week,'')+kpi('Email open rate',d.email.open_rate+'%','click '+d.email.click_rate+'%');
 const a=await api('GET','/organizations');
 if(a.ok)document.getElementById('dacc').innerHTML='<table>'+ (a.data||[]).slice(0,8).map(o=>
  `<tr class="click" onclick='setAccount("${o.id}",${JSON.stringify(o.canonical_name)});nav("accounts/${o.id}")'><td>${esc(o.canonical_name)}</td></tr>`).join('')+'</table>';
 document.getElementById('dhot').innerHTML=d.hot_leads.length?d.hot_leads.map(h=>`<div>${h.person_id.slice(0,8)} — <span class="badge b-gold">${h.score}</span></div>`).join(''):'no engagement yet';};

let _orgsCache=[],_bdOv=null,_bdOvErr=null;
SCREENS.accounts=async(el,id)=>{
 if(id)return account360(el,id);
 el.innerHTML=`<h2>Accounts</h2><div class="sub">Financial institutions and their ecosystem — search, open, edit, tag, import.</div>
 <div class="card"><div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
  <input id="aq" placeholder="🔍 Search banks & ecosystem…" oninput="aFilter()" style="max-width:280px">
  <button class="act" style="margin:0" onclick="aNewForm()">+ New organization</button>
  <button class="act gold" style="margin:0" onclick="csvUp('organizations')">⬆ Import CSV</button>
  <button class="act" style="margin:0" onclick="dl('/export/organizations','banks.csv')">⬇ Export CSV</button></div>
  <div id="aform"></div>
  <h3 style="margin-top:8px">🏦 Banks</h3><div id="alist">loading…</div>
  <h3 style="margin-top:16px">🏛 Non-Bank Financial Institutions (insurance · payments · asset mgmt · finance)</h3><div id="nlist">—</div>
  <h3 style="margin-top:16px">🔗 Ecosystem (vendors · subsidiaries · fintechs · regulators)</h3><div id="elist">—</div></div>`;
 const [r,ov]=await Promise.all([api('GET','/organizations'),api('GET','/bd/overview')]);
 _orgsCache=r.ok?(r.data||[]):[];_bdOv=ov.ok?ov.data:null;_bdOvErr=ov.ok?null:ov.status;aFilter();};
window.aFilter=()=>{
 const q=(document.getElementById('aq')?.value||'').toLowerCase();
 const pb=t=>t?`<span class="badge ${t==='Tier 1'?'b-gold':t==='Tier 2'?'b-blue':'b-dim'}">${esc(t)}</span>`:'<span class="badge b-dim">—</span>';
 if(!_bdOv){
  const msg=_bdOvErr===401?
   '<span class="muted">Sign in required to load accounts — <button class="act gold" style="margin:0;padding:2px 10px" onclick="nav(\'settings\')">go to Settings to sign in</button>, then reopen this page.</span>':
   '<span class="muted">Could not load accounts (server error'+(_bdOvErr?': '+_bdOvErr:'')+'). <button class="act" style="margin:0;padding:2px 10px" onclick="SCREENS.accounts(document.getElementById(\'screen\'))">retry</button></span>';
  document.getElementById('alist').innerHTML=msg;
  document.getElementById('nlist').innerHTML=msg;
  document.getElementById('elist').innerHTML=msg;
  return;
 }
 if(_bdOv){
  const bankRow=b=>`<tr><td class="click" style="cursor:pointer" onclick='setAccount("${b.id}",${JSON.stringify(b.name)});nav("accounts/${b.id}")'><b>${esc(b.name)}</b>${b.name_ar?' <span class="muted">'+esc(b.name_ar)+'</span>':''} ${(b.tags||[]).slice(0,2).map(t=>'<span class="badge b-dim" style="margin:1px">'+esc(t.replace(/_/g,' '))+'</span>').join('')}</td>
   <td>${pb(b.priority)}</td><td>${b.contacts}</td><td>${b.indians}</td><td>${b.signals}</td>
   <td style="white-space:nowrap"><button class="act gold" style="margin:0;padding:4px 10px" onclick='aEdit("${b.id}")'>edit</button>
   <button class="act" style="margin:0;padding:4px 10px;background:var(--red)" onclick='aDel("${b.id}",${JSON.stringify(b.name)})'>del</button></td></tr>`;
  const hdr='<table><tr><th>Organization</th><th>Priority</th><th>Contacts</th><th>🇮🇳 Indians</th><th>Signals</th><th></th></tr>';
  const banks=_bdOv.banks.filter(b=>!q||(b.name||'').toLowerCase().includes(q));
  document.getElementById('alist').innerHTML=banks.length?hdr+banks.map(bankRow).join('')+'</table>':'<span class="muted">no matches</span>';
  const nb=(_bdOv.nbfi||[]).filter(b=>!q||(b.name||'').toLowerCase().includes(q));
  document.getElementById('nlist').innerHTML=nb.length?hdr+nb.map(bankRow).join('')+'</table>':'<span class="muted">none yet — tag an org as insurance_company / payment_bank / financial_institution…</span>';
  const eco=_bdOv.ecosystem.filter(e=>!q||(e.name||'').toLowerCase().includes(q));
  document.getElementById('elist').innerHTML=eco.length?
   '<table><tr><th>Organization</th><th>Tags</th><th>Contacts</th><th>Connected banks</th><th></th></tr>'+eco.map(e=>
   `<tr><td class="click" style="cursor:pointer" onclick='setAccount("${e.id}",${JSON.stringify(e.name)});nav("accounts/${e.id}")'>${esc(e.name)}</td>
   <td>${(e.tags||[]).map(t=>'<span class="badge b-blue" style="margin:1px">'+esc(t)+'</span>').join('')}</td>
   <td>${e.contacts}</td><td>${e.connected_banks}</td>
   <td><button class="act gold" style="margin:0;padding:4px 10px" onclick='aEdit("${e.id}")'>edit</button></td></tr>`).join('')+'</table>':'<span class="muted">none tagged yet — use edit → tags</span>';
 }};
window.aNewForm=()=>{document.getElementById('aform').innerHTML=`<div class="card" style="margin-bottom:10px">
 <label>Bank name</label><input id="anb"><label>Country</label><input id="anc" value="SA">
 <label>Website</label><input id="anw"><button class="act" onclick="aNew()">Create</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('aform').innerHTML=''">Cancel</button></div>`;};
window.aNew=async()=>{const r=await api('POST','/organizations',{canonical_name:v2('anb'),country:v2('anc'),website:v2('anw')});
 if(r.ok){document.getElementById('aform').innerHTML='';SCREENS.accounts(document.getElementById('screen'));}};
window.aEdit=async id=>{const o=_orgsCache.find(x=>x.id===id);if(!o)return;
 const cur=(_bdOv&&[..._bdOv.banks,..._bdOv.ecosystem].find(x=>x.id===id)?.tags)||[];
 const opts=(_bdOv?_bdOv.tag_options:[]);
 document.getElementById('aform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Edit — changes are audit-trailed</h3>
 <label>Name</label><input id="aeb" value="${esc(o.canonical_name||'')}">
 <label>Country</label><input id="aec" value="${esc(o.country||'')}">
 <label>Website</label><input id="aew" value="${esc(o.website||'')}">
 <label>Core banking system</label><input id="aek" value="${esc(o.core_banking||'')}">
 <label>Classification (controls Banks / Non-Bank FI / Ecosystem grouping)</label><div id="aetags">`+
 Object.entries((_bdOv&&_bdOv.tag_groups)||{All:opts}).map(([g,ts])=>
  `<div style="margin:5px 0"><span class="muted" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em">${g}</span><br>`+
  ts.map(t=>`<label style="display:inline-flex;gap:4px;margin:3px 10px 3px 0;font-size:12px;color:var(--text)"><input type="checkbox" value="${t}" ${cur.includes(t)?'checked':''}> ${t.replace(/_/g,' ')}</label>`).join('')+'</div>').join('')+
 `</div><button class="act" onclick='aSave("${id}")'>Save</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('aform').innerHTML=''">Cancel</button></div>`;};
window.aSave=async id=>{
 const tags=[...document.querySelectorAll('#aetags input:checked')].map(c=>c.value);
 const r=await api('PATCH','/organizations/'+id,{fields:{canonical_name:v2('aeb'),country:v2('aec'),website:v2('aew'),core_banking:v2('aek')}});
 await api('POST','/bd/organizations/'+id+'/tags',{tags});
 if(r.ok)SCREENS.accounts(document.getElementById('screen'));};
window.aDel=async(id,name)=>{if(!confirm('Soft-delete "'+name+'"? (restorable — sets inactive)'))return;
 await api('DELETE','/organizations/'+id);SCREENS.accounts(document.getElementById('screen'));};
function v2(id){return document.getElementById(id).value}
/* CSV import: parse in browser, POST JSON rows */
window.csvUp=entity=>{
 const inp=document.createElement('input');inp.type='file';inp.accept='.csv';
 inp.onchange=async()=>{const txt=await inp.files[0].text();
  const lines=txt.split(/\r?\n/).filter(l=>l.trim());
  const head=lines[0].split(',').map(h=>h.trim().toLowerCase().replace(/ /g,'_'));
  const rows=lines.slice(1).map(l=>{const cells=l.split(',');const o={};head.forEach((h,i)=>o[h]=(cells[i]||'').trim());return o});
  const r=await api('POST','/import/'+entity,{rows});
  alert(r.ok?('Imported: '+JSON.stringify(r.data)):('Import failed: '+r.status));
  route();};
 inp.click();};

async function account360(el,id){
 const org=await api('GET','/organizations/'+id);const name=org.ok?org.data.canonical_name:'account';
 if(org.ok)setAccount(id,name);
 el.innerHTML=`<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><h2>${esc(name)}</h2>
  <button class="act gold" style="margin:0;padding:5px 12px" onclick="a360EditBank('${id}')">✎ edit bank</button>
  <button class="act" style="margin:0;padding:5px 12px" onclick="a360Score('${id}')">score</button>
  <button class="act" style="margin:0;padding:5px 12px;background:var(--red)" onclick='aDel("${id}",${JSON.stringify(name)})'>delete</button></div>
 <div class="sub">Account 360 — everything about this bank in one place.</div>
 <div id="a360x"></div>
 <div class="tabs" id="a360t"></div><div id="a360b"></div>`;
 const tabs={Overview:t360Overview,Activity:t360Activity,Contacts:t360Contacts,Committee:t360Committee,Signals:t360Signals,Vendors:t360Vendors,Deals:t360Deals,Documents:t360Docs,AI:t360AI,Tasks:t360Tasks};
 const tb=document.getElementById('a360t');
 Object.keys(tabs).forEach((t,i)=>{const b=document.createElement('button');b.textContent=t;
  b.onclick=()=>{tb.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');tabs[t](document.getElementById('a360b'),id)};
  if(i===0)b.classList.add('on');tb.appendChild(b);});
 tabs.Overview(document.getElementById('a360b'),id);}
window.a360EditBank=async id=>{
 if(!_bdOv){const ov=await api('GET','/bd/overview');_bdOv=ov.ok?ov.data:null;}
 if(!_orgsCache.length){const r=await api('GET','/organizations');_orgsCache=r.ok?r.data:[];}
 const bak=document.getElementById('a360x');bak.innerHTML='<div id="aform"></div>';
 aEdit(id);};
window.a360Score=async id=>{
 const r=await api('GET','/bd/banks/'+id+'/score');const d=r.ok?r.data:{};
 document.getElementById('a360x').innerHTML=`<div class="card" style="margin:10px 0"><h3>Account score & priority</h3>
 <div class="grid g3">
 <div><label>Tier (Tier 1/2/3)</label><input id="sc_t" value="${esc(d.tier||'')}"></div>
 <div><label>Priority</label><input id="sc_p" value="${esc(d.priority||'')}"></div>
 <div><label>Readiness</label><input id="sc_r" value="${esc(d.readiness||'')}"></div>
 <div><label>Segment</label><input id="sc_s" value="${esc(d.segment||'')}"></div>
 <div><label>Digital maturity</label><input id="sc_d" value="${esc(d.digital_maturity||'')}"></div>
 <div><label>Open banking</label><input id="sc_o" value="${esc(d.open_banking||'')}"></div></div>
 <button class="act" onclick="a360ScoreSave('${id}')">Save score</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('a360x').innerHTML=''">Cancel</button></div>`;};
window.a360ScoreSave=async id=>{
 await api('PATCH','/bd/banks/'+id+'/score',{fields:{tier:v2('sc_t')||null,priority:v2('sc_p')||null,
  readiness:v2('sc_r')||null,segment:v2('sc_s')||null,digital_maturity:v2('sc_d')||null,open_banking:v2('sc_o')||null}});
 document.getElementById('a360x').innerHTML='<span class="badge b-green" style="margin:8px 0">score saved</span>';};
async function t360Overview(el,id){const r=await api('GET','/organizations/'+id+'/account');
 el.innerHTML='<div class="grid g3" id="ov"></div>';
 const d=r.ok?r.data:{};document.getElementById('ov').innerHTML=
  kpi('Tier',d.tier||'—',d.segment||'')+kpi('Score',d.score??'—','readiness '+(d.readiness??'—'))+kpi('Lifecycle',d.lifecycle_status||'—',d.open_banking?'open banking: '+d.open_banking:'');}

/* ── Activity tab: bank-level unified timeline + logging ── */
async function t360Activity(el,id){
 el.innerHTML=`<div class="card"><h3>Log bank-level activity (event, seminar, exec meeting…)</h3>
 <div class="grid g3"><div><label>Type</label><select id="oa_t"><option>event</option><option>seminar</option><option>webinar</option><option>meeting</option><option>linkedin</option><option>call</option><option>site_visit</option><option>note</option></select></div>
 <div><label>Outcome</label><input id="oa_o"></div><div><label>Next action</label><input id="oa_x"></div></div>
 <label>What happened</label><textarea id="oa_n" rows="2"></textarea>
 <button class="act" onclick="oaSave('${id}')">Log it</button></div>
 <div class="card" style="margin-top:12px"><h3>Bank activity timeline (all contacts + org events)</h3><div id="oatl">loading…</div></div>`;
 oaLoad(id);}
window.oaLoad=async id=>{
 const r=await api('GET','/bd/orgs/'+id+'/timeline');
 const rows=r.ok?(r.data||[]).slice(0,60):[];
 document.getElementById('oatl').innerHTML=rows.length?rows.map(e=>{
  const k=(e.kind||'').split(':')[0];
  return `<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:12.5px">
  <span>${KIND_ICON[k]||'•'}</span><span class="muted" style="min-width:118px">${String(e.at).slice(0,16).replace('T',' ')}</span>
  <span><b>${esc(e.kind)}</b> ${esc(e.detail||'')}${e.person?(' <span class="muted">· '+esc(e.person)+'</span>'):''}</span></div>`}).join(''):
  '<span class="muted">no activity yet — log one above, or contact-level touches will roll up here</span>';};
window.oaSave=async id=>{
 const r=await api('POST','/bd/orgs/'+id+'/activities',{activity_type:v2('oa_t'),notes:v2('oa_n'),
  outcome:v2('oa_o')||null,next_action:v2('oa_x')||null,owner:'Puneet'});
 if(r.ok){document.getElementById('oa_n').value='';oaLoad(id);}};

/* ── Contacts tab: FULL legacy parity (filters, pagination, edit, log, del) ── */
let _c360={id:null,page:1};
async function t360Contacts(el,id){
 _c360={id,page:1};
 el.innerHTML=`<div class="grid g4" id="cst"></div>
 <div class="card" style="margin-top:10px">
 <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
  <input id="cf_q" placeholder="🔍 name / title…" style="max-width:200px" onkeydown="if(event.key==='Enter')c360Load()">
  <select id="cf_t" onchange="c360Load()" style="max-width:130px"><option value="">All tiers</option><option value="1">Tier 1</option><option value="2">Tier 2</option><option value="3">Tier 3</option></select>
  <select id="cf_s" onchange="c360Load()" style="max-width:150px"><option value="">All seniority</option><option value="c_suite">C-suite</option><option value="evp_svp">EVP/SVP</option><option value="vp_director">VP/Director</option><option value="manager">Manager</option><option value="staff">Staff</option></select>
  <label style="display:flex;align-items:center;gap:5px;color:var(--text);font-size:12.5px;margin:0"><input type="checkbox" id="cf_i" onchange="c360Load()" style="width:auto"> 🇮🇳 Indian origin only</label>
  <button class="act" style="margin:0" onclick="c360NewForm('${id}')">+ New contact</button>
  <button class="act gold" style="margin:0" onclick="c360Upload('${id}')">⬆ Upload Excel/CSV</button>
  <button class="act" style="margin:0;background:var(--blue)" onclick="c360Export('${id}')">⬇ Export</button></div>
 <div id="cform"></div><div id="clist">loading…</div><div id="cpage" class="muted" style="margin-top:8px"></div></div>`;
 c360Load();}
window.c360Load=async()=>{
 const {id,page}=_c360;
 const p=new URLSearchParams({q:v2('cf_q')||'',tier:v2('cf_t')||'',seniority:v2('cf_s')||'',
  indian:document.getElementById('cf_i').checked?'1':'',page});
 const r=await api('GET','/bd/banks/'+id+'/contacts?'+p);if(!r.ok)return;
 const d=r.data,s=d.stats;
 document.getElementById('cst').innerHTML=
  kpi('Contacts',s.total,'T1:'+s.tier_counts['1']+' · T2:'+s.tier_counts['2']+' · T3:'+s.tier_counts['3'])+
  kpi('🇮🇳 Indian origin',s.indians,'')+kpi('C-suite',s.c_suite,'')+kpi('Champions',s.champions,'');
 const flag=p=>[(p.is_decision_maker?'DM':''),(p.is_influencer?'CH':''),(p.is_connector?'CN':''),(p.is_indian?'🇮🇳':'')].filter(Boolean).join(' ');
 const st=p=>p.summary&&p.summary!=='Not contacted yet'?esc(p.summary.slice(0,60)):(p.messaged?'messaged':p.conn_accepted?'accepted':p.conn_sent?'sent':'—');
 document.getElementById('clist').innerHTML=d.contacts.length?
  '<table><tr><th>Name</th><th>Title</th><th>Tier</th><th>Flags</th><th>Outreach</th><th>Actions</th></tr>'+d.contacts.map(p=>
  `<tr><td><b class="click" style="cursor:pointer;color:var(--gold)" onclick='nav("contact/${p.id}")'>${esc(p.full_name)}</b>${p.linkedin?' <a style="color:var(--blue)" href="'+esc(p.linkedin)+'" target="_blank">in</a>':''}</td>
  <td class="muted">${esc(p.title||'')}</td><td>${p.priority_tier?('<span class="badge '+(p.priority_tier==='1'?'b-gold':'b-dim')+'">T'+p.priority_tier+'</span>'):'—'}</td>
  <td>${flag(p)}</td><td class="muted">${st(p)}${p.next_step?(' · '+esc(p.next_step.slice(0,30))):''}</td>
  <td style="white-space:nowrap"><button class="act gold" style="margin:0;padding:3px 8px" onclick='c360Edit(${JSON.stringify(p)})'>edit</button>
  <button class="act" style="margin:0;padding:3px 8px;background:var(--blue)" onclick='c360Log("${p.id}")'>log</button>
  <button class="act" style="margin:0;padding:3px 8px;background:var(--red)" onclick='c360Del("${p.id}",${JSON.stringify(p.full_name)})'>del</button></td></tr>`).join('')+'</table>':'<span class="muted">no matches</span>';
 let pg='page '+d.page+' / '+d.pages+' · '+d.filtered_total+' matching';
 if(d.page>1)pg+=' · <a style="color:var(--gold);cursor:pointer" onclick="_c360.page--;c360Load()">← prev</a>';
 if(d.page<d.pages)pg+=' · <a style="color:var(--gold);cursor:pointer" onclick="_c360.page++;c360Load()">next →</a>';
 document.getElementById('cpage').innerHTML=pg;};
window.c360Upload=id=>{
 const inp=document.createElement('input');inp.type='file';inp.accept='.csv,.xlsx,.xls';
 inp.onchange=async()=>{
  const box=document.getElementById('cform');
  box.innerHTML='<div class="card" style="margin-bottom:10px"><span class="badge b-gold">uploading '+esc(inp.files[0].name)+' …</span></div>';
  const fd=new FormData();fd.append('file',inp.files[0]);
  const h={};if(S.token)h['Authorization']='Bearer '+S.token;
  const r=await fetch('/bd/banks/'+id+'/contacts/upload',{method:'POST',headers:h,body:fd});
  const j=await r.json().catch(()=>({}));
  box.innerHTML='<div class="card" style="margin-bottom:10px"><h3>'+(r.ok?'Import complete':'Import failed')+'</h3><pre>'+esc(JSON.stringify(j,null,1))+'</pre>'+
   '<button class="act" style="background:var(--line)" onclick="document.getElementById(\'cform\').innerHTML=\'\'">Close</button></div>';
  c360Load();};
 inp.click();};
window.c360Export=id=>{
 document.getElementById('cform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Export contacts — which ones?</h3>
 <div style="display:flex;flex-direction:column;gap:6px;margin:8px 0">
 <button class="act" onclick="dl('/export/persons?org_id=${id}','${esc((S.account||{}).name||'bank')}_all.csv')">⬇ All contacts at this bank</button>
 <button class="act" onclick="dl('/export/persons?org_id=${id}&tier=1','tier1.csv')">⬇ Tier 1 only</button>
 <button class="act" onclick="dl('/export/persons?org_id=${id}&indian=1','indian_origin.csv')">⬇ Indian-origin only</button>
 <button class="act" onclick="dl('/export/persons?org_id=${id}&seniority=c_suite','c_suite.csv')">⬇ C-suite only</button>
 <button class="act gold" onclick="dl('/export/persons','all_contacts.csv')">⬇ EVERY contact (all banks)</button></div>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('cform').innerHTML=''">Close</button></div>`;};
/* auth-aware download: fetch with the bearer token, then save the blob */
window.dl=async(path,filename)=>{
 const h={};if(S.token)h['Authorization']='Bearer '+S.token;
 const r=await fetch(path,{headers:h});
 if(!r.ok){alert('export failed: '+r.status+(r.status===401?' — sign in first (Settings)':''));return}
 const blob=await r.blob();const u=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=u;a.download=filename;a.click();URL.revokeObjectURL(u);};
window.c360NewForm=id=>{document.getElementById('cform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>New contact</h3>
 <div class="grid g3"><div><label>Full name</label><input id="cn_n"></div>
 <div><label>Title</label><input id="cn_t"></div>
 <div><label>Seniority</label><select id="cn_s"><option value="">—</option><option value="c_suite">C-suite</option><option value="evp_svp">EVP/SVP</option><option value="vp_director">VP/Director</option><option value="manager">Manager</option><option value="staff">Staff</option></select></div>
 <div><label>Priority tier</label><select id="cn_p"><option value="">—</option><option>1</option><option>2</option><option>3</option></select></div>
 <div><label>Email</label><input id="cn_e"></div><div><label>Mobile</label><input id="cn_m"></div>
 <div><label>LinkedIn URL</label><input id="cn_l"></div></div>
 <label style="display:inline-flex;gap:5px;margin-top:6px;color:var(--text)"><input type="checkbox" id="cn_i" style="width:auto"> 🇮🇳 Indian origin</label>
 <label style="display:inline-flex;gap:5px;margin-left:14px;color:var(--text)"><input type="checkbox" id="cn_d" style="width:auto"> Decision maker</label>
 <label style="display:inline-flex;gap:5px;margin-left:14px;color:var(--text)"><input type="checkbox" id="cn_c" style="width:auto"> Connector</label>
 <br><button class="act" onclick="c360New('${id}')">Create</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('cform').innerHTML=''">Cancel</button></div>`;};
window.c360New=async id=>{
 const r=await api('POST','/bd/banks/'+id+'/contacts',{full_name:v2('cn_n'),current_title:v2('cn_t')||null,
  seniority_level:v2('cn_s')||null,priority_tier:v2('cn_p')||null,primary_email:v2('cn_e')||null,
  mobile:v2('cn_m')||null,linkedin_url:v2('cn_l')||null,
  is_indian_origin:document.getElementById('cn_i').checked,
  is_decision_maker:document.getElementById('cn_d').checked,
  is_connector:document.getElementById('cn_c').checked});
 if(r.ok){document.getElementById('cform').innerHTML='';c360Load();}};
window.c360Edit=p=>{document.getElementById('cform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Edit ${esc(p.full_name)} — audit-trailed</h3>
 <div class="grid g3"><div><label>Name</label><input id="ce_n" value="${esc(p.full_name||'')}"></div>
 <div><label>Title</label><input id="ce_t" value="${esc(p.title||'')}"></div>
 <div><label>Priority tier</label><select id="ce_p"><option value="">—</option><option ${p.priority_tier==='1'?'selected':''}>1</option><option ${p.priority_tier==='2'?'selected':''}>2</option><option ${p.priority_tier==='3'?'selected':''}>3</option></select></div>
 <div><label>Email</label><input id="ce_e" value="${esc(p.email||'')}"></div>
 <div><label>Mobile</label><input id="ce_m" value="${esc(p.phone||'')}"></div>
 <div><label>Next step</label><input id="ce_s" value="${esc(p.next_step||'')}"></div></div>
 <label style="display:inline-flex;gap:5px;margin-top:6px;color:var(--text)"><input type="checkbox" id="ce_i" ${p.is_indian?'checked':''} style="width:auto"> 🇮🇳 Indian origin</label>
 <label style="display:inline-flex;gap:5px;margin-left:14px;color:var(--text)"><input type="checkbox" id="ce_d" ${p.is_decision_maker?'checked':''} style="width:auto"> Decision maker</label>
 <label style="display:inline-flex;gap:5px;margin-left:14px;color:var(--text)"><input type="checkbox" id="ce_c" ${p.is_connector?'checked':''} style="width:auto"> Connector</label>
 <h3 style="margin-top:12px">Outreach by channel — what have we done, what did they say</h3>
 <div id="chgrid" class="grid g2"><div class="muted">loading channels…</div></div>
 <br><button class="act" onclick='c360Save("${p.id}")'>Save contact + channels</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('cform').innerHTML=''">Cancel</button></div>`;
 loadChannels(p.id);};
window._chSugg={};
async function loadChannels(pid){
 const r=await api('GET','/bd/persons/'+pid+'/channels');if(!r.ok)return;
 window._chSugg=r.data.stage_suggestions;
 document.getElementById('chgrid').innerHTML=r.data.channels.map(ch=>`
 <div class="card"><h3>${ch.label} ${ch.updated_at?('<span class="muted" style="text-transform:none;letter-spacing:0">· updated '+ch.updated_at.slice(0,10)+(ch.updated_by?' by '+esc(ch.updated_by):'')+'</span>'):''}</h3>
 <label>Status — what have we done on ${ch.label}</label>
 <input list="dl_${ch.channel}" id="ch_${ch.channel}_stage" value="${esc(ch.stage||'')}" placeholder="pick or type…">
 <datalist id="dl_${ch.channel}">${(window._chSugg[ch.channel]||[]).map(s=>'<option value="'+esc(s)+'">').join('')}</datalist>
 <label>Response — what did they say</label>
 <input id="ch_${ch.channel}_notes" value="${esc(ch.notes||'')}" placeholder="e.g. asked to reconnect after Ramadan">
 <label>Next step on ${ch.label}</label>
 <input id="ch_${ch.channel}_next" value="${esc(ch.next_step||'')}" placeholder="what to do next on this channel"></div>`).join('')+
 `<div class="card"><h3>Rollup</h3><div class="muted">${esc(r.data.summary||'Not contacted yet')}</div>
 <div class="muted" style="margin-top:6px">Saved per channel — the contact table shows the auto-rollup.</div></div>`;}
async function saveChannels(pid){
 for(const ch of ['linkedin','email','phone','whatsapp']){
  const st=document.getElementById('ch_'+ch+'_stage');if(!st)continue;
  const stage=st.value.trim(),notes=v2('ch_'+ch+'_notes').trim(),next=v2('ch_'+ch+'_next').trim();
  if(stage||notes||next)
   await api('POST','/bd/persons/'+pid+'/channels',{channel:ch,stage:stage||null,notes:notes||null,next_step:next||null,updated_by:'Puneet'});
 }}
window.c360Save=async id=>{
 const r=await api('PATCH','/persons/'+id,{fields:{full_name:v2('ce_n'),current_title:v2('ce_t')||null,
  priority_tier:v2('ce_p')||null,primary_email:v2('ce_e')||null,mobile:v2('ce_m')||null,next_step:v2('ce_s')||null,
  is_indian_origin:document.getElementById('ce_i').checked,
  is_decision_maker:document.getElementById('ce_d').checked,
  is_connector:document.getElementById('ce_c').checked}});
 await saveChannels(id);
 if(r.ok){document.getElementById('cform').innerHTML='';c360Load();}};
window.bdQuick=async(id,f)=>{await api('PATCH','/crm/persons/'+id+'/outreach',{[f]:true,updated_by:'Puneet'});c360Load();};
window.c360Del=async(id,name)=>{if(!confirm('Soft-delete "'+name+'"? (restorable)'))return;
 await api('DELETE','/persons/'+id);c360Load();};
window.c360Log=async id=>{
 const r=await api('GET','/crm/records/persons/'+id+'/history');
 const rows=(r.data||[]).slice(-15).reverse();
 document.getElementById('cform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Change log (audit trail)</h3>`+
  (rows.length?rows.map(h=>`<div style="margin:5px 0;font-size:12px"><span class="badge ${h.action==='insert'?'b-green':h.action==='delete'?'b-red':'b-gold'}">${h.action}</span>
   <span class="muted">${String(h.at).slice(0,16)} · ${esc(h.actor||'system')}</span> ${(h.changed||[]).map(c=>esc(c)).join(', ')}</div>`).join(''):'<span class="muted">no recorded changes yet</span>')+
  `<button class="act" style="background:var(--line)" onclick="document.getElementById('cform').innerHTML=''">Close</button></div>`;};
async function t360Committee(el,id){
 el.innerHTML='<div class="grid g2"><div class="card"><h3>Coverage</h3><div id="ccov">—</div><button class="act gold" onclick="c360cov(\''+id+'\')">Check coverage</button></div><div class="card"><h3>Infer roles</h3><div class="muted">Map titles → committee roles for every contact.</div><button class="act" onclick="c360inf(\''+id+'\')">Run inference</button><pre id="cinf">—</pre></div></div>';
 c360cov(id);}
window.c360cov=async id=>{const r=await api('GET','/abm/committee/'+id+'/coverage');if(!r.ok)return;
 const d=r.data,roles=["economic_buyer","executive_sponsor","champion","technical_buyer","user"];
 document.getElementById('ccov').innerHTML=`<div class="kpi">${d.coverage_pct}%</div><div class="bar"><i style="width:${d.coverage_pct}%"></i></div>`+
  roles.map(x=>`<span class="badge ${d.roles_covered.includes(x)?'b-green':'b-dim'}" style="margin:3px">${x.replace('_',' ')}</span>`).join('')+
  (d.single_threaded?'<div style="margin-top:6px"><span class="badge b-red">single-threaded</span></div>':'');};
window.c360inf=async id=>{const r=await api('POST','/abm/committee/'+id+'/infer');
 document.getElementById('cinf').textContent=JSON.stringify(r.data,null,1);c360cov(id);};
async function t360Signals(el,id){
 el.innerHTML=`<div class="card"><div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
 <button class="act" style="margin:0" onclick="sg360New('${id}')">+ New signal / initiative</button>
 <button class="act gold" style="margin:0" onclick="src360New('${id}')">+ Add news source (link)</button></div>
 <div id="sgform"></div><div id="src360l" class="muted" style="margin-bottom:8px"></div><div id="sg360l">loading…</div></div>`;
 sg360Load(id);src360Load(id);}
window.src360Load=async id=>{
 const r=await api('GET','/abm/collectors');if(!r.ok)return;
 const mine=(r.data||[]).filter(s=>s.url&&(s.org_id===id||false));
 // sources endpoint doesn't return org_id yet; show all bank-dedicated via name convention fallback
 const all=(r.data||[]);
 const rows=all.filter(s=>(s.org_id===id));
 document.getElementById('src360l').innerHTML=rows.length?
  'Dedicated sources: '+rows.map(s=>`${esc(s.name)} <span class="badge ${s.enabled?'b-green':'b-red'}">${s.enabled?'on':'off'}</span> (${s.items_ingested} items) <button class="act" style="margin:0;padding:2px 8px" onclick='src360Run("${s.id}","${id}")'>fetch now</button>`).join(' · '):'';};
window.src360New=id=>{document.getElementById('sgform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Add a news/RSS source for THIS bank</h3>
 <div class="muted" style="margin-bottom:6px">Paste any RSS/Atom link (bank newsroom feed, Google News RSS for the bank, etc). Every item fetched will be attached to this bank automatically, hourly.</div>
 <label>Source name</label><input id="sr_n" placeholder="e.g. Alinma newsroom">
 <label>Feed URL</label><input id="sr_u" placeholder="https://…/rss">
 <label>Type</label><select id="sr_t"><option>news</option><option>regulatory</option><option>hiring</option><option>tender</option></select>
 <button class="act" onclick="src360Add('${id}')">Add + fetch now</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('sgform').innerHTML=''">Cancel</button></div>`;};
window.src360Add=async id=>{
 const r=await api('POST','/abm/collectors',{name:v2('sr_n'),url:v2('sr_u'),signal_type:v2('sr_t'),org_id:id});
 if(!r.ok){alert('failed: '+JSON.stringify(r.data));return}
 document.getElementById('sgform').innerHTML='';
 await api('POST','/abm/collectors/'+r.data.id+'/run');
 sg360Load(id);src360Load(id);};
window.src360Run=async(sid,id)=>{await api('POST','/abm/collectors/'+sid+'/run');sg360Load(id);src360Load(id);};
window.sg360Load=async id=>{
 const r=await api('GET','/organizations/'+id+'/signals');
 document.getElementById('sg360l').innerHTML=r.ok&&r.data.length?
  '<table><tr><th>Signal</th><th>Type</th><th>Urgency</th><th>Status</th><th>Actions</th></tr>'+r.data.map(s=>
  `<tr><td>${s.url?('<a href="'+esc(s.url)+'" target="_blank" style="color:var(--gold);text-decoration:none">'+esc(s.title)+' ↗</a>'):esc(s.title)}${s.estimated_value?' <span class="muted">('+esc(s.estimated_value)+')</span>':''}</td>
  <td><span class="badge b-blue">${esc(s.signal_type)}</span></td><td>${esc(s.urgency||'')}</td>
  <td>${s.is_read?'<span class="badge b-dim">read</span>':'<span class="badge b-gold">new</span>'}${s.is_actioned?' <span class="badge b-green">actioned</span>':''}</td>
  <td style="white-space:nowrap"><button class="act" style="margin:0;padding:3px 8px" onclick='sg360T("${s.id}","read","${id}")'>read</button>
  <button class="act gold" style="margin:0;padding:3px 8px" onclick='sg360T("${s.id}","actioned","${id}")'>actioned</button>
  <button class="act" style="margin:0;padding:3px 8px;background:var(--blue)" onclick='sg360E(${JSON.stringify(s)},"${id}")'>edit</button></td></tr>`).join('')+'</table>':
  '<span class="muted">no signals — add one or run collectors</span>';};
window.sg360T=async(sid,which,id)=>{await api('POST','/bd/signals/'+sid+'/toggle?which='+which);sg360Load(id);};
window.sg360New=id=>{document.getElementById('sgform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>New signal</h3>
 <label>Title</label><input id="sn_t"><div class="grid g3">
 <div><label>Type</label><select id="sn_y"><option>news</option><option>tender</option><option>regulatory</option><option>hiring</option><option>initiative</option></select></div>
 <div><label>Urgency</label><select id="sn_u"><option>CRITICAL</option><option selected>HIGH</option><option>MEDIUM</option><option>LOW</option></select></div>
 <div><label>Est. value</label><input id="sn_v" placeholder="SAR 2M"></div></div>
 <label>Summary</label><textarea id="sn_s" rows="2"></textarea>
 <button class="act" onclick="sg360Create('${id}')">Create</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('sgform').innerHTML=''">Cancel</button></div>`;};
window.sg360Create=async id=>{
 const r=await api('POST','/bd/banks/'+id+'/signals',{title:v2('sn_t'),signal_type:v2('sn_y'),
  urgency:v2('sn_u'),estimated_value:v2('sn_v')||null,summary:v2('sn_s')||null});
 if(r.ok){document.getElementById('sgform').innerHTML='';sg360Load(id);}};
window.sg360E=(s,id)=>{document.getElementById('sgform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Edit signal</h3>
 <label>Title</label><input id="se_t" value="${esc(s.title||'')}">
 <label>Urgency</label><input id="se_u" value="${esc(s.urgency||'')}">
 <label>Summary</label><textarea id="se_s" rows="2">${esc(s.summary||'')}</textarea>
 <button class="act" onclick='sg360Save("${s.id}","${id}")'>Save</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('sgform').innerHTML=''">Cancel</button></div>`;};
window.sg360Save=async(sid,id)=>{
 await api('PATCH','/bd/signals/'+sid,{fields:{title:v2('se_t'),urgency:v2('se_u'),summary:v2('se_s')}});
 document.getElementById('sgform').innerHTML='';sg360Load(id);};

/* ── Vendors tab: add/list/remove vendors on THIS bank ── */
async function t360Vendors(el,id){
 el.innerHTML=`<div class="card"><div style="display:flex;gap:8px;margin-bottom:10px">
 <button class="act" style="margin:0" onclick="vn360New('${id}')">+ Add vendor / subsidiary / partner</button></div>
 <div id="vnform"></div><div id="vn360l">loading…</div></div>`;
 vn360Load(id);}
window.vn360Load=async id=>{
 const r=await api('GET','/organizations/'+id+'/vendors');
 document.getElementById('vn360l').innerHTML=r.ok&&r.data.length?
  '<table><tr><th>Organization</th><th>Relationship</th><th>Confidence</th><th>Products</th><th></th></tr>'+r.data.map(v=>
  `<tr><td><b>${esc(v.name)}</b></td><td><span class="badge ${v.type==='subsidiary_of'?'b-blue':'b-green'}">${esc(v.type.replace('_of',''))}</span></td>
  <td>${v.confidence?Math.round(v.confidence*100)+'%':'—'}</td><td class="muted">${esc((v.products||'').slice(0,60))}</td>
  <td><button class="act" style="margin:0;padding:3px 8px;background:var(--red)" onclick='vn360Del("${id}","${v.rel_id}")'>remove</button></td></tr>`).join('')+'</table>':
  '<span class="muted">no vendors attached to this bank yet</span>';};
window.vn360New=id=>{document.getElementById('vnform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Attach to this bank</h3>
 <label>Vendor / org name (created if new)</label><input id="vn_n">
 <div class="grid g3"><div><label>Relationship</label><select id="vn_r"><option value="vendor_of">Vendor</option><option value="subsidiary_of">Subsidiary</option><option value="partner_of">Partner</option></select></div>
 <div><label>Confidence %</label><input id="vn_c" value="80"></div>
 <div><label>Products / context</label><input id="vn_p"></div></div>
 <button class="act" onclick="vn360Add('${id}')">Attach</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('vnform').innerHTML=''">Cancel</button></div>`;};
window.vn360Add=async id=>{
 const r=await api('POST','/organizations/'+id+'/vendors',{vendor_name:v2('vn_n'),
  relationship_type:v2('vn_r'),confidence:(parseFloat(v2('vn_c'))||80)/100,products:v2('vn_p')||null});
 if(r.ok){document.getElementById('vnform').innerHTML='';vn360Load(id);}};
window.vn360Del=async(id,rid)=>{if(!confirm('Remove this relationship? (the vendor org itself is kept)'))return;
 await api('DELETE','/organizations/'+id+'/vendors/'+rid);vn360Load(id);};

/* ── Documents tab: dossier uploads ── */
async function t360Docs(el,id){
 el.innerHTML=`<div class="card"><div style="display:flex;gap:8px;margin-bottom:10px">
 <button class="act" style="margin:0" onclick="dc360Up('${id}')">⬆ Upload document</button></div>
 <div id="dc360l">loading…</div></div>`;
 dc360Load(id);}
window.dc360Load=async id=>{
 const r=await api('GET','/bd/uploads?org_id='+id);
 document.getElementById('dc360l').innerHTML=r.ok&&r.data.length?
  '<table><tr><th>File</th><th>Size</th><th>Status</th><th>Actions</th></tr>'+r.data.map(u=>
  `<tr><td>${esc(u.filename)}${u.notes?' <span class="muted">'+esc(u.notes.slice(0,40))+'</span>':''}</td>
  <td class="muted">${Math.round((u.size||0)/1024)} KB</td><td><span class="badge b-dim">${esc(u.status||'')}</span></td>
  <td style="white-space:nowrap"><a class="act gold" style="margin:0;padding:3px 8px;text-decoration:none" href="/bd/uploads/${u.id}/download">⬇</a>
  <button class="act" style="margin:0;padding:3px 8px" onclick='dc360P("${u.id}","${id}")'>extract contacts</button></td></tr>`).join('')+'</table>':
  '<span class="muted">no documents for this bank yet</span>';};
window.dc360Up=id=>{
 const inp=document.createElement('input');inp.type='file';
 inp.onchange=async()=>{
  const fd=new FormData();fd.append('file',inp.files[0]);fd.append('org_id',id);fd.append('uploaded_by','Puneet');
  const h={};if(S.token)h['Authorization']='Bearer '+S.token;
  const r=await fetch('/bd/uploads',{method:'POST',headers:h,body:fd});
  alert(r.ok?'uploaded':'upload failed: '+r.status);dc360Load(id);};
 inp.click();};
window.dc360P=async(uid,id)=>{const r=await api('POST','/bd/uploads/'+uid+'/process');
 alert(r.ok?('processing: '+(r.data.status||'')):'failed');dc360Load(id);};
async function t360Deals(el,id){const r=await api('GET','/opportunities');
 const rows=(r.data||[]).filter(o=>o.org_id===id);
 el.innerHTML='<div class="card">'+(rows.length?'<table><tr><th>Stage</th><th>Amount</th><th>Next step</th></tr>'+rows.map(o=>
  `<tr><td>${esc(o.stage||'—')}</td><td>${o.amount_minor?('SAR '+(o.amount_minor/100).toLocaleString()):'—'}</td><td class="muted">${esc(o.next_step||'')}</td></tr>`).join('')+'</table>':'<span class="muted">no deals for this account</span>')+'</div>';}
async function t360AI(el,id){
 el.innerHTML=`<div class="card"><h3>AI research (uses prompt registry + guardrails)</h3>
 <label>Signal / topic</label><input id="aiq" value="digital onboarding RFP">
 <button class="act" onclick="a360ai('${id}')">Generate outreach angle</button><pre id="aiout">—</pre>
 <div class="muted" id="aimode"></div></div>`;
 const st=await api('GET','/ai/analytics');
 document.getElementById('aimode').textContent=st.ok&&st.data.live?'model: LIVE':'model: dry-run (set an LLM key in .env to go live)';}
window.a360ai=async id=>{const r=await api('POST','/ai/call',{prompt_name:'personalize_outreach',
 purpose:'personalization',variables:{role:'executive',segment:'tier1 bank',signal:document.getElementById('aiq').value,angle:'Vahana platform'}});
 document.getElementById('aiout').textContent=r.ok?r.data.text:'error';};
async function t360Tasks(el,id){
 el.innerHTML=`<div class="card"><h3>Create task for this account</h3>
 <label>Title</label><input id="tt" placeholder="Follow up with CTO">
 <label>Assignee</label><input id="ta" value="Puneet">
 <button class="act" onclick="a360task('${id}')">Create</button><pre id="tout">—</pre></div>`;}
window.a360task=async id=>{const r=await api('POST','/crm/tasks',{title:document.getElementById('tt').value,
 assignee:document.getElementById('ta').value,related_type:'organization',related_id:id});
 document.getElementById('tout').textContent=r.ok?'task created: '+r.data.task_id:'error '+r.status;};

let _pplCache=[];
SCREENS.contacts=async el=>{
 el.innerHTML=`<h2>Contacts</h2><div class="sub">Search, edit, import people across every account.</div>
 <div class="card"><div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
  <input id="pq" placeholder="🔍 Search people by name / title / email…" oninput="pFilter()" style="max-width:320px">
  <button class="act" style="margin:0" onclick="pNewForm()">+ New contact</button>
  <button class="act gold" style="margin:0" onclick="csvUp('persons')">⬆ Import CSV</button>
  <button class="act" style="margin:0" onclick="dl('/export/persons','all_contacts.csv')">⬇ Export CSV</button></div>
  <div id="pform"></div><div id="plist">loading…</div></div>
 <div class="card" style="margin-top:14px"><h3>Hot leads</h3><div id="phot">—</div></div>`;
 const r=await api('GET','/persons');
 _pplCache=r.ok?(r.data||[]):[];pFilter();
 const h=await api('GET','/sales/hot-leads');
 if(h.ok)document.getElementById('phot').innerHTML=h.data.length?h.data.map(l=>
  `<div>${esc(l.name||l.person_id.slice(0,8))} <span class="badge b-gold">${l.engagement_score}</span> <span class="muted">${l.opens}/${l.clicks}/${l.replies}</span></div>`).join(''):'<span class="muted">no engagement rows</span>';};
window.pFilter=()=>{
 const q=(document.getElementById('pq')?.value||'').toLowerCase();
 const rows=_pplCache.filter(p=>!q||((p.full_name||'')+' '+(p.current_title||'')+' '+(p.primary_email||'')).toLowerCase().includes(q)).slice(0,60);
 document.getElementById('plist').innerHTML=rows.length?'<table><tr><th>Name</th><th>Title</th><th>Email</th><th>Tier</th><th></th></tr>'+rows.map(p=>
  `<tr><td class="click" style="cursor:pointer;color:var(--gold)" onclick='nav("contact/${p.id}")'>${esc(p.full_name)}</td><td class="muted">${esc(p.current_title||'')}</td><td class="muted">${esc(p.primary_email||'')}</td><td>${esc(p.tier||'—')}</td>
  <td style="white-space:nowrap"><button class="act gold" style="margin:0;padding:4px 10px" onclick='pEdit("${p.id}")'>edit</button>
  <button class="act" style="margin:0;padding:4px 10px;background:var(--red)" onclick='pDel("${p.id}",${JSON.stringify(p.full_name)})'>del</button></td></tr>`).join('')+'</table>':'<span class="muted">no matches</span>';};
window.pNewForm=()=>{document.getElementById('pform').innerHTML=`<div class="card" style="margin-bottom:10px">
 <label>Full name</label><input id="pnn"><label>Title</label><input id="pnt">
 <label>Email</label><input id="pne"><label>Bank (name, created if new)</label><input id="pno" value="${S.account?esc(S.account.name):''}">
 <button class="act" onclick="pNew()">Create</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('pform').innerHTML=''">Cancel</button></div>`;};
window.pNew=async()=>{const r=await api('POST','/import/persons',{rows:[{full_name:v2('pnn'),current_title:v2('pnt'),primary_email:v2('pne')}],org_name:v2('pno')||null});
 if(r.ok){document.getElementById('pform').innerHTML='';SCREENS.contacts(document.getElementById('screen'));}};
window.pEdit=id=>{const p=_pplCache.find(x=>x.id===id);if(!p)return;
 document.getElementById('pform').innerHTML=`<div class="card" style="margin-bottom:10px"><h3>Edit — audit-trailed; history via /crm/records/persons/${id}/history</h3>
 <label>Name</label><input id="pen" value="${esc(p.full_name||'')}">
 <label>Title</label><input id="pet" value="${esc(p.current_title||'')}">
 <label>Email</label><input id="pee" value="${esc(p.primary_email||'')}">
 <label>Tier</label><input id="per" value="${esc(p.tier||'')}">
 <label>Next step</label><input id="pes" value="${esc(p.next_step||'')}">
 <button class="act" onclick='pSave("${id}")'>Save</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('pform').innerHTML=''">Cancel</button></div>`;};
window.pSave=async id=>{const r=await api('PATCH','/persons/'+id,{fields:{full_name:v2('pen'),current_title:v2('pet'),primary_email:v2('pee')||null,tier:v2('per')||null,next_step:v2('pes')||null}});
 if(r.ok)SCREENS.contacts(document.getElementById('screen'));};
window.pDel=async(id,name)=>{if(!confirm('Soft-delete "'+name+'"? (restorable)'))return;
 await api('DELETE','/persons/'+id);SCREENS.contacts(document.getElementById('screen'));};

SCREENS.vendors=async el=>{
 el.innerHTML=`<h2>Vendors & Ecosystem</h2><div class="sub">Who serves which bank — vendor, subsidiary and partner edges with confidence.</div>
 <div class="card"><input id="vq" placeholder="🔍 Search vendors…" oninput="vFilter()" style="max-width:280px;margin-bottom:10px"><div id="vlist">loading…</div></div>`;
 const r=await api('GET','/abm/vendors');
 window._venCache=r.ok?(r.data||[]):[];vFilter();};
window.vFilter=()=>{
 const q=(document.getElementById('vq')?.value||'').toLowerCase();
 const rows=(window._venCache||[]).filter(v=>!q||(v.name||'').toLowerCase().includes(q));
 document.getElementById('vlist').innerHTML=rows.length?rows.map(v=>
  `<div style="margin:10px 0;padding-bottom:10px;border-bottom:1px solid var(--line)"><b>${esc(v.name)}</b><br>`+
  (v.edges||[]).map(e=>`<span class="badge ${e.type==='subsidiary_of'?'b-blue':'b-green'}" style="margin:3px">${e.type.replace('_of','')} → ${esc(e.to)}${e.confidence?(' ·'+Math.round(e.confidence*100)+'%'):''}</span>`).join('')+
  (v.intelligence?`<div class="muted" style="margin-top:4px">${esc((v.intelligence.products||[]).slice?String(v.intelligence.products).slice(0,140):'' )}</div>`:'')+'</div>').join(''):
  '<span class="muted">no vendor edges yet — import the ecosystem workbook via the legacy dashboard ETL, or add org relationships via API</span>';};

/* ── CONTACT PAGE: its own route (#/contact/{id}) — the ABM person 360 ── */
SCREENS.contact=async(el,id)=>{
 if(!id){el.innerHTML='<div class="planned">Open a contact from any list.</div>';return}
 const r=await api('GET','/persons/'+id);
 if(!r.ok){el.innerHTML='<div class="planned">contact not found</div>';return}
 const p=r.data;
 el.innerHTML=`<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
  <h2>${esc(p.full_name)}</h2><span class="muted">${esc(p.current_title||'')}</span>
  ${p.priority_tier?'<span class="badge b-gold">T'+esc(p.priority_tier)+'</span>':''}
  ${p.is_indian_origin?'<span class="badge b-blue">🇮🇳</span>':''}
  ${p.linkedin_url?'<a class="act" style="margin:0;padding:4px 10px;text-decoration:none;background:var(--blue)" href="'+esc(p.linkedin_url)+'" target="_blank">LinkedIn ↗</a>':''}
 </div>
 <div class="sub">${esc(p.primary_email||'')} ${p.mobile?(' · '+esc(p.mobile)):''} — every touch across every channel, in one timeline.</div>
 <div class="tabs" id="cpt"></div><div id="cpb"></div>`;
 const tabs={Activity:cpActivity,Channels:cpChannels,"Log activity":cpLog,History:cpHistory};
 const tb=document.getElementById('cpt');
 Object.keys(tabs).forEach((t,i)=>{const b=document.createElement('button');b.textContent=t;
  b.onclick=()=>{tb.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');tabs[t](document.getElementById('cpb'),id)};
  if(i===0)b.classList.add('on');tb.appendChild(b);});
 cpActivity(document.getElementById('cpb'),id);};
const KIND_ICON={activity:'📌',sequence:'⚙️',email:'✉️',linkedin:'💼',form:'📝',ai:'🤖',touch:'👋'};
async function cpActivity(el,id){
 const r=await api('GET','/bd/persons/'+id+'/timeline');
 const rows=r.ok?(r.data||[]):[];
 el.innerHTML='<div class="card"><h3>Unified activity timeline</h3>'+(rows.length?rows.map(e=>{
  const k=(e.kind||'').split(':')[0];
  return `<div style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px">
  <span>${KIND_ICON[k]||'•'}</span><span class="muted" style="min-width:118px">${String(e.at).slice(0,16).replace('T',' ')}</span>
  <span><b>${esc(e.kind)}</b> ${esc(e.detail||'')} <span class="muted">· ${esc(e.source||'')}</span></span></div>`}).join(''):
  '<span class="muted">no activity yet — log a touch in the "Log activity" tab, or channel updates/emails/sequence events will appear here automatically</span>')+'</div>';}
async function cpChannels(el,id){
 el.innerHTML='<div id="chwrap"><div class="grid g2" id="chgrid"><div class="muted">loading…</div></div><br><button class="act" onclick="saveChannels(\''+id+'\').then(()=>cpChannels(document.getElementById(\'cpb\'),\''+id+'\'))">Save channels</button></div>';
 loadChannels(id);}
function cpLog(el,id){
 el.innerHTML=`<div class="card"><h3>Log an activity (event, seminar, LinkedIn touch, call…)</h3>
 <div class="grid g3"><div><label>Type</label><select id="la_t"><option>linkedin</option><option>event</option><option>seminar</option><option>webinar</option><option>meeting</option><option>call</option><option>whatsapp</option><option>site_visit</option><option>note</option></select></div>
 <div><label>Outcome</label><input id="la_o" placeholder="e.g. positive, met at booth"></div>
 <div><label>Next action</label><input id="la_x" placeholder="e.g. send deck by Sunday"></div></div>
 <label>What happened</label><textarea id="la_n" rows="3" placeholder="Met at Seamless KSA, discussed digital onboarding…"></textarea>
 <button class="act" onclick="cpLogSave('${id}')">Log it</button><pre id="la_out" style="display:none"></pre></div>`;}
window.cpLogSave=async id=>{
 const r=await api('POST','/bd/persons/'+id+'/activities',{activity_type:v2('la_t'),notes:v2('la_n'),
  outcome:v2('la_o')||null,next_action:v2('la_x')||null,owner:'Puneet'});
 if(r.ok){nav('contact/'+id);}else{const o=document.getElementById('la_out');o.style.display='block';o.textContent=JSON.stringify(r.data);}};
async function cpHistory(el,id){
 const r=await api('GET','/crm/records/persons/'+id+'/history');
 const rows=(r.data||[]).slice(-25).reverse();
 el.innerHTML='<div class="card"><h3>Field change history (audit)</h3>'+(rows.length?rows.map(h=>
  `<div style="margin:5px 0;font-size:12.5px"><span class="badge ${h.action==='insert'?'b-green':'b-gold'}">${h.action}</span>
  <span class="muted">${String(h.at).slice(0,16)} · ${esc(h.actor||'system')}</span> ${(h.changed||[]).join(', ')}</div>`).join(''):
  '<span class="muted">no changes recorded</span>')+'</div>';}

SCREENS.connectors=async el=>{
 el.innerHTML='<h2>Connectors</h2><div class="sub">People who open doors — warm paths into the banks.</div><div class="card"><div id="cnl">loading…</div></div>';
 const r=await api('GET','/bd/connectors');
 document.getElementById('cnl').innerHTML=r.ok&&r.data.length?
  '<table><tr><th>Name</th><th>Title</th><th>Organization</th><th>Warmth</th></tr>'+r.data.map(c=>
  `<tr><td><b>${esc(c.name)}</b></td><td class="muted">${esc(c.title||'')}</td><td>${esc(c.org||'')}</td><td>${esc(String(c.warmness??'—'))}</td></tr>`).join('')+'</table>':
  '<span class="muted">no connectors flagged — mark contacts as Connector when editing them</span>';};

SCREENS.initiatives=async el=>{
 el.innerHTML='<h2>Initiatives</h2><div class="sub">Every signal/initiative across all banks — newest first.</div><div class="card"><div id="inl">loading…</div></div>';
 const r=await api('GET','/bd/initiatives');
 document.getElementById('inl').innerHTML=r.ok&&r.data.length?
  '<table><tr><th>Initiative</th><th>Bank</th><th>Type</th><th>Urgency</th><th>Value</th><th>Status</th></tr>'+r.data.map(s=>
  `<tr><td>${s.url?('<a href="'+esc(s.url)+'" target="_blank" style="color:var(--gold);text-decoration:none">'+esc(s.title)+' ↗</a>'):esc(s.title)}</td><td>${esc(s.bank||'—')}</td><td><span class="badge b-blue">${esc(s.type)}</span></td>
  <td>${esc(s.urgency||'')}</td><td class="muted">${esc(s.value||'')}</td>
  <td>${s.is_actioned?'<span class="badge b-green">actioned</span>':s.is_read?'<span class="badge b-dim">read</span>':'<span class="badge b-gold">new</span>'}</td></tr>`).join('')+'</table>':
  '<span class="muted">no signals yet</span>';};

SCREENS.bd=async el=>{
 el.innerHTML=`<h2>BD Outreach</h2><div class="sub">${S.account?('Contacts at '+esc(S.account.name)):'Pick an account for its team, or work the global list.'}</div>
 <div class="card"><div style="display:flex;gap:8px;margin-bottom:10px">
 <select id="bdt" onchange="bdLoad()" style="max-width:160px"><option value="">All tiers</option><option>1</option><option>2</option><option>3</option></select>
 <input id="bdq" placeholder="filter by name/title…" oninput="bdLoad()"></div>
 <div id="bdlist">loading…</div></div>
 <div class="card" style="margin-top:14px"><h3>Update outreach</h3>
 <div class="muted">Click a contact above, then record the touch.</div>
 <div id="bdsel" class="muted" style="margin:8px 0">no contact selected</div>
 <div style="display:flex;gap:8px;flex-wrap:wrap">
 <button class="act" onclick="bdMark('connection_sent')">Connection sent</button>
 <button class="act" onclick="bdMark('connection_accepted')">Accepted</button>
 <button class="act gold" onclick="bdMark('messaged')">Messaged</button></div>
 <label>Response / next step</label><input id="bdn" placeholder="e.g. asked for deck — follow up Sunday">
 <button class="act" onclick="bdNote()">Save note</button><pre id="bdout">—</pre></div>`;
 bdLoad();};
let bdPerson=null;
window.bdLoad=async()=>{
 const url=S.account?('/organizations/'+S.account.id+'/persons'):'/persons';
 const r=await api('GET',url);if(!r.ok)return;
 const t=document.getElementById('bdt').value,q=(document.getElementById('bdq').value||'').toLowerCase();
 const rows=(r.data||[]).filter(p=>(!t||String(p.tier||'')===t)&&(!q||(p.full_name+' '+(p.current_title||'')).toLowerCase().includes(q))).slice(0,60);
 document.getElementById('bdlist').innerHTML=rows.length?'<table><tr><th>Name</th><th>Title</th><th>Tier</th><th>Status</th></tr>'+rows.map(p=>
  `<tr class="click" onclick='bdPick("${p.id}",${JSON.stringify(p.full_name)})'><td>${esc(p.full_name)}</td><td class="muted">${esc(p.current_title||'')}</td><td>${esc(p.tier||'—')}</td><td class="muted">${p.outreach_messaged?'messaged':p.outreach_connection_accepted?'accepted':p.outreach_connection_sent?'sent':'—'}</td></tr>`).join('')+'</table>':'<span class="muted">no matches</span>';};
window.bdPick=(id,name)=>{bdPerson=id;document.getElementById('bdsel').innerHTML='selected: <b style="color:var(--gold)">'+esc(name)+'</b>';};
window.bdMark=async f=>{if(!bdPerson){document.getElementById('bdout').textContent='pick a contact first';return}
 const r=await api('PATCH','/crm/persons/'+bdPerson+'/outreach',{[f]:true,updated_by:'Puneet'});
 document.getElementById('bdout').textContent=JSON.stringify(r.data,null,1);bdLoad();};
window.bdNote=async()=>{if(!bdPerson)return;
 const r=await api('PATCH','/crm/persons/'+bdPerson+'/outreach',{response_notes:document.getElementById('bdn').value,next_step:document.getElementById('bdn').value,updated_by:'Puneet'});
 document.getElementById('bdout').textContent=JSON.stringify(r.data,null,1);};

SCREENS.signals=async el=>{
 el.innerHTML=`<h2>Signal Intelligence</h2><div class="sub">Live acquisition + inbox.</div>
 <div class="grid g2"><div class="card"><h3>Inbox</h3><div id="slist">—</div></div>
 <div class="card"><h3>Collectors</h3><div id="chealth">—</div>
 <button class="act" onclick="colSeed()">Seed KSA sources</button>
 <button class="act gold" onclick="colRun()">Run now</button><pre id="cout">—</pre></div></div>`;
 sigsLoad();colHealth();};
async function sigsLoad(){const r=await api('GET','/signals');
 document.getElementById('slist').innerHTML=r.ok&&r.data.length?'<table>'+r.data.slice(0,20).map(s=>
  `<tr><td>${s.url?('<a href="'+esc(s.url)+'" target="_blank" style="color:var(--gold);text-decoration:none">'+esc(s.title)+' ↗</a>'):esc(s.title)}</td><td><span class="badge b-blue">${esc(s.signal_type)}</span></td></tr>`).join('')+'</table>':'<span class="muted">empty — seed + run collectors</span>';}
async function colHealth(){const r=await api('GET','/abm/collectors');
 document.getElementById('chealth').innerHTML=r.ok&&r.data.length?r.data.map(s=>
  `<div style="margin:4px 0">${esc(s.name)} <span class="badge ${s.enabled?'b-green':'b-red'}">${s.enabled?'on':'off'}</span> <span class="muted">${s.items_ingested} ingested</span></div>`).join(''):'<span class="muted">no sources yet</span>';}
window.colSeed=async()=>{const r=await api('POST','/abm/collectors/seed');document.getElementById('cout').textContent=JSON.stringify(r.data);colHealth();};
window.colRun=async()=>{document.getElementById('cout').textContent='fetching…';
 const r=await api('POST','/abm/collectors/run');document.getElementById('cout').textContent=JSON.stringify(r.data,null,1);colHealth();sigsLoad();};

SCREENS.committee=async el=>{
 if(S.account)return account360(el,S.account.id);
 el.innerHTML='<h2>Buying Committee</h2><div class="planned">Select an account first (Accounts → pick a bank) — the committee module works on the account in context.</div>';};

SCREENS.campaigns=async el=>{
 el.innerHTML=`<h2>Campaigns</h2><div class="sub">Build → pick audience → send (send-safe dry-run) → measure. Merge tags: {first_name} {bank}.</div>
 <div class="card"><button class="act" style="margin:0" onclick="cmpNewForm()">+ New campaign</button><div id="cmpform"></div></div>
 <div class="card" style="margin-top:12px"><h3>All campaigns</h3><div id="cmplist">loading…</div></div>`;
 cmpLoad();};
window.cmpLoad=async()=>{
 const r=await api('GET','/mkt/campaigns');if(!r.ok)return;
 document.getElementById('cmplist').innerHTML=r.data.length?
  '<table><tr><th>Campaign</th><th>Subject</th><th>Status</th><th>Sent</th><th>Opens</th><th>Clicks</th><th>Actions</th></tr>'+r.data.map(c=>{
  const rep=c.report||{};
  return `<tr><td><b>${esc(c.name)}</b></td><td class="muted">${esc(c.subject||'')}</td>
  <td><span class="badge ${c.status==='sent'?'b-green':'b-dim'}">${esc(c.status)}</span></td>
  <td>${rep.sent??'—'}</td><td>${rep.unique_opens??rep.opens??'—'}</td><td>${rep.unique_clicks??rep.clicks??'—'}</td>
  <td style="white-space:nowrap"><button class="act" style="margin:0;padding:3px 8px" onclick='cmpSend("${c.id}")'>send (dry-run)</button>
  <button class="act gold" style="margin:0;padding:3px 8px" onclick='cmpReport("${c.id}")'>report</button></td></tr>`}).join('')+'</table>'+
  '<pre id="cmpout" style="display:none"></pre>':'<span class="muted">no campaigns yet</span>';};
window.cmpNewForm=async()=>{
 const[segs,orgs]=await Promise.all([api('GET','/mkt/segments-brief'),api('GET','/organizations')]);
 if(orgs.ok)_orgsCache=orgs.data||[];
 document.getElementById('cmpform').innerHTML=`<div style="margin-top:10px">
 <div class="grid g2"><div><label>Campaign name</label><input id="cm_n" value="KSA outreach ${new Date().toISOString().slice(5,10)}"></div>
 <div><label>Choose audience</label><select id="cm_a" onchange="cmpAudPreview()">
   <optgroup label="Built-in audiences">
    <option value="all">Everyone (active contacts)</option>
    <option value="tier1">Tier 1 contacts</option>
    <option value="tier2">Tier 2 contacts</option>
    <option value="c_suite">C-suite only</option>
    <option value="indian">Indian-origin contacts</option></optgroup>
   <optgroup label="By bank">${_orgsCache.map(o=>`<option value="bank:${o.id}">${esc(o.canonical_name)}</option>`).join('')}</optgroup>
   ${(segs.data||[]).length?'<optgroup label="Saved segments">'+segs.data.map(s=>`<option value="seg:${s.id}">${esc(s.name)} (${s.size})</option>`).join('')+'</optgroup>':''}
 </select></div></div>
 <div id="cm_prev" class="muted" style="margin:6px 0">—</div>
 <label>Subject</label><input id="cm_s" value="Partnering on digital onboarding, {bank}">
 <label>Body (merge tags: {first_name} {bank})</label><textarea id="cm_b" rows="5">Dear {first_name},

We have been following {bank}'s digital initiatives closely...</textarea>
 <button class="act" onclick="cmpCreate()">Create campaign →</button>
 <button class="act" style="background:var(--line)" onclick="document.getElementById('cmpform').innerHTML=''">Cancel</button>
 <div class="muted" style="margin-top:6px">Send-safe: sending builds, personalizes and logs every message with analytics, but nothing reaches a real inbox until SES credentials are configured. C-suite is always held for human review.</div></div>`;
 cmpAudPreview();};
window.cmpAudPreview=async()=>{
 const v=document.getElementById('cm_a').value;
 let body={name:'preview',builtin:v};
 if(v.startsWith('seg:'))body={name:'preview',segment_id:v.slice(4),builtin:null};
 else if(v.startsWith('bank:'))body={name:'preview',builtin:v};
 // create a throwaway audience just to count — cheap
 const a=await api('POST','/mkt/audiences',body);
 if(a.ok)document.getElementById('cm_prev').innerHTML='👥 This audience has <b style="color:var(--gold)">'+a.data.members+'</b> contacts';
 window._lastAud=a.ok?a.data.id:null;};
window.cmpCreate=async()=>{
 if(!window._lastAud){alert('pick an audience');return}
 const r=await api('POST','/mkt/campaigns',{name:v2('cm_n'),audience_id:window._lastAud,subject:v2('cm_s'),body:v2('cm_b')});
 if(r.ok){document.getElementById('cmpform').innerHTML='';nav('campaign/'+r.data.id);}else alert(JSON.stringify(r.data));};
window.cmpSend=async id=>{await api('POST','/mkt/campaigns/'+id+'/send');nav('campaign/'+id);};
window.cmpReport=id=>nav('campaign/'+id);

/* Campaign detail page (its own route) */
SCREENS.campaign=async(el,id)=>{
 if(!id){nav('campaigns');return}
 const list=await api('GET','/mkt/campaigns');
 const c=(list.data||[]).find(x=>x.id===id)||{name:'campaign'};
 const rep=c.report||{};
 el.innerHTML=`<div style="display:flex;align-items:center;gap:10px"><h2>${esc(c.name)}</h2>
  <span class="badge ${c.status==='sent'?'b-green':'b-dim'}">${esc(c.status||'')}</span>
  <button class="act" style="margin:0" onclick="cmpSend('${id}')">Send (dry-run)</button>
  <button class="act" style="margin:0;background:var(--line)" onclick="nav('campaigns')">← all campaigns</button></div>
 <div class="sub">${esc(c.subject||'')}</div>
 <div class="grid g4">${kpi('Sent',rep.sent??'—','')+kpi('Opens',rep.unique_opens??rep.opens??'—','')+kpi('Clicks',rep.unique_clicks??rep.clicks??'—','')+kpi('Replies',rep.replies??'—','')}</div>
 <div class="card" style="margin-top:12px"><h3>Recipients</h3><div id="cmr">loading…</div></div>`;
 const m=await api('GET','/mkt/campaigns/'+id+'/messages');
 document.getElementById('cmr').innerHTML=(m.ok&&m.data.length)?
  '<table><tr><th>Contact</th><th>Email</th><th>Variant</th><th>Status</th><th>Events</th></tr>'+m.data.map(x=>
  `<tr><td>${esc(x.person||'')}</td><td class="muted">${esc(x.to||'')}</td><td>${esc(x.variant||'')}</td>
  <td><span class="badge b-dim">${esc(x.status||'')}</span></td><td class="muted">${(x.events||[]).join(', ')}</td></tr>`).join('')+'</table>':
  '<span class="muted">no messages yet — click "Send (dry-run)" to build the recipient list</span>';};

SCREENS.journeys=async el=>{
 el.innerHTML=`<h2>Journeys</h2><div class="sub">Multi-step orchestration: send → wait → branch.</div>
 <div class="grid g2"><div class="card"><h3>Create demo journey + enroll</h3>
 <label>Name</label><input id="jn" value="Onboarding KSA">
 <button class="act" onclick="jMake()">Create</button>
 <label>Person id (any)</label><input id="jp" value="demo-person">
 <button class="act" onclick="jEnroll()">Enroll</button><pre id="jout">—</pre></div>
 <div class="card"><h3>Runner</h3><button class="act gold" onclick="jTick()">Run tick</button><pre id="jtick">—</pre></div></div>`;};
let lastJ=null;
window.jMake=async()=>{const nodes=[{id:"n1",type:"send",content:"welcome",next:"n2"},{id:"n2",type:"wait",hours:24,next:"n3"},{id:"n3",type:"branch",on:"opened",yes:"n4",no:"n5"},{id:"n4",type:"send",content:"thanks",next:"n6"},{id:"n5",type:"send",content:"nudge",next:"n6"},{id:"n6",type:"exit"}];
 const r=await api('POST','/mkt/journeys',{name:document.getElementById('jn').value,nodes});
 if(r.ok)lastJ=r.data.id;document.getElementById('jout').textContent=JSON.stringify(r.data,null,1);};
window.jEnroll=async()=>{const r=await api('POST','/mkt/journeys/'+lastJ+'/enroll',{person_id:document.getElementById('jp').value});
 document.getElementById('jout').textContent=JSON.stringify(r.data,null,1);};
window.jTick=async()=>{const r=await api('POST','/mkt/journeys/tick');document.getElementById('jtick').textContent=JSON.stringify(r.data,null,1);};

SCREENS.segments=async el=>{
 el.innerHTML=`<h2>Segments</h2><div class="sub">Dynamic conditions or static lists.</div>
 <div class="card"><h3>Create dynamic segment</h3>
 <label>Name</label><input id="sgn" value="Tier-1 repliers">
 <label>Conditions (JSON)</label><textarea id="sgc" rows="3">[{"field":"tier","op":"eq","value":"1"},{"field":"has_replied","op":"eq","value":true}]</textarea>
 <button class="act" onclick="sgMake()">Create + evaluate</button><pre id="sgout">—</pre></div>`;};
window.sgMake=async()=>{let conds;try{conds=JSON.parse(document.getElementById('sgc').value)}catch(e){document.getElementById('sgout').textContent='bad JSON';return}
 const r=await api('POST','/crm/segments',{name:document.getElementById('sgn').value,conditions:conds});
 if(!r.ok){document.getElementById('sgout').textContent=JSON.stringify(r.data);return}
 const s=await api('GET','/crm/segments/'+r.data.id);document.getElementById('sgout').textContent=JSON.stringify(s.data,null,1);};

SCREENS.email=async el=>{
 el.innerHTML='<h2>Email Analytics</h2><div class="sub">Sends, opens, clicks, CTOR — across campaigns.</div><div class="grid g3" id="ek"></div><div class="card" style="margin-top:14px"><h3>Per campaign</h3><div id="ec">—</div></div>';
 const r=await api('GET','/analytics/email');if(!r.ok)return;const d=r.data,t=d.totals,ra=d.rates;
 document.getElementById('ek').innerHTML=kpi('Sent',t.sent,'delivered '+ra.delivery_rate+'%')+kpi('Open rate',ra.open_rate+'%',t.unique_opens+' unique')+kpi('CTOR',ra.ctor+'%','bounces '+t.bounces);
 document.getElementById('ec').innerHTML=d.per_campaign.length?'<table><tr><th>Campaign</th><th>Sent</th><th>Open%</th><th>Click%</th></tr>'+d.per_campaign.map(c=>
  `<tr><td>${esc(c.campaign)}</td><td>${c.sent}</td><td>${c.open_rate}</td><td>${c.click_rate}</td></tr>`).join('')+'</table>':'<span class="muted">no sends in window</span>';};

let _pipe={view:'board',q:'',bank:'',min:0,sort:'amount'};
SCREENS.pipeline=async el=>{
 if(!_orgsCache.length){const rr=await api('GET','/organizations');_orgsCache=rr.ok?rr.data:[];}
 el.innerHTML=`<h2>Pipeline</h2><div class="sub">Board or table · filter · sort · export — every control acts instantly.</div>
 <div class="grid g3" id="pk"></div>
 <div class="card" style="margin-top:12px"><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
  <button class="act" style="margin:0" onclick="dealNewForm()">+ New deal</button>
  <button class="act gold" style="margin:0" id="pv_b" onclick="_pipe.view='board';kanbanLoad()">▦ Board</button>
  <button class="act" style="margin:0;background:var(--line)" id="pv_t" onclick="_pipe.view='table';kanbanLoad()">☰ Table</button>
  <input placeholder="🔍 search deals…" style="max-width:170px" oninput="_pipe.q=this.value;kanbanLoad()">
  <select style="max-width:170px" onchange="_pipe.bank=this.value;kanbanLoad()"><option value="">All banks</option>${_orgsCache.map(o=>`<option value="${o.id}">${esc(o.canonical_name)}</option>`).join('')}</select>
  <select style="max-width:150px" onchange="_pipe.min=parseFloat(this.value)||0;kanbanLoad()"><option value="0">Any amount</option><option value="100000">≥ SAR 100k</option><option value="500000">≥ SAR 500k</option><option value="1000000">≥ SAR 1M</option></select>
  <select style="max-width:150px" onchange="_pipe.sort=this.value;kanbanLoad()"><option value="amount">Sort: amount ↓</option><option value="bank">Sort: bank A-Z</option></select>
  <button class="act" style="margin:0" onclick="dealExport()">⬇ Export CSV</button></div>
 <div id="dform"></div></div>
 <div id="kanban" style="display:flex;gap:10px;overflow-x:auto;margin-top:12px;align-items:flex-start"></div>
 <div id="ptable" style="margin-top:12px"></div>`;
 const e=await api('GET','/dashboard/executive');
 if(e.ok)document.getElementById('pk').innerHTML=kpi('Pipeline',e.data.pipeline_sar,'')+kpi('Weighted',e.data.weighted_sar,'')+kpi('Open deals',e.data.open_deals,'');
 kanbanLoad();};
function _pipeFilter(cards){
 let out=cards.filter(c=>(!_pipe.q||((c.bank||'')+' '+(c.next_step||'')+' '+(c.notes||'')).toLowerCase().includes(_pipe.q.toLowerCase()))
  &&(!_pipe.bank||c.org_id===_pipe.bank)&&(c.amount_sar>=_pipe.min));
 out.sort((a,b)=>_pipe.sort==='bank'?String(a.bank).localeCompare(String(b.bank)):b.amount_sar-a.amount_sar);
 return out;}
window.dealExport=async()=>{
 const r=await api('GET','/bd/deals/board');if(!r.ok){alert('export failed — sign in first');return}
 let csv='stage,bank,amount_sar,next_step,notes\n';let n=0;
 for(const s of r.data.stages)for(const c of _pipeFilter(r.data.columns[s]||[])){
  csv+=[s,JSON.stringify(c.bank||''),c.amount_sar,JSON.stringify(c.next_step||''),JSON.stringify(c.notes||'')].join(',')+'\n';n++;}
 const blob=new Blob([csv],{type:'text/csv'});const u=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=u;a.download='pipeline_'+n+'deals.csv';a.click();URL.revokeObjectURL(u);};
window.kanbanLoad=async()=>{
 const r=await api('GET','/bd/deals/board');if(!r.ok)return;const d=r.data;
 document.getElementById('pv_b').style.background=_pipe.view==='board'?'var(--gold)':'var(--line)';
 document.getElementById('pv_t').style.background=_pipe.view==='table'?'var(--gold)':'var(--line)';
 if(_pipe.view==='table'){
  document.getElementById('kanban').innerHTML='';
  let rows=[];for(const s of d.stages)for(const c of _pipeFilter(d.columns[s]||[]))rows.push({...c,stage:s});
  document.getElementById('ptable').innerHTML='<div class="card"><table><tr><th>Bank</th><th>Stage</th><th>Amount (SAR)</th><th>Next step</th><th></th></tr>'+
   rows.map(c=>`<tr><td><b>${esc(c.bank)}</b></td><td>${esc(c.stage)}</td><td>${c.amount_sar.toLocaleString()}</td><td class="muted">${esc(c.next_step||'')}</td>
   <td><button class="act gold" style="margin:0;padding:3px 8px" onclick='dealEdit(${JSON.stringify(c)})'>edit</button></td></tr>`).join('')+'</table></div>';
  return;}
 document.getElementById('ptable').innerHTML='';
 document.getElementById('kanban').innerHTML=d.stages.map(s=>{
  const cards=_pipeFilter(d.columns[s]||[]);
  const col=s==='Won'?'var(--green)':s==='Lost'?'var(--red)':'var(--line)';
  return `<div style="min-width:200px;flex:1;background:var(--panel);border:1px solid ${col};border-radius:12px;padding:10px">
  <div style="font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">${s}
   <span style="float:inline-end">${cards.length} · SAR ${Math.round(d.totals_sar[s]).toLocaleString()}</span></div>`+
  cards.map(c=>{
   const i=d.stages.indexOf(s);
   return `<div class="card" style="padding:10px;margin-bottom:8px">
   <b style="font-size:12.5px">${esc(c.bank)}</b><br>
   <span class="muted" style="font-size:12px">SAR ${c.amount_sar.toLocaleString()}${c.next_step?' · '+esc(c.next_step.slice(0,26)):''}</span>
   <div style="margin-top:6px;display:flex;gap:4px">
   ${i>0?`<button class="act" style="margin:0;padding:2px 8px" onclick='dealMove("${c.id}","${d.stages[i-1]}")'>◀</button>`:''}
   ${i<d.stages.length-1?`<button class="act" style="margin:0;padding:2px 8px" onclick='dealMove("${c.id}","${d.stages[i+1]}")'>▶</button>`:''}
   <button class="act gold" style="margin:0;padding:2px 8px" onclick='dealEdit(${JSON.stringify(c)})'>edit</button></div></div>`}).join('')+'</div>';}).join('');};
window.dealMove=async(id,stage)=>{await api('PATCH','/bd/deals/'+id,{fields:{stage}});kanbanLoad();};
window.dealNewForm=async()=>{
 if(!_orgsCache.length){const r=await api('GET','/organizations');_orgsCache=r.ok?r.data:[];}
 document.getElementById('dform').innerHTML=`<div class="grid g3" style="margin-top:10px">
 <div><label>Bank</label><select id="dn_o">${_orgsCache.map(o=>`<option value="${o.id}" ${S.account&&S.account.id===o.id?'selected':''}>${esc(o.canonical_name)}</option>`).join('')}</select></div>
 <div><label>Amount (SAR)</label><input id="dn_a" value="500000"></div>
 <div><label>Stage</label><select id="dn_s"><option>Identified</option><option>Qualified</option><option>Proposal</option><option>Negotiation</option></select></div></div>
 <label>Next step</label><input id="dn_n">
 <button class="act" onclick="dealNew()">Create deal</button>`;};
window.dealNew=async()=>{
 const r=await api('POST','/bd/deals',{org_id:v2('dn_o'),stage:v2('dn_s'),
  amount_sar:parseFloat(v2('dn_a'))||null,next_step:v2('dn_n')||null});
 if(r.ok){document.getElementById('dform').innerHTML='';kanbanLoad();}};
window.dealEdit=c=>{document.getElementById('dform').innerHTML=`<div class="grid g3" style="margin-top:10px">
 <div><label>Amount (SAR)</label><input id="de_a" value="${c.amount_sar}"></div>
 <div><label>Next step</label><input id="de_n" value="${esc(c.next_step||'')}"></div>
 <div><label>Notes</label><input id="de_x" value="${esc(c.notes||'')}"></div></div>
 <button class="act" onclick='dealSave("${c.id}")'>Save</button>`;};
window.dealSave=async id=>{
 await api('PATCH','/bd/deals/'+id,{fields:{amount_sar:parseFloat(v2('de_a'))||null,next_step:v2('de_n')||null,notes:v2('de_x')||null}});
 document.getElementById('dform').innerHTML='';kanbanLoad();};

SCREENS.meetings=async el=>{
 el.innerHTML=`<h2>Meetings</h2><div class="sub">Schedule with conflict detection; export to any calendar (.ics).</div>
 <div class="grid g2"><div class="card"><h3>Schedule</h3>
 <label>Title</label><input id="mtt" value="Discovery call">
 <label>Start (YYYY-MM-DDTHH:MM)</label><input id="mts" value="">
 <label>Owner</label><input id="mto" value="Puneet">
 <button class="act" onclick="mMake()">Schedule</button><pre id="mout">—</pre></div>
 <div class="card"><h3>Upcoming</h3><div id="mup">—</div></div></div>`;
 const d=new Date(Date.now()+864e5);document.getElementById('mts').value=d.toISOString().slice(0,16);
 mUp();};
async function mUp(){const r=await api('GET','/crm/meetings/upcoming');
 document.getElementById('mup').innerHTML=r.ok&&r.data.length?r.data.map(m=>
  `<div style="margin:5px 0">${esc(m.title)} <span class="muted">${m.starts_at.replace('T',' ').slice(0,16)} · ${esc(m.owner)}</span> <a style="color:var(--gold)" href="/crm/meetings/${m.id}/ics">.ics</a></div>`).join(''):'<span class="muted">nothing scheduled</span>';}
window.mMake=async()=>{const r=await api('POST','/crm/meetings',{title:document.getElementById('mtt').value,
 starts_at:document.getElementById('mts').value+':00',owner:document.getElementById('mto').value,
 org_id:S.account?S.account.id:null});
 document.getElementById('mout').textContent=r.ok?'scheduled':'conflict/err: '+JSON.stringify(r.data);mUp();};

SCREENS.tasks=async el=>{
 el.innerHTML=`<h2>Tasks</h2><div class="sub">My day.</div>
 <div class="card"><label>Assignee</label><input id="tas" value="Puneet">
 <button class="act" onclick="tDay()">Load my day</button><pre id="tday">—</pre></div>`;};
window.tDay=async()=>{const r=await api('GET','/crm/tasks/my-day/'+encodeURIComponent(document.getElementById('tas').value));
 document.getElementById('tday').textContent=JSON.stringify(r.data,null,1);};

SCREENS.sequences=async el=>{
 el.innerHTML='<h2>Sequences</h2><div class="sub">Automated cadences (send-safe).</div><div class="card"><div id="sq">—</div></div>';
 const r=await api('GET','/sequences');
 document.getElementById('sq').innerHTML=r.ok&&r.data.length?'<table><tr><th>Name</th><th>Type</th></tr>'+r.data.map(s=>
  `<tr><td>${esc(s.name)}</td><td class="muted">${esc(s.relationship_type||'')}</td></tr>`).join('')+'</table>':'<span class="muted">none yet</span>';};

SCREENS.quotes=async el=>{
 el.innerHTML=`<h2>Quotes & Products</h2><div class="sub">Money-correct CPQ in SAR.</div>
 <div class="grid g2"><div class="card"><h3>Quick quote</h3>
 <label>Name</label><input id="qn" value="Q-${Date.now()%1000}">
 <label>Line description</label><input id="qd" value="Vahana License">
 <label>Qty × unit (SAR)</label><div style="display:flex;gap:8px"><input id="qq" value="3" style="width:70px"><input id="qu" value="100000"></div>
 <button class="act" onclick="qMake()">Create quote</button><pre id="qout">—</pre></div>
 <div class="card"><h3>Custom objects / products live via API</h3><div class="muted">POST /crm/products · /crm/price-books · /crm/quotes — full reference at /docs</div></div></div>`;};
window.qMake=async()=>{const r=await api('POST','/crm/quotes',{name:document.getElementById('qn').value,org_id:S.account?S.account.id:null});
 if(!r.ok){document.getElementById('qout').textContent='err';return}
 await api('POST',`/crm/quotes/${r.data.id}/lines`,{description:document.getElementById('qd').value,
  quantity:parseInt(document.getElementById('qq').value),unit_amount_minor:Math.round(parseFloat(document.getElementById('qu').value)*100)});
 const s=await api('GET','/crm/quotes/'+r.data.id);document.getElementById('qout').textContent=JSON.stringify(s.data,null,1);};

SCREENS.objects=async el=>{
 el.innerHTML=`<h2>Custom Objects</h2><div class="sub">Define your own record types.</div>
 <div class="card"><div id="odefs">—</div>
 <label>Define (key)</label><input id="ok" value="regulatory_case">
 <label>Label</label><input id="ol" value="Regulatory Case">
 <button class="act" onclick="oMake()">Define type</button><pre id="oout">—</pre></div>`;
 oList();};
async function oList(){const r=await api('GET','/crm/objects');
 document.getElementById('odefs').innerHTML=r.ok&&r.data.length?r.data.map(o=>`<span class="badge b-green" style="margin:3px">${esc(o.key)}</span>`).join(''):'<span class="muted">none defined</span>';}
window.oMake=async()=>{const r=await api('POST','/crm/objects',{key:document.getElementById('ok').value,
 label:document.getElementById('ol').value,schema:[{key:"case_no",type:"text",required:true}]});
 document.getElementById('oout').textContent=JSON.stringify(r.data,null,1);oList();};

SCREENS.workflow=async el=>{
 el.innerHTML='<h2>Workflow</h2><div class="sub">Durable execution health.</div><div class="card"><h3>Dead letters</h3><div id="wdl">—</div></div>';
 const r=await api('GET','/workflow/dead-letters');
 document.getElementById('wdl').innerHTML=r.ok&&r.data.length?'<table><tr><th>Run</th><th>Node</th><th>Error</th></tr>'+r.data.map(d=>
  `<tr><td class="muted">${d.run_id.slice(0,8)}</td><td>${esc(d.node_id)}</td><td class="muted">${esc(d.error||'')}</td></tr>`).join('')+'</table>':'<span class="badge b-green">queue healthy — no dead letters</span>';};

SCREENS.ai=async el=>{
 el.innerHTML=`<h2>AI Center</h2><div class="sub">Prompt registry, versioning, cost tracking.</div>
 <div class="grid g2"><div class="card"><h3>Prompt registry</h3><div id="aip">—</div></div>
 <div class="card"><h3>Analytics</h3><div id="aia">—</div></div></div>
 <div class="card" style="margin-top:14px"><h3>Test console</h3>
 <label>Prompt</label><select id="aisel"></select>
 <label>Variables (JSON)</label><textarea id="aivars" rows="2">{"role":"CTO","segment":"tier1","signal":"core banking RFP","angle":"onboarding"}</textarea>
 <button class="act" onclick="aiTest()">Call</button><pre id="aires">—</pre></div>`;
 const p=await api('GET','/ai/prompts');
 if(p.ok){document.getElementById('aip').innerHTML=Object.entries(p.data).map(([n,vs])=>
  `<div style="margin:5px 0">${n} ${vs.map(v=>`<span class="badge ${v.active?'b-gold':'b-dim'}">v${v.version}</span>`).join(' ')}</div>`).join('');
  document.getElementById('aisel').innerHTML=Object.keys(p.data).map(n=>`<option>${n}</option>`).join('');}
 const a=await api('GET','/ai/analytics');
 if(a.ok)document.getElementById('aia').innerHTML=kpi(a.data.live?'LIVE model':'Dry-run',a.data.total_calls+' calls','$'+a.data.total_cost_usd+' total');};
window.aiTest=async()=>{let vars;try{vars=JSON.parse(document.getElementById('aivars').value)}catch(e){vars={}}
 const r=await api('POST','/ai/call',{prompt_name:document.getElementById('aisel').value,variables:vars});
 document.getElementById('aires').textContent=r.ok?r.data.text+'\n\n[provider: '+r.data.provider+', v'+r.data.prompt_version+', $'+r.data.cost_usd+']':'error';};

SCREENS.agents=el=>{el.innerHTML='<h2>Agents</h2><div class="planned">Autonomous agents are the next build phase (PM2): research → committee → outreach pipelines over the LLM core. The prompt registry, cost tracking, and guardrails they will run on are live today in the AI Center. Nothing here is faked — this module appears when the capability is real.</div>';};

SCREENS.reports=async el=>{
 el.innerHTML=`<h2>Reports</h2><div class="sub">Custom report builder.</div>
 <div class="card"><label>Entity</label><select id="re"><option>opportunities</option><option>persons</option><option>organizations</option><option>signals</option></select>
 <label>Group by</label><input id="rg" value="stage">
 <label>Metric</label><select id="rm"><option>count</option><option>sum</option></select>
 <label>Metric field (for sum)</label><input id="rf" value="amount_minor">
 <button class="act" onclick="rRun()">Run</button><div id="rout" style="margin-top:10px">—</div></div>`;};
window.rRun=async()=>{const r=await api('POST','/reports/run',{entity:document.getElementById('re').value,
 group_by:document.getElementById('rg').value||null,metric:document.getElementById('rm').value,
 metric_field:document.getElementById('rf').value||null});
 if(!r.ok){document.getElementById('rout').textContent='err';return}
 const mx=Math.max(...r.data.data.map(d=>d.value),1);
 document.getElementById('rout').innerHTML=r.data.data.map(d=>
  `<div style="margin:5px 0">${esc(d.group)} <span class="muted">${d.value.toLocaleString()}</span><div class="bar"><i style="width:${100*d.value/mx}%"></i></div></div>`).join('');};

SCREENS.analytics=async el=>{
 el.innerHTML=`<h2>Cohorts & Trends</h2>
 <div class="grid g2"><div class="card"><h3>Time series</h3><label>Event</label><input id="ane" value="signup">
 <button class="act" onclick="anTs()">Query</button><pre id="ants">—</pre></div>
 <div class="card"><h3>Cohort retention</h3><label>Cohort / return events</label>
 <div style="display:flex;gap:8px"><input id="anc" value="signup"><input id="anr" value="active"></div>
 <button class="act gold" onclick="anCo()">Compute</button><pre id="anco">—</pre></div></div>`;};
window.anTs=async()=>{const r=await api('GET','/analytics/timeseries?event_type='+document.getElementById('ane').value+'&since_days=28&bucket_days=7');
 document.getElementById('ants').textContent=JSON.stringify(r.data,null,1);};
window.anCo=async()=>{const r=await api('GET','/analytics/cohort-retention?cohort_event='+document.getElementById('anc').value+'&return_event='+document.getElementById('anr').value);
 document.getElementById('anco').textContent=JSON.stringify(r.data,null,1);};

SCREENS.parity=async el=>{
 el.innerHTML='<h2>Feature Parity</h2><div class="sub">Live from the capability registry.</div><div class="grid g2"><div class="card"><h3>Competitors</h3><div id="pc">—</div></div><div class="card"><h3>Completion</h3><div id="ps">—</div></div></div>';
 const r=await api('GET','/platform/parity');if(!r.ok)return;const d=r.data;
 document.getElementById('pc').innerHTML=Object.entries(d.competitor_parity).map(([k,v])=>
  `<div style="margin:4px 0">${k} <span class="muted">${v}%</span><div class="bar"><i style="width:${v}%"></i></div></div>`).join('');
 document.getElementById('ps').innerHTML=`<div class="kpi">${d.summary.completion_pct}%</div><div class="muted">${d.summary.total_capabilities} capabilities</div>`;};

SCREENS.developer=async el=>{
 el.innerHTML=`<h2>Developer</h2><div class="sub">API keys, webhooks, OpenAPI.</div>
 <div class="grid g2"><div class="card"><h3>API keys</h3>
 <label>Name</label><input id="dkn" value="integration">
 <button class="act" onclick="dKey()">Create (shown once)</button>
 <button class="act gold" onclick="dKeys()">List</button><pre id="dkout">—</pre></div>
 <div class="card"><h3>Webhooks</h3><label>URL</label><input id="dwu" value="https://example.invalid/hook">
 <button class="act" onclick="dHook()">Subscribe</button><pre id="dwout">—</pre>
 <div class="muted" style="margin-top:8px">Full API reference: <a style="color:var(--gold)" href="/docs" target="_blank">/docs</a></div></div></div>`;};
window.dKey=async()=>{const r=await api('POST','/dev/api-keys',{name:document.getElementById('dkn').value,scopes:["crm.read"]});
 document.getElementById('dkout').textContent=JSON.stringify(r.data,null,1);};
window.dKeys=async()=>{const r=await api('GET','/dev/api-keys');document.getElementById('dkout').textContent=JSON.stringify(r.data,null,1);};
window.dHook=async()=>{const r=await api('POST','/dev/webhooks',{url:document.getElementById('dwu').value,event_types:[]});
 document.getElementById('dwout').textContent=JSON.stringify(r.data,null,1);};

SCREENS.compliance=async el=>{
 el.innerHTML=`<h2>Compliance (PDPL)</h2>
 <div class="grid g3"><div class="card"><h3>Export subject</h3><label>Person id</label><input id="cpe">
 <button class="act" onclick="cpE()">Export</button><pre id="cpeo">—</pre></div>
 <div class="card"><h3>Consent</h3><label>Person id</label><input id="cpc">
 <select id="cpcs"><option>granted</option><option>withdrawn</option></select>
 <button class="act gold" onclick="cpC()">Set</button><pre id="cpco">—</pre></div>
 <div class="card"><h3>Erase</h3><label>Person id</label><input id="cpd">
 <button class="act" style="background:var(--red)" onclick="cpD()">Erase</button><pre id="cpdo">—</pre></div></div>`;};
window.cpE=async()=>{const r=await api('GET','/compliance/subjects/'+document.getElementById('cpe').value+'/export');document.getElementById('cpeo').textContent=JSON.stringify(r.data,null,1);};
window.cpC=async()=>{const r=await api('POST','/compliance/subjects/'+document.getElementById('cpc').value+'/consent',{status:document.getElementById('cpcs').value});document.getElementById('cpco').textContent=JSON.stringify(r.data,null,1);};
window.cpD=async()=>{const r=await api('POST','/compliance/subjects/'+document.getElementById('cpd').value+'/erase');document.getElementById('cpdo').textContent=JSON.stringify(r.data,null,1);};

SCREENS.health=async el=>{
 el.innerHTML='<h2>Health</h2><div class="grid g2" id="hl"></div>';
 const r=await api('GET','/health/ready');
 document.getElementById('hl').innerHTML=kpi('API + DB',r.ok?'READY':'DOWN',JSON.stringify(r.data))+
  `<div class="card"><h3>Probes</h3><div class="muted">/health/live · /health/ready · /metrics (Prometheus)</div></div>`;};

SCREENS.settings=async el=>{
 el.innerHTML=`<h2>Settings</h2>
 <div class="grid g2"><div class="card"><h3>Sign in</h3>
 <label>Email</label><input id="se"><label>Password</label><input id="sp" type="password">
 <button class="act" onclick="sLogin()">Sign in</button><div class="muted" id="sst" style="margin-top:8px">${S.token?'token saved ✓':'not signed in'}</div></div>
 <div class="card"><h3>Preferences</h3>
 <div class="muted">Layout: <button class="act gold" style="margin-top:6px" onclick="toggleRTL()">Toggle Arabic RTL</button></div>
 <div class="muted" style="margin-top:10px">Legacy console: <a style="color:var(--gold)" href="/legacy">/legacy</a></div>
 <button class="act" style="background:var(--red);margin-top:14px" onclick="sOut()">Sign out</button></div></div>`;};
window.sLogin=async()=>{const r=await api('POST','/auth/login',{email:document.getElementById('se').value,password:document.getElementById('sp').value});
 if(r.ok&&r.data.access_token){S.token=r.data.access_token;localStorage.setItem('drip_token',S.token);
  document.getElementById('sst').textContent='signed in ✓ ('+r.data.role+')';document.getElementById('who').textContent=r.data.role;}
 else document.getElementById('sst').textContent=(r.data&&r.data.detail)||'failed';};
window.sOut=()=>{S.token=null;localStorage.removeItem('drip_token');document.getElementById('sst').textContent='signed out';document.getElementById('who').textContent='Sign in';};

/* ═══════════ boot ═══════════ */
buildNav();ctx();route();notifDot();
if(S.token)document.getElementById('who').textContent='●';
</script></body></html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def drip_os():
    return HTMLResponse(_OS)


@router.get("/app", include_in_schema=False)
def app_redirect():
    return RedirectResponse("/", status_code=307)
