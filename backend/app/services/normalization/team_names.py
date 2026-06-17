"""Canonical team name normalization.

All logic is pure Python (no LLM). Returns the Spanish canonical name used
throughout the project as the primary identifier.
"""

from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# External source aliases: any variant -> WC2026 team ID
# ---------------------------------------------------------------------------

TEAM_NAME_ALIASES: dict[str, str] = {
    "Bosnia-Herzegovina": "BIH",
    "Bosnia and Herzegovina": "BIH",
    "Cape Verde Islands": "CPV",
    "Cape Verde": "CPV",
    "Cabo Verde": "CPV",
    "South Korea": "KOR",
    "Korea Republic": "KOR",
    "Republic of Korea": "KOR",
    "USA": "USA",
    "United States": "USA",
    "Ivory Coast": "CIV",
    "Côte d'Ivoire": "CIV",
    "Cote d'Ivoire": "CIV",
    "DR Congo": "COD",
    "Congo DR": "COD",
    "Democratic Republic of Congo": "COD",
    "Iran": "IRN",
    "IR Iran": "IRN",
    "Turkey": "TUR",
    "Türkiye": "TUR",
    "Czechia": "CZE",
    "Czech Republic": "CZE",
    "Netherlands": "NED",
    "Holland": "NED",
    "Switzerland": "SUI",
    "New Zealand": "NZL",
    "Saudi Arabia": "KSA",
    "Curacao": "CUW",
    "Curaçao": "CUW",
    "Norway": "NOR",
    "Sweden": "SWE",
    "Scotland": "SCO",
    "Algeria": "ALG",
    "Austria": "AUT",
    "Jordan": "JOR",
    "Portugal": "POR",
    "Colombia": "COL",
    "Uzbekistan": "UZB",
    "Croatia": "CRO",
    "Ghana": "GHA",
    "Panama": "PAN",
    "Paraguay": "PAR",
    "Australia": "AUS",
    "Haiti": "HAI",
    "Morocco": "MAR",
    "Senegal": "SEN",
    "Tunisia": "TUN",
    "Egypt": "EGY",
    "Belgium": "BEL",
    "Iraq": "IRQ",
    "Ecuador": "ECU",
    "Germany": "GER",
    "France": "FRA",
    "Spain": "ESP",
    "Argentina": "ARG",
    "Brazil": "BRA",
    "England": "ENG",
    "Japan": "JPN",
    "Uruguay": "URU",
    "Mexico": "MEX",
    "Canada": "CAN",
    "Qatar": "QAT",
    "South Africa": "RSA",
}

_CANONICAL_NAME_TO_ID: dict[str, str] = {
    "Argentina": "ARG",
    "Brasil": "BRA",
    "Uruguay": "URU",
    "Colombia": "COL",
    "Ecuador": "ECU",
    "Paraguay": "PAR",
    "México": "MEX",
    "Estados Unidos": "USA",
    "Canadá": "CAN",
    "Panamá": "PAN",
    "Haití": "HAI",
    "Curazao": "CUW",
    "Alemania": "GER",
    "Inglaterra": "ENG",
    "Francia": "FRA",
    "España": "ESP",
    "Portugal": "POR",
    "Países Bajos": "NED",
    "Suiza": "SUI",
    "Austria": "AUT",
    "Bélgica": "BEL",
    "Turquía": "TUR",
    "Croacia": "CRO",
    "Escocia": "SCO",
    "Suecia": "SWE",
    "Noruega": "NOR",
    "República Checa": "CZE",
    "Bosnia y Herzegovina": "BIH",
    "Marruecos": "MAR",
    "Senegal": "SEN",
    "Egipto": "EGY",
    "Ghana": "GHA",
    "Costa de Marfil": "CIV",
    "Sudáfrica": "RSA",
    "Túnez": "TUN",
    "Argelia": "ALG",
    "Cabo Verde": "CPV",
    "R.D. Congo": "COD",
    "RD Congo": "COD",
    "Japón": "JPN",
    "Corea del Sur": "KOR",
    "Australia": "AUS",
    "Irán": "IRN",
    "Arabia Saudita": "KSA",
    "Jordania": "JOR",
    "Irak": "IRQ",
    "Uzbekistán": "UZB",
    "Catar": "QAT",
    "Nueva Zelanda": "NZL",
}

