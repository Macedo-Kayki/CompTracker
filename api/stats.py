from __future__ import annotations

import json

import numpy as np
import pandas as pd

import config
from api import countries
from api.store import Filters, store

INTERNATIONAL_TYPES = ("Masters", "Champions")

PLAYER_METRICS = {
    "rating": ("Rating", "rating"), "acs": ("ACS", "acs"), "kills": ("Kills", "k"),
    "kd": ("K/D", "kd"), "kpr": ("Kills por round", "kpr"), "adr": ("ADR", "adr"),
    "kast": ("KAST %", "kast"), "hs": ("HS %", "hs"), "fk": ("First kills", "fk"),
    "clutches": ("Clutches", "clutches"), "aces": ("Aces (5K)", "k5"), "k4": ("Quadra kills (4K)", "k4"),
    "k3": ("Triple kills (3K)", "k3"), "k2": ("Double kills (2K)", "k2"), "assists": ("Assistências", "a"),
}


def _ratio(num, den):
    """Divide elemento a elemento, retornando NaN quando o denominador é zero."""
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _clean(df: pd.DataFrame) -> list[dict]:
    """Converte o DataFrame em lista de dicts JSON, trocando NaN e infinito por None."""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


records = _clean


def _one(row: dict) -> dict:
    """Converte um único dict de linha em registro JSON limpo."""
    return _clean(pd.DataFrame([row]))[0]


TEAM_SUMS = ["matches", "match_wins", "maps", "map_wins", "rounds_won", "rounds_lost", "atk_won", "atk_played",
             "def_won", "def_played", "ot_won", "ot_played", "picks", "pick_wins", "pistols_won", "pistols_played",
             "start_atk_maps", "start_atk_wins", "start_def_maps", "start_def_wins"]


