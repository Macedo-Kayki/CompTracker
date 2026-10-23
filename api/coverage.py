from __future__ import annotations

from functools import lru_cache

import config
from api import photos, stats
from api.store import Filters, store


@lru_cache(maxsize=2)
def _coverage(version: int) -> dict:
    """Conta quanto de cada informação existe nas fontes (eventos, partidas, prêmios e fotos)."""
    mf = store["matches_fact"]
    pmf = store["player_maps_fact"]
    titles = stats.titles(Filters())
    t1 = stats.titles(Filters(tier=1))
    pc = store["player_cube"]
    vct = photos.eligible_players(pc)
    leaders = photos.leader_players()
    has_photo = lambda ids: sum(1 for p in ids if photos.cached_path(p))
    title_dir = config.ROOT / "web" / "img" / "titulos"
    title_photos = {p.stem for p in title_dir.glob("*.jpg")} | {p.stem for p in title_dir.glob("*.png")}
    perf = {p.stem.split(".")[0] for p in (config.BRONZE_DIR / "performance").glob("year=*/*.html.gz")}
    return {
        "events": int(store["dim_events"]["event_id"].nunique()),
        "matches": int(mf["match_id"].nunique()),
        "maps": int(pmf["game_id"].nunique()),
        "rounds": int(store["round_cube"]["rounds"].sum()),
        "teams": int(store["dim_teams"]["team_id"].nunique()),
        "players": int(store["dim_players"]["player_id"].nunique()),
        "titles": int(len(titles)),
        "titles_prize": int((titles["prize_usd"].fillna(0) > 0).sum()),
        "titles_champion_prize": int(titles["champion_prize_usd"].notna().sum()),
        "tier1_titles": int(len(t1)),
        "tier1_title_photos": int(t1["event_id"].astype(str).isin(title_photos).sum()),
        "title_photos": len(title_photos),
        "vct_players": len(vct),
        "vct_photos": has_photo(vct),
        "leaders": len(leaders),
        "leader_photos": has_photo(leaders),
        "liquipedia_photos": len(list(photos.CACHE.glob("*.jpg"))),
        "flickr_photos": len(list(photos.FLICKR_CACHE.glob("*.jpg"))) if photos.FLICKR_CACHE.exists() else 0,
        "matrix_matches": int(mf["match_id"].astype(str).isin(perf).sum()),
    }


def coverage() -> dict:
    """Devolve a cobertura dos dados para a página Dados, com cache por versão."""
    return _coverage(store.version)


def credits() -> dict:
    """Lista os fotógrafos das fotos de títulos e de jogadores (Flickr da Riot), com quantas fotos cada um tem."""
    import json
    from collections import Counter

    titles = Counter()
    path = config.ROOT / "web" / "img" / "titulos" / "creditos.json"
    if path.exists():
        for rec in json.loads(path.read_text(encoding="utf-8")).values():
            titles[(rec.get("credit") or "Riot Games").strip()] += 1
    players = Counter()
    if photos.FLICKR_MAPPING.exists():
        for line in photos.FLICKR_MAPPING.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("pid") and photos.cached_path(rec["player_id"]):
                players[(rec.get("credit") or "Riot Games").strip()] += 1
    rows = lambda c: [{"credit": k, "photos": v} for k, v in c.most_common()]
    return {"title_photographers": rows(titles), "player_photographers": rows(players)}
