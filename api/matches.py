from __future__ import annotations

import gzip
from functools import lru_cache

import pandas as pd

import config
from api.stats import records
from api.store import Filters, store
from etl.parsers import parse_kill_matrix, parse_match_page

SUM_COLS = ("k", "d", "a", "fk", "fd")
ROUND_COLS = ("rating", "acs", "adr", "kast")


def team_matches(team_id: int, f: Filters, offset: int = 0, limit: int = 10) -> dict:
    """Lista as partidas de um time no filtro atual, de forma paginada."""
    mf = f.apply(store["matches_fact"])
    mine = mf[(mf["team1_id"] == team_id) | (mf["team2_id"] == team_id)]
    mine = mine.sort_values(["match_date", "match_id"], ascending=False)
    page = mine.iloc[offset:offset + limit]
    return {"total": int(len(mine)), "offset": offset, "matches": records(page)}


@lru_cache(maxsize=2)
def _mvps(version: int) -> pd.DataFrame:
    """Calcula o MVP de cada time em cada mapa e marca quem foi MVP da partida."""
    pmf = store["player_maps_fact"].dropna(subset=["rating"])
    ranked = pmf.sort_values(["game_id", "rating", "acs"], ascending=[True, False, False])
    team = ranked.drop_duplicates(["game_id", "team_id"])[["game_id", "player_id"]]
    match = set(ranked.drop_duplicates("game_id")["player_id"].astype(str) + ":" + ranked.drop_duplicates("game_id")["game_id"].astype(str))
    team = team.assign(mvp_kind=["match" if f"{p}:{g}" in match else "team" for p, g in zip(team["player_id"], team["game_id"])])
    return team


def player_mvp_maps(player_id: int, f: Filters, offset: int = 0, limit: int = 10) -> dict:
    """Lista os mapas em que o jogador foi MVP, com contagem por tipo."""
    mvp = _mvps(store.version)
    mine = mvp[mvp["player_id"] == player_id][["game_id", "mvp_kind"]]
    pmf = f.apply(store["player_maps_fact"])
    rows = pmf[pmf["player_id"] == player_id].merge(mine, on="game_id")
    rows = rows.sort_values(["match_date", "game_id"], ascending=False)
    counts = rows["mvp_kind"].value_counts()
    page = rows.iloc[offset:offset + limit][["game_id", "match_id", "map_name", "agent", "won", "k", "d", "a", "acs",
                                             "rating", "adr", "hs", "fk", "team_id", "mvp_kind"]]
    info = store["matches_fact"].drop(columns=["year"], errors="ignore")
    page = page.merge(info, on="match_id", how="left")
    out = records(page)
    for r in out:
        if isinstance(r.get("match_date"), pd.Timestamp):
            r["match_date"] = r["match_date"].date().isoformat()
    return {"total": int(len(rows)), "offset": offset, "matches": out,
            "match_mvps": int(counts.get("match", 0)), "team_mvps": int(counts.get("team", 0))}


def _bronze(kind: str, match_id: int, year) -> str | None:
    """Lê o HTML compactado de uma partida na camada bronze, procurando por ano."""
    years = [int(year)] if year and not pd.isna(year) else []
    years += [y for y in range(config.START_DATE.year, config.END_DATE.year + 1) if y not in years]
    for y in years:
        path = config.BRONZE_DIR / kind / f"year={y}" / f"{match_id}.html.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return fh.read()
    return None


def _num(v):
    """Troca valores NaN por None."""
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def _players(rows: list[dict], names: dict) -> list[dict]:
    """Monta as linhas de jogadores de um mapa, ordenadas por ACS."""
    out = []
    for r in rows:
        rec = {k: _num(r.get(k)) for k in ("player_id", "team_id", "agent", "rating", "acs", "k", "d", "a", "kast",
                                           "adr", "hs", "fk", "fd")}
        rec["player_name"] = names.get(r.get("player_id")) or r.get("player_name")
        rec["raw_name"] = r.get("player_name")
        out.append(rec)
    return sorted(out, key=lambda p: -(p["acs"] or 0))