def _team_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula as taxas de vitória (partida, mapa, round, lados, pistol) dos times."""
    df = df.copy()
    df["match_wr"] = _ratio(df["match_wins"], df["matches"])
    df["map_wr"] = _ratio(df["map_wins"], df["maps"])
    df["round_wr"] = _ratio(df["rounds_won"], df["rounds_won"] + df["rounds_lost"])
    df["atk_wr"] = _ratio(df["atk_won"], df["atk_played"])
    df["def_wr"] = _ratio(df["def_won"], df["def_played"])
    df["pistol_wr"] = _ratio(df["pistols_won"], df["pistols_played"])
    df["pick_wr"] = _ratio(df["pick_wins"], df["picks"])
    df["best_side"] = np.where(df["atk_wr"] > df["def_wr"], "Ataque", "Defesa")
    return df


def titles(f: Filters) -> pd.DataFrame:
    """Retorna os eventos com campeão definido no filtro, do mais recente ao mais antigo."""
    ev = f.apply(store["dim_events"])
    return ev[ev["champion_id"].notna()].sort_values("end_date", ascending=False)


def team_table(f: Filters, team_region: str | None = None, min_maps: int = 0) -> pd.DataFrame:
    """Monta a tabela de times com somas, taxas, títulos e finais no filtro."""
    cube = f.apply(store["team_cube"])
    agg = cube.groupby("team_id", as_index=False)[TEAM_SUMS].sum()
    t = titles(f)
    tcount = t.groupby("champion_id").size().rename("titles")
    intl = t[t["event_type"].isin(INTERNATIONAL_TYPES)].groupby("champion_id").size().rename("intl_titles")
    finals = pd.concat([t["champion_id"], t["runner_up_id"]]).dropna().astype(int).value_counts().rename("finals")
    agg = (agg.merge(store["dim_teams"], on="team_id", how="left")
              .merge(tcount, left_on="team_id", right_index=True, how="left")
              .merge(intl, left_on="team_id", right_index=True, how="left")
              .merge(finals, left_on="team_id", right_index=True, how="left"))
    agg[["titles", "intl_titles", "finals"]] = agg[["titles", "intl_titles", "finals"]].fillna(0).astype(int)
    if team_region:
        agg = agg[agg["team_region"] == team_region]
    agg = agg[agg["maps"] >= min_maps]
    return _team_rates(agg)


def team_detail(team_id: int, f: Filters) -> dict:
    """Monta o detalhe de um time: resumo, por ano, por mapa, títulos e partidas."""
    cube = f.apply(store["team_cube"])
    cube = cube[cube["team_id"] == team_id]
    dim = store["dim_teams"].set_index("team_id")
    if team_id not in dim.index:
        return {}
    total = _one(_team_rates(cube[TEAM_SUMS].sum().to_frame().T).iloc[0].to_dict())
    by_year = _team_rates(cube.groupby("year", as_index=False)[TEAM_SUMS].sum())
    tm = f.apply(store["team_map_cube"])
    tm = tm[tm["team_id"] == team_id]
    by_map = _team_rates(tm.groupby("map_name", as_index=False)[[c for c in TEAM_SUMS if c in tm]].sum()
                         .assign(matches=0, match_wins=0, pistols_won=0, pistols_played=0))
    t = titles(f)
    won = t[t["champion_id"] == team_id][["event_id", "name", "year", "tier", "event_type", "region", "end_date",
                                          "champion_prize_usd", "prize_usd"]]
    tp = f.apply(store["team_prizes"])
    tp = tp[tp["team_id"] == team_id]
    total["prize_won_usd"] = float(tp["prize_usd"].fillna(0).sum())
    total["prize_events"] = int((tp["prize_usd"].fillna(0) > 0).sum())
    finals_lost = t[t["runner_up_id"] == team_id][["event_id", "name", "year", "champion_name"]]
    mf = f.apply(store["matches_fact"])
    recent = mf[(mf["team1_id"] == team_id) | (mf["team2_id"] == team_id)].sort_values("match_date", ascending=False).head(15)
    return {
        "team": _one({"team_id": team_id, **dim.loc[team_id].to_dict()}),
        "summary": total, "by_year": records(by_year), "by_map": records(by_map.sort_values("maps", ascending=False)),
        "titles": records(won), "finals_lost": records(finals_lost),
        "players": records(player_table(f, team_id=team_id, min_maps=0).head(15)),
        "recent": records(recent),
    }


PLAYER_SUMS = ["maps", "map_wins", "rounds", "k", "d", "a", "fk", "fd", "k_atk", "k_def", "d_atk", "d_def",
               "rating_x_rounds", "rating_rounds", "acs_x_rounds", "acs_rounds", "adr_x_rounds", "adr_rounds",
               "kast_x_rounds", "kast_rounds", "hs_x_kills", "hs_kills", "perf_maps", "k2", "k3", "k4", "k5",
               "c1v1", "c1v2", "c1v3", "c1v4", "c1v5", "clutches", "plants", "defuses"]


def _player_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula as médias ponderadas e taxas dos jogadores (rating, ACS, HS, K/D)."""
    df = df.copy()
    df["rating"] = _ratio(df["rating_x_rounds"], df["rating_rounds"])
    df["acs"] = _ratio(df["acs_x_rounds"], df["acs_rounds"])
    df["adr"] = _ratio(df["adr_x_rounds"], df["adr_rounds"])
    df["kast"] = _ratio(df["kast_x_rounds"], df["kast_rounds"])
    df["hs"] = _ratio(df["hs_x_kills"], df["hs_kills"])
    df["kd"] = _ratio(df["k"], df["d"])
    df["kpr"] = _ratio(df["k"], df["rounds"])
    df["map_wr"] = _ratio(df["map_wins"], df["maps"])
    df["fk_diff"] = df["fk"] - df["fd"]
    df["multikills"] = df["k2"] + df["k3"] + df["k4"] + df["k5"]
    drop = [c for c in df.columns if c.endswith("_x_rounds") or c.endswith("_rounds") and c != "rounds"
            or c in ("hs_x_kills", "hs_kills")]
    return df.drop(columns=drop)


