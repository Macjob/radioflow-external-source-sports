import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.addon_protocol import (
    ADDON_VERSION,
    SPORTS_ADDON_MANIFEST,
    AddonEventEnvelope,
    AddonHealth,
    AddonManifest,
)
from app.api_football_client import ApiFootballClient
from app.config import load_config
from app.football_client import FootballDataClient
from app.hosted_configuration import HostedConfigurationStore
from app.hosted_events import fixtures_to_suggest_block_events
from app.match_service import get_relevant_matches
from app.models import RadioflowExternalBlock, RadioflowExternalSuggestion, SportsEvent
from app.radioflow_blocks import to_radioflow_blocks, to_radioflow_suggestions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()


class ConfigurationStartRequest(BaseModel):
    callback_url: str = Field(alias="callbackUrl")
    state: str
    mode: str


class ConfigurationStartResponse(BaseModel):
    configure_url: str = Field(alias="configureUrl")


class ConfigurationExchangeRequest(BaseModel):
    code: str


class ConfigurationExchangeResponse(BaseModel):
    config_id: str = Field(alias="configId")
    summary: dict


class CompetitionSelection(BaseModel):
    id: int
    name: str
    season: int


class TeamSelection(BaseModel):
    id: int
    name: str


class ConfigurationSelection(BaseModel):
    competition: CompetitionSelection
    teams: list[TeamSelection]
    events: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.config = load_config()
        logger.info("Self-hosted config loaded successfully")
    except FileNotFoundError:
        app.state.config = None
        logger.info("No self-hosted config.json; hosted configuration remains available")

    legacy_api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    api_football_key = os.getenv("API_FOOOTBAL", "").strip()
    app.state.football_client = FootballDataClient(api_key=legacy_api_key) if legacy_api_key else None
    app.state.api_football_client = ApiFootballClient(api_key=api_football_key) if api_football_key else None
    signing_secret = os.getenv("SPORTS_CONFIG_SIGNING_SECRET", "").strip()
    app.state.configuration_store = (
        HostedConfigurationStore(
            os.getenv("SPORTS_CONFIG_DB_PATH", ".data/sports-addon.db"),
            signing_secret,
        )
        if signing_secret
        else None
    )
    if not api_football_key:
        logger.warning("API_FOOOTBAL not set; hosted catalog and events are degraded")
    if not signing_secret:
        logger.warning("SPORTS_CONFIG_SIGNING_SECRET not set; hosted configuration is disabled")
    yield