def _total_players(rows: list[dict], rounds_by_game: dict, names: dict) -> list[dict]:
    """Agrega as estatísticas dos jogadores em todos os mapas da partida."""
    acc = {}
    for r in rows:
        pid = r.get("player_id")
        n = rounds_by_game.get(r["game_id"], 0)
        a = acc.setdefault(pid, {"player_id": pid, "team_id": r.get("team_id"), "player_name": names.get(pid) or r.get("player_name"),
                                 "raw_name": r.get("player_name"), "agents": [], "_n": {}, "_w": {}, "_hs": 0.0, "_hsk": 0})
        if r.get("agent") and r["agent"] not in a["agents"]:
            a["agents"].append(r["agent"])
        for c in SUM_COLS:
            a[c] = a.get(c, 0) + (r.get(c) or 0)
        for c in ROUND_COLS:
            if r.get(c) is not None and n:
                a["_w"][c] = a["_w"].get(c, 0) + r[c] * n
                a["_n"][c] = a["_n"].get(c, 0) + n
        if r.get("hs") is not None and r.get("k"):
            a["_hs"] += r["hs"] * r["k"]
            a["_hsk"] += r["k"]
    out = []
    for a in acc.values():
        for c in ROUND_COLS:
            a[c] = round(a["_w"][c] / a["_n"][c], 3 if c == "rating" else 1) if a["_n"].get(c) else None
        a["hs"] = round(a["_hs"] / a["_hsk"], 1) if a["_hsk"] else None
        a["agent"] = a["agents"][0] if a["agents"] else None
        for k in ("_n", "_w", "_hs", "_hsk"):
            a.pop(k)
        out.append(a)
    return sorted(out, key=lambda p: -(p["acs"] or 0))


def _matrix(raw: dict, players: list[dict], team1_id) -> dict | None:
    """Monta a matriz de abates, alinhando as linhas ao time 1."""
    if not raw:
        return None
    ids = {}
    for key in ("raw_name", "player_name"):
        for p in players:
            ids.setdefault((p.get(key) or "").lower(), (p["player_id"], p["team_id"]))
    names = {p["player_id"]: p["player_name"] for p in players}

    def who(x):
        """Identifica jogador e time a partir do nome na matriz."""
        pid, tid = ids.get(x["name"].lower(), (None, None))
        return {"player_id": pid, "team_id": tid, "name": names.get(pid) or x["name"]}

    rows, cols = [who(x) for x in raw["rows"]], [who(x) for x in raw["cols"]]
    kills, deaths = raw["kills"], raw["deaths"]
    rows_team = next((r["team_id"] for r in rows if r["team_id"]), None)
    if rows_team is not None and team1_id is not None and rows_team != team1_id:
        rows, cols = cols, rows
        kills, deaths = [list(c) for c in zip(*deaths)], [list(c) for c in zip(*kills)]
    return {"rows": rows, "cols": cols, "kills": kills, "deaths": deaths}


def _strip(players: list[dict]) -> list[dict]:
    """Remove o nome bruto dos jogadores antes de responder."""
    for p in players:
        p.pop("raw_name", None)
    return players


@lru_cache(maxsize=256)
def _detail(match_id: int, version: int) -> dict | None:
    """Monta (com cache) o detalhe completo de uma partida a partir do HTML bronze."""
    mf = store["matches_fact"]
    row = mf[mf["match_id"] == match_id]
    year = row["year"].iloc[0] if len(row) else None
    html = _bronze("matches", match_id, year)
    if html is None:
        return None
    parsed = parse_match_page(html, match_id)
    perf = _bronze("performance", match_id, year)
    matrices = parse_kill_matrix(perf) if perf else {}
    names = store["dim_players"].set_index("player_id")["player_name"].to_dict()
    head = records(row)[0] if len(row) else parsed["match"]
    if isinstance(head.get("match_date"), pd.Timestamp):
        head["match_date"] = head["match_date"].date().isoformat()
    t1, t2 = parsed["match"]["team1_id"], parsed["match"]["team2_id"]

    rounds_by_game, maps = {}, []
    for m in sorted(parsed["maps"], key=lambda x: x["map_order"]):
        gid = m["game_id"]
        rows = [p for p in parsed["players"] if p["game_id"] == gid]
        if not rows and m["team1_score"] is None:
            continue
        rounds_by_game[gid] = (m["team1_score"] or 0) + (m["team2_score"] or 0)
        rounds = [{"n": r["round_no"], "winner": 1 if r["winner_id"] == t1 else 2, "side": r["winner_side"],
                   "type": r["win_type"], "score": r["score_after"]}
                  for r in sorted((r for r in parsed["rounds"] if r["game_id"] == gid), key=lambda r: r["round_no"] or 0)]
        players = _players(rows, names)
        matrix = {k: _matrix(v, players, t1) for k, v in matrices.get(str(gid), {}).items()}
        maps.append({**{k: _num(v) for k, v in m.items()}, "rounds": rounds, "players": _strip(players), "matrix": matrix})

    every = [p for p in parsed["players"] if p["game_id"] in rounds_by_game]
    total = _total_players(every, rounds_by_game, names)
    matrix = {k: _matrix(v, total, t1) for k, v in matrices.get("all", {}).items()}
    out_total = {"players": _strip(total), "matrix": matrix}
    return {"match": head, "team1_id": t1, "team2_id": t2, "veto": parsed["match"].get("veto"),
            "maps": maps, "total": out_total}


def match_detail(match_id: int) -> dict | None:
    """Retorna o detalhe de uma partida para a versão atual dos dados."""
    return _detail(int(match_id), store.version)