def player_table(f: Filters, team_id: int | None = None, team_region: str | None = None,
                 min_maps: int = 0) -> pd.DataFrame:
    """Monta a tabela de jogadores com seu time principal e métricas no filtro."""
    cube = f.apply(store["player_cube"])
    if team_id is not None:
        cube = cube[cube["team_id"] == team_id]
    agg = cube.groupby("player_id", as_index=False)[PLAYER_SUMS].sum()
    main_team = (cube.groupby(["player_id", "team_id"])["maps"].sum().reset_index()
                 .sort_values("maps", ascending=False).drop_duplicates("player_id")[["player_id", "team_id"]])
    agg = (agg.merge(main_team, on="player_id", how="left")
              .merge(store["dim_players"][["player_id", "player_name", "country", "current_team_name"]], on="player_id", how="left")
              .merge(store["dim_teams"][["team_id", "team_name", "team_region"]], on="team_id", how="left"))
    if team_region:
        agg = agg[agg["team_region"] == team_region]
    agg = agg[agg["maps"] >= min_maps]
    return _player_rates(agg).sort_values("rating", ascending=False)


def player_ranking(f: Filters, metric: str, min_maps: int, team_region: str | None = None,
                   team_id: int | None = None, limit: int = 50) -> pd.DataFrame:
    """Ordena os jogadores pela métrica escolhida e retorna os primeiros."""
    col = PLAYER_METRICS[metric][1]
    df = player_table(f, team_id=team_id, team_region=team_region, min_maps=min_maps)
    return df.sort_values(col, ascending=False, na_position="last").head(limit)


def _metric_text(col, v) -> str:
    """Formata o valor de uma métrica de jogador para exibição."""
    if v is None or pd.isna(v):
        return "—"
    if col in ("hs", "kast"):
        return f"{v:.1f}%".replace(".", ",")
    if col in ("rating", "kd", "kpr"):
        return f"{v:.2f}".replace(".", ",")
    return f"{int(round(v)):,}".replace(",", ".")


def players_featured(f: Filters, metric: str, min_maps: int, count_min: int, rate_min: int,
                     team_region: str | None = None) -> list[dict]:
    """Escolhe os jogadores líderes de várias métricas para os destaques."""
    label, col = PLAYER_METRICS.get(metric, PLAYER_METRICS["rating"])
    counts = player_table(f, team_region=team_region, min_maps=count_min)
    rates = player_table(f, team_region=team_region, min_maps=rate_min)
    picks = []

    def top(df, key, title, chart):
        """Adiciona aos destaques o líder do DataFrame na métrica informada."""
        df = df.dropna(subset=[key])
        df = df[df[key] > 0] if key not in ("rating", "hs") else df
        if not df.empty:
            r = df.sort_values(key, ascending=False).iloc[0]
            picks.append((int(r["player_id"]), title, _metric_text(key, r[key]), chart, r))

    top(player_table(f, team_region=team_region, min_maps=min_maps), col, label, "player_top")
    top(counts.assign(_c=counts[["c1v1", "c1v2", "c1v3", "c1v4", "c1v5"]].sum(axis=1)), "_c", "Clutches", "player_clutches")
    top(counts.assign(_m=counts[["k2", "k3", "k4", "k5"]].sum(axis=1)), "_m", "Multikills", "player_multikills")
    top(rates, "hs", "HS %", "hs_distribution")
    top(rates, "rating", "Rating", "rating_vs_hs")
    out, seen = [], {}
    for pid, title, value, chart, r in picks:
        if pid in seen:
            if not any(l["title"] == title and l["value"] == value for l in seen[pid]["leads"]):
                seen[pid]["leads"].append({"title": title, "value": value, "chart": chart})
            continue
        rec = {"player_id": pid, "player_name": r["player_name"],
               "team_id": None if pd.isna(r.get("team_id")) else int(r["team_id"]),
               "team_name": r.get("team_name") if isinstance(r.get("team_name"), str) else None,
               "leads": [{"title": title, "value": value, "chart": chart}]}
        seen[pid] = rec
        out.append(rec)
    return out