app = FastAPI(title="Radioflow External Source - Sports", version=ADDON_VERSION, lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(_landing_html())


@app.get("/manifest.json", response_model=AddonManifest, response_model_by_alias=True)
async def addon_manifest():
    return SPORTS_ADDON_MANIFEST


@app.get("/health", response_model=AddonHealth)
async def health():
    ready = _configuration_store(required=False) is not None and _api_football_client(required=False) is not None
    return AddonHealth(status="ok" if ready else "degraded", version=ADDON_VERSION)


@app.post(
    "/configuration/start",
    response_model=ConfigurationStartResponse,
    response_model_by_alias=True,
)
async def configuration_start(
    payload: ConfigurationStartRequest,
    request: Request,
    config_id: str | None = Header(None, alias="X-RadioFlow-Config-Id"),
):
    store = _configuration_store()
    try:
        session = store.create_session(
            state=payload.state,
            callback_url=payload.callback_url,
            mode=payload.mode,
            existing_config_id=config_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ConfigurationStartResponse(
        configureUrl=f"{_public_base_url(request)}/configure/{session.id}",
    )


@app.post(
    "/configuration/exchange",
    response_model=ConfigurationExchangeResponse,
    response_model_by_alias=True,
)
async def configuration_exchange(payload: ConfigurationExchangeRequest):
    try:
        config_id, summary = _configuration_store().exchange_code(payload.code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ConfigurationExchangeResponse(configId=config_id, summary=summary)


@app.get("/configure/{session_id}", response_class=HTMLResponse)
async def configure(session_id: str, request: Request):
    session = _configuration_store().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found or expired")
    current = None
    if session.existing_config_hash:
        current = _configuration_by_hash(session.existing_config_hash)
    return HTMLResponse(_configuration_html(_public_base_url(request), session_id, current))


@app.get("/configure/api/leagues")
async def configuration_leagues(session: str = Query(...)):
    _require_session(session)
    rows = _api_football_client().get_leagues("Chile")
    leagues = []
    for row in rows:
        league = row.get("league") or {}
        seasons = row.get("seasons") or []
        current = next((season for season in seasons if season.get("current")), seasons[-1] if seasons else None)
        if isinstance(league.get("id"), int) and current and isinstance(current.get("year"), int):
            leagues.append({"id": league["id"], "name": league.get("name", ""), "season": current["year"]})
    return sorted(leagues, key=lambda item: item["name"])


@app.get("/configure/api/teams")
async def configuration_teams(
    session: str = Query(...),
    league: int = Query(..., gt=0),
    season: int = Query(..., gt=1900),
):
    _require_session(session)
    rows = _api_football_client().get_teams(league, season)
    teams = []
    for row in rows:
        team = row.get("team") or {}
        if isinstance(team.get("id"), int) and team.get("name"):
            teams.append({"id": team["id"], "name": team["name"], "logo": team.get("logo")})
    return sorted(teams, key=lambda item: item["name"])


@app.post("/configure/{session_id}/complete")
async def configuration_complete(session_id: str, selection: ConfigurationSelection):
    try:
        code, state, callback_url, summary = _configuration_store().save_configuration(
            session_id,
            selection.competition.model_dump(),
            [team.model_dump() for team in selection.teams],
            selection.events,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "callbackUrl": f"{callback_url}?{urlencode({'state': state, 'code': code})}",
        "summary": summary,
    }


@app.get("/addon/events", response_model=list[AddonEventEnvelope])
async def addon_events(config_id: str | None = Header(None, alias="X-RadioFlow-Config-Id")):
    configuration = _configuration_store().get_configuration(config_id)
    if not configuration:
        raise HTTPException(status_code=401, detail="A valid X-RadioFlow-Config-Id is required")
    client = _api_football_client()
    today = date.today()
    fixtures = []
    for team in configuration.teams:
        fixtures.extend(
            client.get_fixtures(
                team_id=team["id"],
                from_date=today,
                to_date=today + timedelta(days=7),
                timezone="America/Santiago",
            )
        )
    return fixtures_to_suggest_block_events(fixtures, configuration)


@app.get("/events/today", response_model=list[SportsEvent])
async def events_today(country: str | None = Query(None)):
    return _get_legacy_events(country)


def _get_legacy_events(country: str | None = None) -> list[SportsEvent]:
    config = getattr(app.state, "config", None)
    client = getattr(app.state, "football_client", None)
    if not config:
        raise HTTPException(status_code=500, detail="Self-hosted configuration not loaded")
    if not client:
        return []
    return get_relevant_matches(config, client, country=country)


@app.get("/radioflow/blocks/today", response_model=list[RadioflowExternalBlock])
async def blocks_today(country: str | None = Query(None)):
    config = getattr(app.state, "config", None)
    return to_radioflow_blocks(_get_legacy_events(country), config)


@app.get("/radioflow/suggestions/today", response_model=list[RadioflowExternalSuggestion])
async def suggestions_today(source_key: str = Query(..., min_length=3, max_length=64), country: str | None = Query(None)):
    config = getattr(app.state, "config", None)
    return to_radioflow_suggestions(_get_legacy_events(country), config, source_key=source_key)


def _configuration_store(required: bool = True) -> HostedConfigurationStore | None:
    store = getattr(app.state, "configuration_store", None)
    if required and not store:
        raise HTTPException(status_code=503, detail="Hosted configuration storage is unavailable")
    return store


def _api_football_client(required: bool = True) -> ApiFootballClient | None:
    client = getattr(app.state, "api_football_client", None)
    if required and not client:
        raise HTTPException(status_code=503, detail="API-Football provider is unavailable")
    return client


def _require_session(session_id: str):
    if not _configuration_store().get_session(session_id):
        raise HTTPException(status_code=404, detail="Configuration session not found or expired")


def _configuration_by_hash(config_hash: str):
    stored = _configuration_store().get_configuration_by_hash(config_hash)
    if not stored:
        return None
    return {"competition": stored.competition, "teams": stored.teams, "events": stored.events}


def _public_base_url(request: Request) -> str:
    configured = os.getenv("SPORTS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _landing_html():
    return """<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>RadioFlow Addons</title><style>body{margin:0;background:#080713;color:#f5f2ff;font:16px system-ui}main{max-width:900px;margin:auto;padding:64px 24px}.card{border:1px solid #30274d;border-radius:20px;background:#100e1f;padding:32px}h1{font-size:36px}.pill{display:inline-block;color:#b997ff;background:#25134b;padding:7px 12px;border-radius:99px}p{color:#b9b3cc;line-height:1.6}</style></head><body><main><span class=\"pill\">RadioFlow Addons</span><div class=\"card\"><h1>Sports Notifications</h1><p>Configura ligas y equipos desde la web. RadioFlow instala el addon y recibe sólo sugerencias asociadas a tu configuración opaca.</p><p>La credencial de API-Football y la infraestructura permanecen en el backend alojado.</p></div></main></body></html>"""


def _configuration_html(base_url: str, session_id: str, current: dict | None):
    current_json = json.dumps(current or {}, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Sports Notifications</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#080713;color:#f7f4ff;font:15px system-ui}}main{{max-width:820px;margin:auto;padding:36px 20px}}.head{{display:flex;gap:16px;align-items:center;margin-bottom:24px}}.icon{{display:grid;place-items:center;width:52px;height:52px;border-radius:16px;background:#651dff;font-size:28px}}.steps{{display:flex;gap:8px;margin:24px 0}}.steps span{{flex:1;border-top:3px solid #30264f;padding-top:8px;color:#8d86a3}}.steps .on{{border-color:#7c2cff;color:#fff}}.card{{border:1px solid #2d2744;border-radius:18px;background:#100e1e;padding:24px}}label{{display:block;margin:16px 0 8px;font-weight:700}}select{{width:100%;padding:12px;border:1px solid #3a3156;border-radius:10px;background:#17132a;color:#fff}}#teams{{display:grid;gap:8px;margin-top:12px;max-height:330px;overflow:auto}}.team{{display:flex;gap:10px;padding:11px;border:1px solid #2d2744;border-radius:10px;background:#151225}}button{{margin-top:20px;width:100%;padding:13px;border:0;border-radius:10px;background:#6d20ff;color:white;font-weight:800;cursor:pointer}}button:disabled{{opacity:.5}}.muted{{color:#9d96b1}}.error{{color:#ff8b9b}}</style></head><body><main><div class=\"head\"><div class=\"icon\">⚽</div><div><h1>Sports Notifications</h1><div class=\"muted\">Configuración del addon</div></div></div><div class=\"steps\"><span class=\"on\">1 Competición</span><span class=\"on\">2 Equipos</span><span class=\"on\">3 Evento</span><span>4 Instalar</span></div><div class=\"card\"><label for=\"league\">Liga o competición</label><select id=\"league\"><option>Cargando competiciones…</option></select><label>Equipos</label><div id=\"teams\" class=\"muted\">Selecciona una competición.</div><label>Evento</label><div class=\"team\"><input type=\"checkbox\" checked disabled> Inicio / partido programado</div><p id=\"error\" class=\"error\"></p><button id=\"install\" disabled>Instalar en RadioFlow</button></div></main><script>const base={json.dumps(base_url)},session={json.dumps(session_id)},current={current_json},league=document.querySelector('#league'),teams=document.querySelector('#teams'),button=document.querySelector('#install'),error=document.querySelector('#error');async function loadLeagues(){{const rows=await fetch(`${{base}}/configure/api/leagues?session=${{encodeURIComponent(session)}}`).then(r=>r.ok?r.json():Promise.reject());league.innerHTML='<option value=\"\">Selecciona una competición</option>'+rows.map(x=>`<option value=\"${{x.id}}\" data-season=\"${{x.season}}\">${{x.name}}</option>`).join('');if(current.competition){{league.value=String(current.competition.id);await loadTeams();}}}}async function loadTeams(){{button.disabled=true;const option=league.selectedOptions[0];if(!option.value)return;teams.textContent='Cargando equipos…';const rows=await fetch(`${{base}}/configure/api/teams?session=${{encodeURIComponent(session)}}&league=${{option.value}}&season=${{option.dataset.season}}`).then(r=>r.ok?r.json():Promise.reject());const selected=new Set((current.teams||[]).map(x=>x.id));teams.innerHTML=rows.map(x=>`<label class=\"team\"><input type=\"checkbox\" value=\"${{x.id}}\" data-name=\"${{x.name}}\" ${{selected.has(x.id)?'checked':''}}> ${{x.name}}</label>`).join('');button.disabled=false;}}league.addEventListener('change',loadTeams);button.addEventListener('click',async()=>{{error.textContent='';const option=league.selectedOptions[0],selected=[...teams.querySelectorAll('input:checked')].map(x=>({{id:Number(x.value),name:x.dataset.name}}));if(!option.value||!selected.length){{error.textContent='Selecciona una competición y al menos un equipo.';return;}}button.disabled=true;button.textContent='Guardando…';try{{const response=await fetch(`${{base}}/configure/${{session}}/complete`,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{competition:{{id:Number(option.value),name:option.textContent,season:Number(option.dataset.season)}},teams:selected,events:['match.scheduled']}})}});if(!response.ok)throw new Error();const result=await response.json();window.location.assign(result.callbackUrl);}}catch{{error.textContent='No pudimos guardar la configuración. Intenta nuevamente.';button.disabled=false;button.textContent='Instalar en RadioFlow';}}}});loadLeagues().catch(()=>error.textContent='No pudimos cargar API-Football.');</script></body></html>"""
