from __future__ import annotations

import re

INTERNATIONAL = "Internacional"
REGIONS = ("Americas", "EMEA", "Pacific", "China")
TIERS = (1, 2, 3)
EVENT_TYPES = ("Champions", "Masters", "Liga", "Kickoff", "Challengers", "Ascension", "Qualificatória", "Outros")

_REGION_KEYWORDS = [
    ("China", r"china|chinese|evolution series|road to vct"),
    ("Americas", r"americas|north america|brazil|brasil|latam|latin america|south america|mexico|argentina|chile"),
    ("EMEA", r"emea|europe|turkey|türkiye|cis|arabia|mena|spain|france|dach|italy|portugal|poland|polska|"
             r"northern europe|nordic|benelux|balkans?|baltics?|united kingdom|uk & ireland|ukraine|east: surge"),
    ("Pacific", r"pacific|korea|japan|sea|southeast asia|philippines|indonesia|thailand|vietnam|malaysia|"
                r"singapore|hong kong|taiwan|oceania|asia-pacific|east asia|south asia|india|skyesports"),
]

_AMERICAS = set("us ca br mx ar cl co pe uy ve ec py bo cr pa gt do pr sv hn ni cu jm tt".split())
_PACIFIC = set("kr jp ph id th vn my sg hk tw mo au nz in pk bd lk np kh mm la mn".split())


_WOMENS = re.compile(r"game ?changers|\bgirl|\bwom[ae]n|female|ladies|feminin|femen|mulher", re.I)


def is_mens_event(title: str) -> bool:
    """Indica se o evento não é feminino (Game Changers e afins)."""
    return not _WOMENS.search(title or "")


def region_from_flag(flag: str | None) -> str | None:
    """Deduz a região a partir do código de bandeira do país."""
    if not flag:
        return None
    flag = flag.lower()
    if flag == "un":
        return INTERNATIONAL
    if flag == "cn":
        return "China"
    if flag in _AMERICAS:
        return "Americas"
    if flag in _PACIFIC:
        return "Pacific"
    return "EMEA"


def event_type(title: str, tier: int = 1) -> str:
    """Classifica o evento (Champions, Masters, Liga etc.) pelo título e tier."""
    t = title.lower()
    if tier == 1:
        if re.search(r"valorant masters|champions tour 20\d\d: masters|valorant champions tour stage \d: masters|lock//in", t):
            return "Masters"
        if "masters" in t:
            return "Challengers"
    if "ascension" in t:
        return "Ascension"
    if re.search(r"last chance|qualifier|promotion", t):
        return "Qualificatória"
    if tier == 1:
        if re.fullmatch(r"valorant champions 20\d\d", t.strip()):
            return "Champions"
        if "kickoff" in t:
            return "Kickoff"
        if re.search(r"(vct 20\d\d|champions tour 2024): .*stage", t) or re.search(r"champions tour 2023: \w+ league", t):
            return "Liga"
        if "evolution series" in t:
            return "Liga"
        if "challengers" in t or re.search(r"champions tour .*stage \d: playoffs", t):
            return "Challengers"
        return "Outros"
    if tier == 2:
        return "Challengers"
    return "Outros"


def event_region(title: str, etype: str | None = None, flag: str | None = None) -> str:
    """Define a região do evento pelo tipo, por palavras do título ou pela bandeira."""
    etype = etype or event_type(title)
    if etype in ("Masters", "Champions"):
        return INTERNATIONAL
    t = title.lower()
    for region, pattern in _REGION_KEYWORDS:
        if re.search(rf"\b(?:{pattern})\b", t):
            return region
    return region_from_flag(flag) or "Outros"