def player_detail(player_id: int, f: Filters) -> dict:
    """Monta o detalhe de um jogador: resumo, por ano, times, agentes e melhores mapas."""
    dim = store["dim_players"].set_index("player_id")
    if player_id not in dim.index:
        return {}
    cube = f.apply(store["player_cube"])
    cube = cube[cube["player_id"] == player_id]
    total = _one(_player_rates(cube[PLAYER_SUMS].sum().to_frame().T).iloc[0].to_dict())
    by_year = _player_rates(cube.groupby("year", as_index=False)[PLAYER_SUMS].sum())
    teams = (_player_rates(cube.groupby("team_id", as_index=False)[PLAYER_SUMS].sum())
             .merge(store["dim_teams"][["team_id", "team_name"]], on="team_id", how="left"))
    pa = f.apply(store["player_agent_cube"])
    agents = pa[pa["player_id"] == player_id].groupby("agent", as_index=False)[
        ["maps", "wins", "k", "d", "rounds", "rating_x_rounds", "rating_rounds"]].sum()
    agents["rating"] = _ratio(agents["rating_x_rounds"], agents["rating_rounds"])
    agents["win_rate"] = _ratio(agents["wins"], agents["maps"])
    agents["kd"] = _ratio(agents["k"], agents["d"])
    pmf = store["player_maps_fact"]
    best = f.apply(pmf[pmf["player_id"] == player_id]).sort_values(["rating", "k"], ascending=False).head(10)
    names = store["dim_teams"].set_index("team_id")["team_name"]
    events = store["dim_events"].set_index("event_id")["name"]
    best = best.assign(team_name=best["team_id"].map(names), opp_name=best["opp_id"].map(names),
                       event_name=best["event_id"].map(events))
    player = _one({"player_id": player_id, **dim.loc[player_id].to_dict()})
    player["country"] = countries.pt(player.get("country"))
    return {"player": player, "summary": total,
            "by_year": records(by_year), "by_team": records(teams.sort_values("maps", ascending=False)),
            "agents": records(agents.drop(columns=["rating_x_rounds", "rating_rounds"]).sort_values("maps", ascending=False)),
            "best_maps": records(best)}


def map_table(f: Filters) -> pd.DataFrame:
    """Monta a tabela de mapas com win rate por lado, prorrogação e duração."""
    mc = f.apply(store["map_cube"])
    agg = mc.groupby("map_name", as_index=False)[["maps", "atk_won", "def_won", "ot_maps", "picks",
                                                  "duration_sum", "duration_maps"]].sum()
    agg["atk_wr"] = _ratio(agg["atk_won"], agg["atk_won"] + agg["def_won"])
    agg["def_wr"] = 1 - agg["atk_wr"]
    agg["play_rate"] = agg["maps"] / max(1, agg["maps"].sum())
    agg["ot_rate"] = _ratio(agg["ot_maps"], agg["maps"])
    agg["avg_duration_min"] = _ratio(agg["duration_sum"], agg["duration_maps"]) / 60
    return agg.sort_values("maps", ascending=False)


def agent_table(f: Filters, map_name: str | None = None) -> pd.DataFrame:
    """Monta a tabela de agentes com pick rate, win rate e K/D."""
    ac = f.apply(store["agent_cube"])
    if map_name:
        ac = ac[ac["map_name"] == map_name]
    agg = ac.groupby("agent", as_index=False)[["picks", "wins", "rounds", "k", "d"]].sum()
    total_maps = max(1, agg["picks"].sum() / 10)
    agg["pick_rate"] = agg["picks"] / total_maps
    agg["win_rate"] = _ratio(agg["wins"], agg["picks"])
    agg["kd"] = _ratio(agg["k"], agg["d"])
    return agg.sort_values("picks", ascending=False)


AGENT_NAMES = {"kayo": "KAY/O"}


