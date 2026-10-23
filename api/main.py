from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

import config
from api import assets, chart_data, charts, countries, coverage, logos, matches, photos, stats
from api.stats import records
from api.store import Filters, store
from etl.classify import EVENT_TYPES, INTERNATIONAL, REGIONS

WEB_DIR = config.ROOT / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Carrega as tabelas da camada de serving ao iniciar a API."""
    store.load()
    yield


app = FastAPI(title="CompTracker — VALORANT competitivo 2021–2026", version="1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def filters(year: int | None = None, tier: int | None = Query(None, ge=1, le=3), region: str | None = None,
            event_type: str | None = None, event_id: int | None = None) -> Filters:
    """Monta os filtros globais da requisição, exigindo que os dados estejam carregados."""
    if not store.ready:
        raise HTTPException(503, "Dados ainda não processados: rode `python -m scraper.run` e `python -m etl.run`.")
    return Filters(year=year, tier=tier, region=region or None, event_type=event_type or None, event_id=event_id)


@app.get("/", include_in_schema=False)
def index():
    """Serve a página inicial com versão nos arquivos estáticos para evitar cache."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    version = int(max((WEB_DIR / f).stat().st_mtime for f in ("style.css", "charts.js", "matches.js", "app.js")))
    return HTMLResponse(html.replace("?v=dev", f"?v={version}"), headers={"Cache-Control": "no-cache"})


@app.get("/api/meta")
def meta(f: Filters = Depends(filters)):
    """Retorna os metadados usados pelo front-end (anos, regiões, eventos, temas)."""
    ev = store["dim_events"].sort_values("start_date", ascending=False)
    return {
        "years": sorted(int(y) for y in store["matches_fact"]["year"].dropna().unique()),
        "regions": [*REGIONS, INTERNATIONAL, "Outros"],
        "event_types": list(EVENT_TYPES),
        "event_colors": charts.EVENT_COLORS,
        "chart_themes": charts.THEMES,
        "team_countries": _team_countries(),
        "event_order": charts.EVENT_ORDER,
        "tiers": [{"tier": 1, "label": "Tier 1", "desc": "VCT: ligas, Masters e Champions"},
                  {"tier": 2, "label": "Tier 2", "desc": "Challengers e Ascension"},
                  {"tier": 3, "label": "Tier 3", "desc": "Torneios independentes (prêmio ≥ US$ 5 mil)"}],
        "events": records(ev[["event_id", "name", "year", "tier", "region", "event_type"]]),
        "manifest": store.manifest,
        "banner_version": _file_version(WEB_DIR / "img" / "banners" / "allcamps.jpg"),
    }


def _file_version(path) -> int:
    """Devolve a data de modificação de um arquivo, usada para o navegador não mostrar a versão antiga."""
    return int(path.stat().st_mtime) if path.exists() else 0


def _team_countries() -> dict:
    """Mapeia cada time para o nome do seu país em português."""
    dt = store["dim_teams"]
    if "team_country" not in dt:
        return {}
    dt = dt[dt["team_country"].notna()]
    return {int(t): countries.pt(c) for t, c in zip(dt["team_id"], dt["team_country"])}


@app.get("/api/search")
def search(q: str = Query(min_length=2), f: Filters = Depends(filters)):
    """Busca times e jogadores pelo nome, ordenados por mapas jogados."""
    key = _search_key(q)
    if not key:
        return {"teams": [], "players": []}
    teams = store["team_cube"].groupby("team_id")["maps"].sum().rename("maps").reset_index()
    teams = teams.merge(store["dim_teams"], on="team_id")
    teams = _rank_matches(teams, "team_name", key)
    players = store["player_cube"].groupby("player_id")["maps"].sum().rename("maps").reset_index()
    players = players.merge(store["dim_players"], on="player_id")
    players = _rank_matches(players, "player_name", key)
    return {"teams": records(teams[["team_id", "team_name", "team_region", "maps", "exact"]]),
            "players": records(players[["player_id", "player_name", "current_team_name", "maps", "exact"]])}


