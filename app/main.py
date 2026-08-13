import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
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
from app.broadcast_catalog import BroadcastCatalog, load_broadcast_catalog
from app.config import load_config
from app.configurator_web import render_configuration_html, render_landing_html
from app.football_client import FootballDataClient
from app.hosted_configuration import HostedConfigurationStore
from app.hosted_events import scheduled_matches_to_suggest_block_events
from app.match_service import get_relevant_matches
from app.models import RadioflowExternalBlock, RadioflowExternalSuggestion, SportsEvent
from app.provider_registry import get_sports_provider
from app.radioflow_blocks import to_radioflow_blocks, to_radioflow_suggestions
from app.sports_provider import (
    Competition,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderUnauthorizedError,
    ScheduledMatchOptions,
    SportsProvider,
    SyncableSportsProvider,
    Team,
)

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
    id: str
    name: str
    season: str


class TeamSelection(BaseModel):
    id: str
    name: str


class ConfigurationSelection(BaseModel):
    competition: CompetitionSelection
    teams: list[TeamSelection]
    events: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_task = None
    try:
        app.state.config = load_config()
        logger.info("Self-hosted config loaded successfully")
    except FileNotFoundError:
        app.state.config = None
        logger.info("No self-hosted config.json; hosted configuration remains available")

    try:
        app.state.broadcast_catalog = load_broadcast_catalog()
        logger.info("Hosted sports broadcast catalog loaded")
    except ValueError as error:
        app.state.broadcast_catalog = None
        logger.error("Hosted sports broadcast catalog is unavailable: %s", error)

    legacy_api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    app.state.football_client = FootballDataClient(api_key=legacy_api_key) if legacy_api_key else None
    try:
        app.state.sports_provider = get_sports_provider()
        logger.info("Hosted sports provider loaded: %s", app.state.sports_provider.name)
        if isinstance(app.state.sports_provider, SyncableSportsProvider):
            try:
                await asyncio.to_thread(
                    app.state.sports_provider.sync_if_due,
                    force=not app.state.sports_provider.has_data,
                )
            except ProviderError as error:
                logger.error("Initial sports sync failed: %s", error)
                if not app.state.sports_provider.has_data:
                    app.state.sports_provider = None
            if app.state.sports_provider is not None:
                sync_task = asyncio.create_task(_provider_sync_loop(app.state.sports_provider))
    except (ProviderError, ValueError) as error:
        app.state.sports_provider = None
        logger.error("Hosted sports provider is unavailable: %s", error)
    signing_secret = os.getenv("SPORTS_CONFIG_SIGNING_SECRET", "").strip()
    app.state.configuration_store = (
        HostedConfigurationStore(
            os.getenv("SPORTS_CONFIG_DB_PATH", ".data/sports-addon.db"),
            signing_secret,
        )
        if signing_secret
        else None
    )
    if app.state.sports_provider is None or app.state.broadcast_catalog is None:
        logger.warning("Hosted sports catalog and events are degraded")
    if not signing_secret:
        logger.warning("SPORTS_CONFIG_SIGNING_SECRET not set; hosted configuration is disabled")
    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task


async def _provider_sync_loop(provider: SyncableSportsProvider):
    interval = max(60, int(os.getenv("SPORTS_SYNC_CHECK_INTERVAL_SECONDS", "3600")))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(provider.sync_if_due)
        except ProviderError as error:
            logger.error("Periodic sports sync failed; stored data remains available: %s", error)