# ---------------------------------------------------------------------------
# Alias map: any variant → canonical Spanish name
# The canonical name is also the value, so lookups work both ways.
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    # ── CONMEBOL ─────────────────────────────────────────────────────────
    "Argentina": "Argentina",
    "Brazil": "Brasil",
    "Brasil": "Brasil",
    "Uruguay": "Uruguay",
    "Colombia": "Colombia",
    "Ecuador": "Ecuador",
    "Venezuela": "Venezuela",
    "Paraguay": "Paraguay",
    "Chile": "Chile",
    "Peru": "Perú",
    "Perú": "Perú",
    "Bolivia": "Bolivia",

    # ── CONCACAF ─────────────────────────────────────────────────────────
    "Mexico": "México",
    "México": "México",
    "United States": "Estados Unidos",
    "USA": "Estados Unidos",
    "USMNT": "Estados Unidos",
    "United States of America": "Estados Unidos",
    "Estados Unidos": "Estados Unidos",
    "Canada": "Canadá",
    "Canadá": "Canadá",
    "Panama": "Panamá",
    "Panamá": "Panamá",
    "Jamaica": "Jamaica",
    "Honduras": "Honduras",
    "Costa Rica": "Costa Rica",
    "El Salvador": "El Salvador",
    "Trinidad and Tobago": "Trinidad y Tobago",
    "Trinidad & Tobago": "Trinidad y Tobago",
    "Guatemala": "Guatemala",
    "Haiti": "Haití",
    "Haití": "Haití",
    "Cuba": "Cuba",
    "Curacao": "Curazao",
    "Curaçao": "Curazao",

    # ── UEFA ─────────────────────────────────────────────────────────────
    "Germany": "Alemania",
    "Alemania": "Alemania",
    "England": "Inglaterra",
    "Inglaterra": "Inglaterra",
    "France": "Francia",
    "Francia": "Francia",
    "Spain": "España",
    "España": "España",
    "Portugal": "Portugal",
    "Netherlands": "Países Bajos",
    "Holland": "Países Bajos",
    "Países Bajos": "Países Bajos",
    "Switzerland": "Suiza",
    "Suiza": "Suiza",
    "Serbia": "Serbia",
    "Austria": "Austria",
    "Belgium": "Bélgica",
    "Bélgica": "Bélgica",
    "Denmark": "Dinamarca",
    "Dinamarca": "Dinamarca",
    "Turkey": "Turquía",
    "Türkiye": "Turquía",
    "Turquía": "Turquía",
    "Poland": "Polonia",
    "Polonia": "Polonia",
    "Croatia": "Croacia",
    "Croacia": "Croacia",
    "Scotland": "Escocia",
    "Escocia": "Escocia",
    "Hungary": "Hungría",
    "Hungría": "Hungría",
    "Slovenia": "Eslovenia",
    "Eslovenia": "Eslovenia",
    "Albania": "Albania",
    "Italy": "Italia",
    "Italia": "Italia",
    "Russia": "Rusia",
    "Rusia": "Rusia",
    "Sweden": "Suecia",
    "Suecia": "Suecia",
    "Norway": "Noruega",
    "Noruega": "Noruega",
    "Iceland": "Islandia",
    "Islandia": "Islandia",
    "Wales": "Gales",
    "Gales": "Gales",
    "Czech Republic": "República Checa",
    "Czechia": "República Checa",
    "República Checa": "República Checa",
    "Slovakia": "Eslovaquia",
    "Eslovaquia": "Eslovaquia",
    "Romania": "Rumanía",
    "Rumanía": "Rumanía",
    "Ukraine": "Ucrania",
    "Ucrania": "Ucrania",
    "Greece": "Grecia",
    "Grecia": "Grecia",
    "Finland": "Finlandia",
    "Finlandia": "Finlandia",
    "Israel": "Israel",
    "Bosnia-Herzegovina": "Bosnia y Herzegovina",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Bosnia Herzegovina": "Bosnia y Herzegovina",
    "Bosnia-Herzegovina": "Bosnia y Herzegovina",
    "North Macedonia": "Macedonia del Norte",
    "Montenegro": "Montenegro",
    "Kosovo": "Kosovo",
    "Georgia": "Georgia",
    "Kazakhstan": "Kazajistán",
    "Kazajistán": "Kazajistán",
    "Northern Ireland": "Irlanda del Norte",
    "Republic of Ireland": "Irlanda",
    "Ireland": "Irlanda",

    # ── CAF ──────────────────────────────────────────────────────────────
    "Morocco": "Marruecos",
    "Marruecos": "Marruecos",
    "Senegal": "Senegal",
    "Nigeria": "Nigeria",
    "Cameroon": "Camerún",
    "Camerún": "Camerún",
    "Egypt": "Egipto",
    "Egipto": "Egipto",
    "Ghana": "Ghana",
    "Ivory Coast": "Costa de Marfil",
    "Côte d'Ivoire": "Costa de Marfil",
    "Cote d'Ivoire": "Costa de Marfil",
    "Cote d Ivoire": "Costa de Marfil",
    "Costa de Marfil": "Costa de Marfil",
    "Mali": "Malí",
    "Malí": "Malí",
    "South Africa": "Sudáfrica",
    "Sudáfrica": "Sudáfrica",
    "Algeria": "Argelia",
    "Argelia": "Argelia",
    "Tunisia": "Túnez",
    "Túnez": "Túnez",
    "Congo DR": "RD Congo",
    "DR Congo": "RD Congo",
    "Democratic Republic of Congo": "RD Congo",
    "Democratic Republic of the Congo": "RD Congo",
    "R.D. Congo": "RD Congo",
    "RD Congo": "RD Congo",
    "Zambia": "Zambia",
    "Tanzania": "Tanzania",
    "Ethiopia": "Etiopía",
    "Mozambique": "Mozambique",
    "Uganda": "Uganda",
    "Burkina Faso": "Burkina Faso",
    "Guinea": "Guinea",
    "Cape Verde": "Cabo Verde",
    "Cape Verde Islands": "Cabo Verde",
    "Cabo Verde": "Cabo Verde",
    "Angola": "Angola",
    "Zimbabwe": "Zimbabue",
    "Namibia": "Namibia",
    "Sudan": "Sudán",

    # ── AFC ──────────────────────────────────────────────────────────────
    "Japan": "Japón",
    "Japón": "Japón",
    "South Korea": "Corea del Sur",
    "Korea Republic": "Corea del Sur",
    "Republic of Korea": "Corea del Sur",
    "Corea del Sur": "Corea del Sur",
    "Australia": "Australia",
    "Iran": "Irán",
    "IR Iran": "Irán",
    "Irán": "Irán",
    "Saudi Arabia": "Arabia Saudita",
    "Arabia Saudita": "Arabia Saudita",
    "Saudi Arabia": "Arabia Saudita",
    "Jordan": "Jordania",
    "Jordania": "Jordania",
    "Iraq": "Irak",
    "Irak": "Irak",
    "Uzbekistan": "Uzbekistán",
    "Uzbekistán": "Uzbekistán",
    "Qatar": "Catar",
    "Catar": "Catar",
    "UAE": "Emiratos Árabes Unidos",
    "United Arab Emirates": "Emiratos Árabes Unidos",
    "China": "China",
    "China PR": "China",
    "Vietnam": "Vietnam",
    "Thailand": "Tailandia",
    "India": "India",
    "Oman": "Omán",
    "Omán": "Omán",
    "Kuwait": "Kuwait",
    "Bahrain": "Baréin",
    "Baréin": "Baréin",
    "Kyrgyzstan": "Kirguistán",
    "Tajikistan": "Tayikistán",
    "Korea DPR": "Corea del Norte",
    "North Korea": "Corea del Norte",

    # ── OFC ──────────────────────────────────────────────────────────────
    "New Zealand": "Nueva Zelanda",
    "Nueva Zelanda": "Nueva Zelanda",
}