def _search_key(text) -> str:
    """Normaliza um nome para a busca: minúsculas, sem acentos, espaços ou pontuação."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _rank_matches(df, col, key, limit=8):
    """Filtra os nomes que contêm a busca e põe primeiro os exatos, depois os com mais mapas."""
    keys = df[col].map(_search_key)
    hit = df[keys.str.contains(key, regex=False, na=False)].copy()
    hit["exact"] = keys[hit.index] == key
    return hit.sort_values(["exact", "maps"], ascending=False).head(limit)


@app.post("/api/reload")
def reload():
    """Recarrega as tabelas do disco e limpa os caches de gráficos e partidas."""
    ok = store.load()
    charts.render.cache_clear()
    chart_data.build.cache_clear()
    matches._detail.cache_clear()
    matches._mvps.cache_clear()
    coverage._coverage.cache_clear()
    return {"ok": ok, "version": store.version}


@app.get("/api/lake")
def lake(f: Filters = Depends(filters)):
    """Retorna o manifesto do data lake."""
    return store.manifest


@app.get("/api/coverage")
def data_coverage(f: Filters = Depends(filters)):
    """Devolve a cobertura dos dados e das fotos para a página Dados."""
    return coverage.coverage()


@app.get("/api/credits")
def data_credits():
    """Devolve os créditos dos fotógrafos para a página Dados."""
    return coverage.credits()


@app.get("/api/overview")
def overview(f: Filters = Depends(filters)):
    """Retorna os números gerais do filtro atual."""
    return stats.overview(f)


@app.get("/api/titles")
def titles(f: Filters = Depends(filters)):
    """Lista os títulos (campeão e vice) dos eventos no filtro atual."""
    t = stats.titles(f)
    return records(t[["event_id", "name", "year", "tier", "region", "event_type", "end_date", "prize_usd",
                      "champion_id", "champion_name", "champion_prize_usd", "runner_up_id", "runner_up_name",
                      "runner_up_prize_usd"]])


@app.get("/api/events/{event_id}")
def event(event_id: int, f: Filters = Depends(filters)):
    """Retorna os detalhes de um evento."""
    d = stats.event_detail(event_id)
    if not d:
        raise HTTPException(404, "evento não encontrado")
    return d


@app.get("/api/events/{event_id}/bracket")
def event_bracket(event_id: int, f: Filters = Depends(filters)):
    """Retorna o chaveamento de playoffs de um evento Tier 1."""
    d = stats.event_detail(event_id)
    if not d:
        raise HTTPException(404, "evento não encontrado")
    if not d["has_bracket"]:
        raise HTTPException(404, "chaveamento disponível apenas para eventos do Tier 1 com playoffs")
    return stats.bracket(event_id)


@app.get("/api/featured-title")
def featured_title(f: Filters = Depends(filters)):
    """Retorna o título em destaque no filtro atual."""
    return stats.featured_title(f)


@app.get("/api/logo/{kind}/{key}", response_class=Response)
def logo(kind: Literal["team", "event"], key: int, theme: Literal["dark", "light"] | None = None):
    """Serve o logo de um time ou evento, adaptado ao tema."""
    if not store.ready:
        raise HTTPException(503, "dados não carregados")
    got = logos.themed(kind, key, theme)
    if got is None:
        raise HTTPException(404, "sem logo")
    data, media, _ext, _path = got
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=604800"})


TEAM_SORTS = Literal["map_wr", "match_wr", "round_wr", "atk_wr", "def_wr", "pistol_wr", "titles", "maps"]


@app.get("/api/teams")
def teams(f: Filters = Depends(filters), team_region: str | None = None, min_maps: int = 20,
          sort: TEAM_SORTS = "map_wr", limit: int = Query(100, le=1000)):
    """Lista os times com suas taxas de vitória, ordenados pela métrica escolhida."""
    df = stats.team_table(f, team_region=team_region or None, min_maps=min_maps)
    return records(df.sort_values(sort, ascending=False).head(limit))


@app.get("/api/teams/{team_id}")
def team(team_id: int, f: Filters = Depends(filters)):
    """Retorna os detalhes de um time."""
    d = stats.team_detail(team_id, f)
    if not d:
        raise HTTPException(404, "time não encontrado")
    return d


@app.get("/api/teams/{team_id}/featured-title")
def team_featured_title(team_id: int, f: Filters = Depends(filters)):
    """Retorna o título em destaque de um time."""
    return stats.team_featured_title(team_id)


@app.get("/api/teams/{team_id}/matches")
def team_matches(team_id: int, f: Filters = Depends(filters), offset: int = Query(0, ge=0),
                 limit: int = Query(10, ge=1, le=50)):
    """Lista as partidas de um time de forma paginada."""
    return matches.team_matches(team_id, f, offset, limit)


@app.get("/api/matches/{match_id}")
def match_detail(match_id: int, f: Filters = Depends(filters)):
    """Retorna os detalhes de uma partida a partir da camada bronze."""
    d = matches.match_detail(match_id)
    if not d:
        raise HTTPException(404, "partida não encontrada na camada bronze")
    return d


@app.get("/api/team-colors")
def team_colors(ids: str = Query(..., description="ids separados por vírgula")):
    """Retorna a cor principal de até quatro times."""
    out = {}
    for raw in ids.split(",")[:4]:
        if raw.strip().isdigit():
            out[raw.strip()] = logos.team_color(int(raw))
    return out


@app.get("/api/h2h")
def h2h(team_a: int, team_b: int, f: Filters = Depends(filters)):
    """Retorna o confronto direto entre dois times."""
    return stats.head_to_head(team_a, team_b, f)


@app.get("/api/players")
def players(f: Filters = Depends(filters), metric: str = "rating", min_maps: int = 20,
            team_region: str | None = None, team_id: int | None = None, limit: int = Query(50, le=500)):
    """Lista o ranking de jogadores pela métrica escolhida."""
    if metric not in stats.PLAYER_METRICS:
        raise HTTPException(400, f"métrica inválida; use uma de {list(stats.PLAYER_METRICS)}")
    return records(stats.player_ranking(f, metric, min_maps, team_region=team_region or None,
                                        team_id=team_id, limit=limit))


@app.get("/api/players/featured")
def players_featured(f: Filters = Depends(filters), metric: str = "rating", min_maps: int = 20, count_min: int = 1,
                     rate_min: int = 20, team_region: str | None = None):
    """Retorna os jogadores em destaque com dados de foto e enquadramento."""
    leaders = stats.players_featured(f, metric, min_maps, count_min, rate_min, team_region or None)
    for p in leaders:
        meta = photos.photo_meta(p["player_id"])
        p["photo_url"] = f"/api/photo/player/{p['player_id']}?v={meta['version']}" if meta else None
        p["photo_source"] = meta["source"] if meta else None
        p["photo_credit"] = meta["credit"] if meta else None
        p["focus"] = photos.focus(p["player_id"]) if meta else None
    return leaders


@app.get("/api/players/metrics")
def player_metrics():
    """Lista as métricas de jogador disponíveis e seus rótulos."""
    return {k: v[0] for k, v in stats.PLAYER_METRICS.items()}


_eligible_cache: dict = {}


def _photo_players() -> set[int]:
    """Retorna (com cache por versão) os jogadores elegíveis a ter foto."""
    if _eligible_cache.get("version") != store.version:
        _eligible_cache.update(version=store.version, ids=photos.eligible_players(store["player_cube"]))
    return _eligible_cache["ids"]


@app.get("/api/players/{player_id}/hero")
def player_hero(player_id: int, f: Filters = Depends(filters)):
    """Retorna os dados do cabeçalho do jogador (mapas Tier 1 e foto)."""
    pc = store["player_cube"]
    t1 = int(pc.loc[(pc["player_id"] == player_id) & (pc["tier"] == 1), "maps"].sum())
    meta = photos.photo_meta(player_id) if player_id in _photo_players() else None
    return {"tier1_maps": t1, "photo_url": f"/api/photo/player/{player_id}?v={meta['version']}" if meta else None,
            "photo_portrait": bool(meta and meta["portrait"]),
            "photo_credit": meta["credit"] if meta else None, "photo_page": meta["page"] if meta else None}


@app.get("/api/photo/player/{player_id}", response_class=Response)
def player_photo(player_id: int):
    """Serve a foto em cache de um jogador."""
    got = photos.player_photo(player_id)
    if got is None:
        raise HTTPException(404, "sem foto")
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "max-age=604800"})


@app.get("/api/players/{player_id}/mvp-maps")
def player_mvp_maps(player_id: int, f: Filters = Depends(filters), offset: int = Query(0, ge=0),
                    limit: int = Query(10, ge=1, le=50)):
    """Lista de forma paginada os mapas em que o jogador foi MVP."""
    return matches.player_mvp_maps(player_id, f, offset, limit)


@app.get("/api/players/{player_id}")
def player(player_id: int, f: Filters = Depends(filters)):
    """Retorna os detalhes de um jogador."""
    d = stats.player_detail(player_id, f)
    if not d:
        raise HTTPException(404, "jogador não encontrado")
    return d


@app.get("/api/top-performances")
def top_performances(f: Filters = Depends(filters), metric: Literal["k", "rating", "acs"] = "k", limit: int = 25):
    """Lista as melhores atuações individuais pela métrica escolhida."""
    tp = f.apply(store["top_performances"])
    return records(tp.sort_values(metric, ascending=False).head(limit))


@app.get("/api/maps")
def maps(f: Filters = Depends(filters)):
    """Retorna as estatísticas por mapa."""
    return records(stats.map_table(f))


@app.get("/api/maps/featured")
def maps_featured(f: Filters = Depends(filters)):
    """Retorna o mapa e o agente em destaque com cores e nomes de exibição."""
    d = stats.maps_featured(f)
    if not d:
        return {}
    d["agent"]["colors"] = (assets.info("agent", d["agent"]["name"]) or {}).get("colors")
    d["agent"]["display_name"] = stats.agent_name(d["agent"]["name"])
    d["map"]["top_agent"]["display_name"] = stats.agent_name(d["map"]["top_agent"]["name"])
    return d


@app.get("/api/asset/{kind}/{name}/{field}", response_class=Response)
def asset(kind: Literal["map", "agent"], name: str, field: Literal["splash", "fullPortrait", "background"]):
    """Serve a imagem de um mapa ou agente vinda da valorant-api."""
    got = assets.image(kind, name, field)
    if got is None:
        raise HTTPException(404, "imagem indisponível")
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "max-age=604800"})


@app.get("/api/agents")
def agents(f: Filters = Depends(filters), map_name: str | None = None):
    """Retorna as estatísticas dos agentes, opcionalmente por mapa."""
    return records(stats.agent_table(f, map_name=map_name or None))


CHART_PARAMS = ("team_id", "player_id", "metric", "min_maps", "team_region", "map_name", "team_a", "team_b", "limit",
                "wide")


def chart_params(team_id: int | None = None, player_id: int | None = None, metric: str | None = None,
                 min_maps: int | None = None, team_region: str | None = None, map_name: str | None = None,
                 team_a: int | None = None, team_b: int | None = None, limit: int | None = None,
                 wide: bool = Query(False, description="versão larga para cartões de largura total")) -> tuple:
    """Agrupa os parâmetros opcionais de gráfico numa tupla ordenada e hashable."""
    local = locals()
    return tuple(sorted((k, local[k]) for k in CHART_PARAMS if local[k] not in (None, "", False)))


@app.get("/api/chart/{name}.png", response_class=Response)
def chart(name: str, f: Filters = Depends(filters), theme: Literal["dark", "light"] = "dark",
          params: tuple = Depends(chart_params)):
    """Serve um gráfico renderizado em PNG."""
    if name not in charts.CHARTS:
        raise HTTPException(404, f"gráfico desconhecido; disponíveis: {sorted(charts.CHARTS)}")
    png = charts.render(name, f, theme, params, store.version)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=300"})


@app.get("/api/chart-data/{name}")
def chart_json(name: str, f: Filters = Depends(filters), params: tuple = Depends(chart_params)):
    """Retorna a especificação JSON de um gráfico."""
    if name not in chart_data.SPECS:
        raise HTTPException(404, f"gráfico desconhecido; disponíveis: {sorted(chart_data.SPECS)}")
    return chart_data.build(name, f, params, store.version)