app = FastAPI(title="Radioflow External Source - Sports", version=ADDON_VERSION, lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(render_landing_html())


@app.get("/manifest.json", response_model=AddonManifest, response_model_by_alias=True)
async def addon_manifest():
    return SPORTS_ADDON_MANIFEST


@app.get("/health", response_model=AddonHealth)
async def health():
    provider = _sports_provider(required=False)
    ready = (
        _configuration_store(required=False) is not None
        and provider is not None
        and _broadcast_catalog(required=False) is not None
    )
    return AddonHealth(
        status="ok" if ready else "degraded",
        version=ADDON_VERSION,
        provider=provider.name if provider else os.getenv("SPORTS_PROVIDER", "thesportsdb").strip().casefold(),
    )


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
    return HTMLResponse(render_configuration_html(_public_base_url(request), session_id, current))


@app.get("/configure/api/leagues")
def configuration_leagues(session: str = Query(...)):
    _require_session(session)
    try:
        competitions = _sports_provider().get_competitions()
    except ProviderError as error:
        raise _provider_http_exception(error) from error
    return [_competition_payload(competition) for competition in competitions]


@app.get("/configure/api/teams")
def configuration_teams(
    session: str = Query(...),
    competition: str = Query(..., min_length=2, max_length=160),
):
    _require_session(session)
    try:
        teams = _sports_provider().get_teams(competition)
    except (ProviderError, ValueError) as error:
        raise _provider_http_exception(error) from error
    return [_team_payload(team) for team in teams]


@app.post("/configure/{session_id}/complete")
def configuration_complete(session_id: str, selection: ConfigurationSelection):
    try:
        competition, teams = _canonicalize_selection(selection)
        code, state, callback_url, summary = _configuration_store().save_configuration(
            session_id,
            competition,
            teams,
            selection.events,
        )
    except ProviderError as error:
        raise _provider_http_exception(error) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "callbackUrl": f"{callback_url}?{urlencode({'state': state, 'code': code})}",
        "summary": summary,
    }


@app.get("/addon/events", response_model=list[AddonEventEnvelope])
def addon_events(config_id: str | None = Header(None, alias="X-RadioFlow-Config-Id")):
    configuration = _configuration_store().get_configuration(config_id)
    if not configuration:
        raise HTTPException(status_code=401, detail="A valid X-RadioFlow-Config-Id is required")
    now = datetime.now(timezone.utc)
    try:
        matches = _sports_provider().get_scheduled_matches(
            configuration.competition["id"],
            ScheduledMatchOptions(starts_after=now, starts_before=now + timedelta(days=7)),
        )
    except (ProviderError, ValueError) as error:
        raise _provider_http_exception(error) from error
    return scheduled_matches_to_suggest_block_events(
        matches,
        configuration,
        broadcast_catalog=_broadcast_catalog(),
        schedule_timezone=os.getenv("SPORTS_SCHEDULE_TIMEZONE", "America/Santiago"),
    )


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


def _sports_provider(required: bool = True) -> SportsProvider | None:
    provider = getattr(app.state, "sports_provider", None)
    if required and not provider:
        raise HTTPException(status_code=503, detail="Sports provider is unavailable")
    return provider


def _broadcast_catalog(required: bool = True) -> BroadcastCatalog | None:
    catalog = getattr(app.state, "broadcast_catalog", None)
    if required and not catalog:
        raise HTTPException(status_code=503, detail="Sports broadcast catalog is unavailable")
    return catalog


def _competition_payload(competition: Competition) -> dict[str, str | None]:
    return {
        "id": competition.id,
        "name": competition.name,
        "country": competition.country,
        "season": competition.current_season,
    }


def _team_payload(team: Team) -> dict[str, str]:
    return {"id": team.id, "name": team.name}


def _canonicalize_selection(selection: ConfigurationSelection) -> tuple[dict, list[dict]]:
    provider = _sports_provider()
    competition = next(
        (item for item in provider.get_competitions() if item.id == selection.competition.id),
        None,
    )
    if not competition or competition.current_season != selection.competition.season:
        raise ValueError("invalid competition selection")
    available_teams = {team.id: team for team in provider.get_teams(competition.id)}
    requested_ids = [team.id for team in selection.teams]
    if not requested_ids or len(requested_ids) != len(set(requested_ids)):
        raise ValueError("invalid team selection")
    if any(team_id not in available_teams for team_id in requested_ids):
        raise ValueError("invalid team selection")
    return (
        {
            "id": competition.id,
            "name": competition.name,
            "season": competition.current_season,
        },
        [{"id": team_id, "name": available_teams[team_id].name} for team_id in requested_ids],
    )


def _provider_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, ProviderRateLimitedError):
        return HTTPException(status_code=429, detail="Sports provider rate limit reached")
    if isinstance(error, ProviderUnauthorizedError):
        return HTTPException(status_code=503, detail="Sports provider credential is unavailable")
    if isinstance(error, ProviderInvalidResponseError):
        return HTTPException(status_code=502, detail="Sports provider returned an invalid response")
    if isinstance(error, ProviderError):
        return HTTPException(status_code=503, detail="Sports provider is unavailable")
    return HTTPException(status_code=400, detail=str(error))


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