def agent_name(agent) -> str:
    """Retorna o nome de exibição de um agente."""
    agent = str(agent or "")
    return AGENT_NAMES.get(agent, agent.capitalize())


def maps_featured(f: Filters) -> dict:
    """Retorna o mapa e o agente mais jogados, com seus melhores pares."""
    mc = f.apply(store["map_cube"])
    ac = f.apply(store["agent_cube"])
    ac = ac[ac["agent"].str.fullmatch(r"[a-z]+", na=False)]
    if mc.empty or ac.empty:
        return {}
    maps = mc.groupby("map_name")["maps"].sum()
    picks = ac.groupby("agent")["picks"].sum()
    top_map, top_agent = maps.idxmax(), picks.idxmax()
    on_map = ac[ac["map_name"] == top_map].groupby("agent")["picks"].sum()
    agent_maps = ac[ac["agent"] == top_agent].groupby("map_name")["picks"].sum()
    rate = lambda n, m: float(n / (2 * maps.get(m, 0))) if maps.get(m, 0) else None
    best_agent, best_map = on_map.idxmax(), agent_maps.idxmax()
    return {
        "map": {"name": top_map, "maps": int(maps[top_map]), "share": float(maps[top_map] / maps.sum()),
                "top_agent": {"name": best_agent, "picks": int(on_map[best_agent]), "rate": rate(on_map[best_agent], top_map)}},
        "agent": {"name": top_agent, "picks": int(picks[top_agent]), "rate": float(picks[top_agent] / (2 * maps.sum())),
                  "best_map": {"name": best_map, "picks": int(agent_maps[best_map]), "rate": rate(agent_maps[best_map], best_map)}},
    }


def side_summary(f: Filters) -> dict:
    """Resume os rounds vencidos por lado e os pistols no filtro."""
    mc = f.apply(store["map_cube"])
    atk, dfn = mc["atk_won"].sum(), mc["def_won"].sum()
    rc = f.apply(store["round_cube"])
    pistol = rc[rc["round_kind"] == "pistol"].groupby("winner_side")["rounds"].sum()
    return {"atk_rounds": int(atk), "def_rounds": int(dfn),
            "atk_wr": float(atk / (atk + dfn)) if atk + dfn else None,
            "pistol_atk": int(pistol.get("atk", 0)), "pistol_def": int(pistol.get("def", 0))}


