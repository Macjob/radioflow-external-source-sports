import json


def render_landing_html() -> str:
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RadioFlow Addons</title><style>body{margin:0;background:#080713;color:#f5f2ff;font:16px system-ui}main{max-width:900px;margin:auto;padding:64px 24px}.card{border:1px solid #30274d;border-radius:20px;background:#100e1f;padding:32px}h1{font-size:36px}.pill{display:inline-block;color:#b997ff;background:#25134b;padding:7px 12px;border-radius:99px}p{color:#b9b3cc;line-height:1.6}</style></head><body><main><span class="pill">RadioFlow Addons</span><div class="card"><h1>Sports Notifications</h1><p>Configura ligas y equipos desde la web. RadioFlow instala el addon y recibe sólo sugerencias asociadas a tu configuración opaca.</p><p>Las credenciales y la infraestructura del proveedor deportivo permanecen en el backend alojado.</p></div></main></body></html>"""


def render_configuration_html(base_url: str, session_id: str, current: dict | None) -> str:
    current_json = json.dumps(current or {}, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sports Notifications</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#080713;color:#f7f4ff;font:15px system-ui}}
main{{max-width:820px;margin:auto;padding:36px 20px}}
.head{{display:flex;gap:16px;align-items:center;margin-bottom:24px}}
.icon{{display:grid;place-items:center;width:52px;height:52px;border-radius:16px;background:#651dff;font-size:28px}}
.steps{{display:flex;gap:8px;margin:24px 0}}
.steps span{{flex:1;border-top:3px solid #30264f;padding-top:8px;color:#8d86a3}}
.steps .on{{border-color:#7c2cff;color:#fff}}
.card{{border:1px solid #2d2744;border-radius:18px;background:#100e1e;padding:24px}}
label{{display:block;margin:16px 0 8px;font-weight:700}}
select{{width:100%;padding:12px;border:1px solid #3a3156;border-radius:10px;background:#17132a;color:#fff}}
#teams{{display:grid;gap:8px;margin-top:12px;max-height:330px;overflow:auto}}
.team,.select-all{{display:flex;align-items:center;gap:10px;padding:11px;border:1px solid #2d2744;border-radius:10px;background:#151225}}
.select-all{{justify-content:space-between;margin-top:12px;background:#1b1630}}
.select-all span:first-child{{display:flex;align-items:center;gap:10px}}
.selection-count{{color:#9d96b1;font-size:13px;font-weight:600}}
[hidden]{{display:none!important}}
button{{margin-top:20px;width:100%;padding:13px;border:0;border-radius:10px;background:#6d20ff;color:white;font-weight:800;cursor:pointer}}
button:disabled{{opacity:.5}}
.muted{{color:#9d96b1}}
.error{{color:#ff8b9b}}
</style>
</head>
<body>
<main>
  <div class="head"><div class="icon">⚽</div><div><h1>Sports Notifications</h1><div class="muted">Configuración del addon</div></div></div>
  <div class="steps"><span class="on">1 Competición</span><span class="on">2 Equipos</span><span class="on">3 Evento</span><span>4 Instalar</span></div>
  <div class="card">
    <label for="league">Liga o competición</label>
    <select id="league"><option>Cargando competiciones…</option></select>
    <label>Equipos</label>
    <label id="select-all-row" class="select-all" for="select-all-teams" hidden>
      <span><input id="select-all-teams" type="checkbox"> Seleccionar todos los equipos</span>
      <span id="selection-count" class="selection-count" aria-live="polite"></span>
    </label>
    <div id="teams" class="muted">Selecciona una competición.</div>
    <label>Evento</label>
    <div class="team"><input type="checkbox" checked disabled> Inicio / partido programado</div>
    <p id="error" class="error"></p>
    <button id="install" disabled>Instalar en RadioFlow</button>
  </div>
</main>
<script>
const base={json.dumps(base_url)},session={json.dumps(session_id)},current={current_json},league=document.querySelector('#league'),teams=document.querySelector('#teams'),selectAllRow=document.querySelector('#select-all-row'),selectAll=document.querySelector('#select-all-teams'),selectionCount=document.querySelector('#selection-count'),button=document.querySelector('#install'),error=document.querySelector('#error');
const teamInputs=()=>[...teams.querySelectorAll('input[type="checkbox"]')];
function syncTeamSelection(){{
  const inputs=teamInputs(),checked=inputs.filter(input=>input.checked).length;
  selectAll.checked=inputs.length>0&&checked===inputs.length;
  selectAll.indeterminate=checked>0&&checked<inputs.length;
  selectionCount.textContent=inputs.length?`${{checked}} de ${{inputs.length}}`:'';
}}
async function loadLeagues(){{
  const rows=await fetch(`${{base}}/configure/api/leagues?session=${{encodeURIComponent(session)}}`).then(r=>r.ok?r.json():Promise.reject());
  league.innerHTML='<option value="">Selecciona una competición</option>'+rows.map(x=>`<option value="${{x.id}}" data-season="${{x.season}}">${{x.name}}</option>`).join('');
  if(current.competition){{league.value=String(current.competition.id);await loadTeams();}}
}}
async function loadTeams(){{
  button.disabled=true;
  selectAllRow.hidden=true;
  selectAll.checked=false;
  selectAll.indeterminate=false;
  selectionCount.textContent='';
  const option=league.selectedOptions[0];
  if(!option.value){{teams.textContent='Selecciona una competición.';return;}}
  teams.textContent='Cargando equipos…';
  const rows=await fetch(`${{base}}/configure/api/teams?session=${{encodeURIComponent(session)}}&competition=${{encodeURIComponent(option.value)}}`).then(r=>r.ok?r.json():Promise.reject());
  const selected=new Set((current.teams||[]).map(x=>String(x.id)));
  teams.innerHTML=rows.map(x=>`<label class="team"><input type="checkbox" value="${{x.id}}" data-name="${{x.name}}" ${{selected.has(String(x.id))?'checked':''}}> ${{x.name}}</label>`).join('');
  selectAllRow.hidden=rows.length===0;
  syncTeamSelection();
  button.disabled=false;
}}
league.addEventListener('change',loadTeams);
selectAll.addEventListener('change',()=>{{
  teamInputs().forEach(input=>{{input.checked=selectAll.checked;}});
  syncTeamSelection();
}});
teams.addEventListener('change',event=>{{
  if(event.target.matches('input[type="checkbox"]'))syncTeamSelection();
}});
button.addEventListener('click',async()=>{{
  error.textContent='';
  const option=league.selectedOptions[0],selected=teamInputs().filter(input=>input.checked).map(input=>({{id:input.value,name:input.dataset.name}}));
  if(!option.value||!selected.length){{error.textContent='Selecciona una competición y al menos un equipo.';return;}}
  button.disabled=true;
  button.textContent='Guardando…';
  try{{
    const response=await fetch(`${{base}}/configure/${{session}}/complete`,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{competition:{{id:option.value,name:option.textContent,season:option.dataset.season}},teams:selected,events:['match.scheduled']}})}});
    if(!response.ok)throw new Error();
    const result=await response.json();
    window.location.assign(result.callbackUrl);
  }}catch{{
    error.textContent='No pudimos guardar la configuración. Intenta nuevamente.';
    button.disabled=false;
    button.textContent='Instalar en RadioFlow';
  }}
}});
loadLeagues().catch(()=>error.textContent='No pudimos cargar el proveedor deportivo.');
</script>
</body>
</html>"""
