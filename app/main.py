import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from app.config import load_config
from app.football_client import FootballDataClient
from app.match_service import get_relevant_matches
from app.models import RadioflowExternalBlock, RadioflowExternalSuggestion, SportsEvent
from app.radioflow_blocks import to_radioflow_blocks, to_radioflow_suggestions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        config = load_config()
        app.state.config = config
        logger.info("Config loaded successfully")
    except FileNotFoundError as e:
        logger.critical("Startup failed: %s", e)
        app.state.config = None
        raise
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    app.state.football_client = FootballDataClient(api_key=api_key) if api_key else None
    if not api_key:
        logger.warning("FOOTBALL_DATA_API_KEY not set. API will return empty results.")
    yield


app = FastAPI(
    title="Radioflow External Source - Sports",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/events/today", response_model=list[SportsEvent])
async def events_today(country: str | None = Query(None)):
    config = getattr(app.state, "config", None)
    client = getattr(app.state, "football_client", None)
    if not config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")
    if not client:
        return []
    events = get_relevant_matches(config, client, country=country)
    return events


@app.get("/radioflow/blocks/today", response_model=list[RadioflowExternalBlock])
async def blocks_today(country: str | None = Query(None)):
    config = getattr(app.state, "config", None)
    client = getattr(app.state, "football_client", None)
    if not config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")
    if not client:
        return []
    events = get_relevant_matches(config, client, country=country)
    blocks = to_radioflow_blocks(events, config)
    return blocks


@app.get("/radioflow/suggestions/today", response_model=list[RadioflowExternalSuggestion])
async def suggestions_today(
    source_key: str = Query(..., min_length=3, max_length=64),
    country: str | None = Query(None),
):
    config = getattr(app.state, "config", None)
    client = getattr(app.state, "football_client", None)
    if not config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")
    if not client:
        return []
    events = get_relevant_matches(config, client, country=country)
    suggestions = to_radioflow_suggestions(events, config, source_key=source_key)
    return suggestions