def overview(f: Filters) -> dict:
    """Retorna os totais gerais (eventos, partidas, mapas, kills, prêmios) no filtro."""
    tc, pc, mf = f.apply(store["team_cube"]), f.apply(store["player_cube"]), f.apply(store["matches_fact"])
    ev = f.apply(store["dim_events"])
    return {
        "events": int(ev["event_id"].nunique()), "matches": int(len(mf)), "maps": int(tc["maps"].sum() // 2),
        "rounds": int(tc["rounds_won"].sum()), "teams": int(tc["team_id"].nunique()),
        "players": int(pc["player_id"].nunique()), "kills": int(pc["k"].sum()), "aces": int(pc["k5"].sum()),
        "clutches": int(pc["clutches"].sum()), "prize_usd": float(ev["prize_usd"].fillna(0).sum()),
        "sides": side_summary(f),
    }


def head_to_head(team_a: int, team_b: int, f: Filters) -> dict:
    """Retorna as vitórias e as partidas do confronto direto entre dois times."""
    mf = f.apply(store["matches_fact"])
    pair = mf[((mf["team1_id"] == team_a) & (mf["team2_id"] == team_b))
              | ((mf["team1_id"] == team_b) & (mf["team2_id"] == team_a))].sort_values("match_date", ascending=False)
    wins_a = int((pair["winner_id"] == team_a).sum())
    wins_b = int((pair["winner_id"] == team_b).sum())
    dim = store["dim_teams"].set_index("team_id")
    name = lambda t: dim.loc[t, "team_name"] if t in dim.index else str(t)
    return {"team_a": {"team_id": team_a, "name": name(team_a), "wins": wins_a},
            "team_b": {"team_id": team_b, "name": name(team_b), "wins": wins_b},
            "matches": records(pair)}


PHOTO_DIR = config.ROOT / "web" / "img" / "titulos"


def _photo(event_id: int) -> tuple[str | None, str | None]:
    """Retorna a URL e o crédito da foto do título de um evento, se existir."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        if (PHOTO_DIR / f"{event_id}.{ext}").exists():
            credits_file = PHOTO_DIR / "creditos.json"
            credits = json.loads(credits_file.read_text(encoding="utf-8")) if credits_file.exists() else {}
            return f"/static/img/titulos/{event_id}.{ext}", (credits.get(str(event_id)) or {}).get("credit")
    return None, None


def _bracket_stage(mf: pd.DataFrame) -> pd.DataFrame:
    """Seleciona as partidas da fase de playoffs de um evento."""
    if mf.empty:
        return mf
    stages = mf["stage_label"].fillna("")
    if (stages == "Playoffs").any():
        return mf[stages == "Playoffs"]
    gf = mf[mf["round_label"].fillna("").str.contains("Grand Final", case=False)]
    if not gf.empty:
        return mf[stages == gf["stage_label"].iloc[0]]
    return mf.iloc[0:0]


def event_detail(event_id: int) -> dict:
    """Monta o detalhe de um evento, com foto e indicação de chaveamento."""
    ev = store["dim_events"]
    row = ev[ev["event_id"] == event_id]
    if row.empty:
        return {}
    d = _one(row.iloc[0].to_dict())
    mf = store["matches_fact"]
    playoffs = _bracket_stage(mf[mf["event_id"] == event_id])
    d["photo_url"], d["photo_credit"] = _photo(event_id)
    d["has_bracket"] = bool(d.get("tier") == 1 and not playoffs.empty)
    d["matches"] = int((mf["event_id"] == event_id).sum())
    return d


def bracket(event_id: int) -> dict:
    """Monta o chaveamento de playoffs de um evento separado por chave e rodada."""
    mf = store["matches_fact"]
    games = _bracket_stage(mf[mf["event_id"] == event_id]).copy()
    if games.empty:
        return {"sections": []}
    games["round_label"] = games["round_label"].fillna("Rodada")

    def section(label: str) -> str:
        """Classifica o rótulo da rodada em chave superior, inferior, média ou final."""
        low = label.lower()
        if "grand final" in low:
            return "final"
        if low.startswith("lower"):
            return "lower"
        if low.startswith("middle"):
            return "middle"
        return "upper"

    games["section"] = games["round_label"].map(section)
    names = {"upper": "Chave superior", "middle": "Chave intermediária", "lower": "Chave inferior", "final": "Grande final"}
    out = []
    for key in ("upper", "middle", "lower", "final"):
        part = games[games["section"] == key]
        if part.empty:
            continue
        order = part.groupby("round_label")["match_date"].min().sort_values().index
        rounds = [{"label": lab, "matches": records(part[part["round_label"] == lab]
                                                    .sort_values(["match_date", "match_id"]))} for lab in order]
        out.append({"key": key, "name": names[key], "rounds": rounds})
    return {"sections": out}


def _featured(t: pd.DataFrame) -> dict:
    """Escolhe o título em destaque, preferindo eventos com foto."""
    if t.empty:
        return {}
    ids = [int(e) for e in t["event_id"]]
    pick = next((e for e in ids if _photo(e)[0]), ids[0])
    return event_detail(pick)


def team_featured_title(team_id: int) -> dict:
    """Retorna o título Tier 1 em destaque de um time."""
    t = titles(Filters(tier=1))
    return _featured(t[t["champion_id"] == team_id])


def featured_title(f: Filters) -> dict:
    """Retorna o título Tier 1 em destaque no filtro atual."""
    return _featured(titles(Filters(year=f.year, tier=1, region=f.region, event_type=f.event_type, event_id=f.event_id)))