# Pre-build a normalized (lowercased + NFC) lookup for fuzzy matching
_LOWER_MAP: dict[str, str] = {
    unicodedata.normalize("NFC", k).casefold(): v
    for k, v in _ALIASES.items()
}

_TEAM_ID_LOWER_MAP: dict[str, str] = {
    unicodedata.normalize("NFC", k).casefold(): v
    for k, v in {**TEAM_NAME_ALIASES, **_CANONICAL_NAME_TO_ID}.items()
}


def normalize_team_name(name: str) -> str:
    """Convert any team name variant to the canonical Spanish name.

    Falls back to the stripped input if no mapping is found, and logs
    a warning so missing entries can be added.
    """
    stripped = name.strip()

    # 1. Exact match
    if stripped in _ALIASES:
        return _ALIASES[stripped]

    # 2. Case/accent-insensitive match
    key = unicodedata.normalize("NFC", stripped).casefold()
    if key in _LOWER_MAP:
        return _LOWER_MAP[key]

    logger.warning("No canonical mapping for team name: %r — returning as-is", stripped)
    return stripped


def normalize_team_id(name: str) -> str | None:
    """Return the WC2026 team ID for a known external team-name variant."""
    stripped = name.strip()
    if not stripped:
        return None
    upper = stripped.upper()
    if upper in set(_CANONICAL_NAME_TO_ID.values()):
        return upper
    if stripped in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[stripped]
    if stripped in _CANONICAL_NAME_TO_ID:
        return _CANONICAL_NAME_TO_ID[stripped]
    key = unicodedata.normalize("NFC", stripped).casefold()
    return _TEAM_ID_LOWER_MAP.get(key)


def canonical_names() -> list[str]:
    """Return sorted list of all canonical Spanish team names."""
    return sorted(set(_ALIASES.values()))
