import re
import unicodedata

from app.sports_provider import ProviderInvalidResponseError, build_team_id


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


_ALIASES = {
    "audax italiano": "Audax Italiano",
    "cd universidad catolica": "Universidad Católica",
    "cobresal": "Cobresal",
    "colo colo": "Colo Colo",
    "coquimbo unido": "Coquimbo Unido",
    "deportes concepcion": "Deportes Concepción",
    "deportes la serena": "Deportes La Serena",
    "deportes limache": "Deportes Limache",
    "everton": "Everton",
    "huachipato": "Huachipato",
    "nublense": "Ñublense",
    "o higgins": "O'Higgins",
    "ohiggins": "O'Higgins",
    "palestino": "Palestino",
    "u catolica": "Universidad Católica",
    "u de chile": "Universidad de Chile",
    "u de concepcion": "Universidad de Concepción",
    "union la calera": "Unión La Calera",
    "universidad catolica": "Universidad Católica",
    "universidad de chile": "Universidad de Chile",
    "universidad de concepcion": "Universidad de Concepción",
}


def normalize_team_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ProviderInvalidResponseError("official source returned an empty team name")
    return _ALIASES.get(_key(cleaned), cleaned)


def normalized_team(competition_id: str, name: str) -> tuple[str, str]:
    canonical = normalize_team_name(name)
    return build_team_id(competition_id, canonical), canonical
