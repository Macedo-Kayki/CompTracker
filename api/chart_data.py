from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from api import stats
from api.charts import EVENT_ORDER, _short
from api.store import Filters, store


def _num(v, nd=4):
    """Converte um valor para float arredondado, retornando None se inválido ou NaN."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else round(v, nd)


def _nums(values, nd=4):
    """Aplica _num a uma sequência de valores."""
    return [_num(v, nd) for v in values]


def _int_txt(v):
    """Formata um inteiro com separador de milhar por ponto."""
    return f"{int(v):,}".replace(",", ".")


def _pct_txt(v, nd=0):
    """Formata uma fração como porcentagem com vírgula decimal."""
    return f"{v * 100:.{nd}f}%".replace(".", ",")


def _ids(values):
    """Converte uma sequência de IDs para int, trocando nulos por None."""
    return [None if pd.isna(v) else int(v) for v in values]


def _empty(msg="Sem dados para o filtro atual"):
    """Monta a especificação de gráfico vazio com uma mensagem."""
    return {"kind": "empty", "message": msg}


def _bars(title, subtitle, labels, datasets, fmt, **extra):
    """Monta a especificação JSON de um gráfico de barras."""
    return {"kind": "bar", "title": title, "subtitle": subtitle, "labels": [str(x) for x in labels],
            "datasets": datasets, "fmt": fmt, **extra}


def _player_labels(df):
    """Gera rótulos "jogador · time" para cada linha do DataFrame."""
    return [f"{p} · {_short(tm, 20)}" if isinstance(tm, str) else p for p, tm in zip(df["player_name"], df["team_name"])]


def matches_by_year(f, **_):
    """Gera os dados do gráfico de partidas por ano."""
    mf = f.apply(store["matches_fact"])
    if mf.empty:
        return _empty()
    s = mf.groupby("year").size()
    return _bars("Partidas por ano", "Partidas concluídas no filtro atual", s.index.astype(int),
                 [{"label": "Partidas", "data": [int(v) for v in s.values], "color": "main"}], "int", end="value")


def matches_by_tier(f, **_):
    """Gera os dados do gráfico de partidas por ano empilhadas por tier."""
    mf = f.apply(store["matches_fact"])
    if mf.empty:
        return _empty()
    p = mf.groupby(["year", "tier"]).size().unstack(fill_value=0).reindex(columns=[1, 2, 3], fill_value=0)
    return _bars("Partidas por ano e tier", "Tier 1 = VCT · Tier 2 = Challengers/Ascension · Tier 3 = prêmio ≥ US$ 5 mil",
                 p.index.astype(int),
                 [{"label": f"Tier {tier}", "data": [int(v) for v in p[tier]], "color": f"s{i}"} for i, tier in enumerate(p.columns)],
                 "int", stacked=True, end="total")


def side_by_year(f, **_):
    """Gera a linha de % de rounds vencidos por ataque e defesa a cada ano."""
    mc = f.apply(store["map_cube"])
    if mc.empty:
        return _empty()
    g = mc.groupby("year")[["atk_won", "def_won"]].sum()
    atk = g["atk_won"] / (g["atk_won"] + g["def_won"])
    lo, hi = float(min(atk.min(), 1 - atk.max())), float(max(atk.max(), 1 - atk.min()))
    return {"kind": "line", "title": "Lado que mais vence rounds", "subtitle": "% dos rounds do tempo regulamentar vencidos por lado",
            "labels": [str(int(y)) for y in g.index], "fmt": "pct1", "end": "last",
            "datasets": [{"label": "Ataque", "data": _nums(atk), "color": "atk"},
                         {"label": "Defesa", "data": _nums(1 - atk), "color": "def"}],
            "y": {"min": min(0.44, lo - 0.01), "max": max(0.56, hi + 0.01), "fmt": "pct0"},
            "refs": [{"axis": "y", "value": 0.5}]}


def win_types(f, **_):
    """Gera a participação de cada tipo de vitória de round por lado."""
    rc = f.apply(store["round_cube"])
    if rc.empty:
        return _empty()
    names = {("atk", "elim"): "Ataque · eliminação", ("atk", "boom"): "Ataque · spike detonada",
             ("def", "elim"): "Defesa · eliminação", ("def", "defuse"): "Defesa · spike desarmada",
             ("def", "time"): "Defesa · tempo esgotado"}
    g = rc.groupby(["winner_side", "win_type"])["rounds"].sum()
    total = g.sum()
    share = {k: float(g.get(k, 0) / total) for k in names}
    return _bars("Como os rounds são vencidos", "Participação de cada tipo de vitória no total de rounds",
                 list(names.values()),
                 [{"label": "Ataque", "data": [_num(share[k]) if k[0] == "atk" else None for k in names], "color": "atk"},
                  {"label": "Defesa", "data": [_num(share[k]) if k[0] == "def" else None for k in names], "color": "def"}],
                 "pct1", horizontal=True, stacked=True, end="total", x={"fmt": "pct0"})


def _titles_stack(g, types, title, subtitle, logos=None):
    """Monta barras horizontais empilhadas de títulos por tipo de evento."""
    return _bars(title, subtitle, [_short(n) for n in g.index],
                 [{"label": ty, "data": [int(v) for v in g[ty]], "color": f"ev:{ty}"} for ty in types],
                 "int", horizontal=True, stacked=True, end="total", logos=logos)


def titles_top(f, limit=15, **_):
    """Gera o ranking dos times com mais títulos, por tipo de evento."""
    ti = stats.titles(f)
    if ti.empty:
        return _empty("Nenhum título no filtro atual")
    g = ti.groupby(["champion_name", "event_type"]).size().unstack(fill_value=0)
    types = [c for c in EVENT_ORDER if c in g.columns]
    g["total"] = g[types].sum(axis=1)
    intl = [c for c in ("Champions", "Masters") if c in g.columns]
    g["_intl"] = g[intl].sum(axis=1) if intl else 0
    g = g.sort_values(["total", "_intl"], ascending=False).head(int(limit))
    ids = ti.drop_duplicates("champion_name").set_index("champion_name")["champion_id"]
    return _titles_stack(g, types, "Times com mais títulos",
                         "Campeão de cada evento concluído (1º lugar), por tipo de evento",
                         logos=_ids(ids.get(n) for n in g.index))


def intl_titles_region(f, **_):
    """Gera os títulos internacionais (Masters/Champions) por região."""
    ti = stats.titles(f)
    ti = ti[ti["event_type"].isin(stats.INTERNATIONAL_TYPES)]
    if ti.empty:
        return _empty("Nenhum título internacional no filtro atual")
    reg = store["dim_teams"].set_index("team_id")["team_region"]
    g = (ti.assign(team_region=ti["champion_id"].map(reg).fillna("Outros"))
           .groupby(["team_region", "event_type"]).size().unstack(fill_value=0))
    types = [c for c in ("Champions", "Masters") if c in g.columns]
    g["total"] = g[types].sum(axis=1)
    g = g.sort_values("total", ascending=False)
    spec = _titles_stack(g, types, "Títulos internacionais por região", "Masters e Champions, pela região do time campeão")
    spec["labels"] = list(g.index)
    return spec


def team_winrate(f, min_maps=40, team_region=None, limit=20, **_):
    """Gera o ranking de win rate de mapas dos melhores times."""
    df = stats.team_table(f, team_region=team_region, min_maps=int(min_maps))
    if df.empty:
        return _empty("Nenhum time com o mínimo de mapas")
    df = df.sort_values("map_wr", ascending=False).head(int(limit))
    return _bars("Win rate de mapas — melhores times", f"Mínimo de {min_maps} mapas no filtro atual",
                 [_short(n) for n in df["team_name"]],
                 [{"label": "Win rate de mapas", "data": _nums(df["map_wr"]), "color": "main"}],
                 "pct1", horizontal=True, end="value", notes=[f"({int(m)} mapas)" for m in df["maps"]],
                 logos=_ids(df["team_id"]), links=[f"#/time/{i}" for i in df["team_id"]], x={"max": 1, "fmt": "pct0"})


def team_sides(f, min_maps=40, team_region=None, **_):
    """Gera o gráfico de dispersão de rounds vencidos no ataque versus defesa por time."""
    df = stats.team_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["atk_wr", "def_wr"])
    if df.empty:
        return _empty("Nenhum time com o mínimo de mapas")
    df = df.assign(score=df["atk_wr"] + df["def_wr"]).sort_values("score", ascending=False)
    lo = float(min(df["atk_wr"].min(), df["def_wr"].min()) - 0.02)
    hi = float(max(df["atk_wr"].max(), df["def_wr"].max()) + 0.02)
    points = [{"x": _num(r.atk_wr), "y": _num(r.def_wr), "name": r.team_name, "note": f"{int(r.maps)} mapas",
               "link": f"#/time/{int(r.team_id)}", "logo": int(r.team_id)} for r in df.itertuples()]
    return {"kind": "scatter", "title": "Força no ataque × defesa",
            "subtitle": f"% de rounds vencidos em cada lado · times com {min_maps}+ mapas", "fmt": "pct1",
            "datasets": [{"label": "Times", "data": points, "color": "main"},
                         {"label": "ataque = defesa", "data": [{"x": lo, "y": lo}, {"x": hi, "y": hi}], "color": "axis",
                          "role": "ref"}],
            "x": {"title": "Rounds vencidos no ataque", "fmt": "pct0", "min": lo, "max": hi},
            "y": {"title": "Rounds vencidos na defesa", "fmt": "pct0", "min": lo, "max": hi},
            "label_top": 10, "height": 460}


def team_year(f, team_id=None, **_):
    """Gera o win rate de séries e mapas de um time por ano."""
    if team_id is None:
        return _empty("Selecione um time")
    by = pd.DataFrame(stats.team_detail(int(team_id), f).get("by_year", []))
    if by.empty:
        return _empty()
    return _bars("Desempenho por ano", "Win rate de séries (partidas) e de mapas", by["year"].astype(int),
                 [{"label": "Partidas", "data": _nums(by["match_wr"]), "color": "s0"},
                  {"label": "Mapas", "data": _nums(by["map_wr"]), "color": "s1"}],
                 "pct1", end="value", end_fmt="pct0", y={"max": 1, "fmt": "pct0"})


def team_maps(f, team_id=None, **_):
    """Gera os rounds vencidos por mapa e lado de um time."""
    if team_id is None:
        return _empty("Selecione um time")
    by = pd.DataFrame(stats.team_detail(int(team_id), f).get("by_map", []))
    if by.empty:
        return _empty()
    by = by[by["maps"] >= 1].sort_values("maps", ascending=False).head(12)
    return _bars("Rounds vencidos por mapa e lado", "Rótulo: win rate do mapa e número de mapas jogados", by["map_name"],
                 [{"label": "Ataque", "data": _nums(by["atk_wr"]), "color": "atk"},
                  {"label": "Defesa", "data": _nums(by["def_wr"]), "color": "def"}],
                 "pct1", horizontal=True, end="note",
                 notes=[f"mapa {_pct_txt(r.map_wr)} · {int(r.maps)}" for r in by.itertuples()],
                 x={"min": 0, "max": 1, "fmt": "pct0"}, refs=[{"axis": "x", "value": 0.5}])


def team_players(f, team_id=None, min_maps=5, **_):
    """Gera o ranking de rating dos jogadores de um time."""
    if team_id is None:
        return _empty("Selecione um time")
    df = stats.player_table(f, team_id=int(team_id), min_maps=int(min_maps)).dropna(subset=["rating"]).head(12)
    if df.empty:
        return _empty()
    return _bars("Melhores jogadores do time", f"Rating médio por round · mínimo de {min_maps} mapas pelo time",
                 df["player_name"], [{"label": "Rating", "data": _nums(df["rating"]), "color": "main"}], "n2",
                 horizontal=True, end="value", notes=[f"({int(m)} mapas)" for m in df["maps"]],
                 links=[f"#/jogador/{i}" for i in df["player_id"]])


def h2h_maps(f, team_a=None, team_b=None, **_):
    """Gera o placar de vitórias no confronto direto entre dois times."""
    if team_a is None or team_b is None:
        return _empty("Selecione dois times")
    a, b = int(team_a), int(team_b)
    pair = pd.DataFrame(stats.head_to_head(a, b, f)["matches"])
    if pair.empty:
        return _empty("Os times não se enfrentaram no filtro atual")
    dim = store["dim_teams"].set_index("team_id")["team_name"]
    wins = [int((pair["winner_id"] == a).sum()), int((pair["winner_id"] == b).sum())]
    return _bars("Confronto direto", f"{len(pair)} séries no filtro atual", [dim.get(a, a), dim.get(b, b)],
                 [{"label": "Vitórias", "data": wins, "color": ["s0", "s1"]}], "int", horizontal=True,
                 end="value", notes=["vitórias", "vitórias"], logos=[a, b], links=[f"#/time/{a}", f"#/time/{b}"])


def player_top(f, metric="rating", min_maps=20, team_region=None, limit=20, **_):
    """Gera o ranking de jogadores pela métrica escolhida."""
    label, col = stats.PLAYER_METRICS.get(metric, stats.PLAYER_METRICS["rating"])
    df = stats.player_ranking(f, metric, int(min_maps), team_region=team_region, limit=int(limit)).dropna(subset=[col])
    if df.empty:
        return _empty("Nenhum jogador com o mínimo de mapas")
    fmt = "hs" if col in ("hs", "kast") else "n2" if col in ("rating", "kd", "kpr") else "int"
    return _bars(f"Top {len(df)} — {label}", f"Mínimo de {min_maps} mapas no filtro atual · time onde mais jogou",
                 _player_labels(df), [{"label": label, "data": _nums(df[col]), "color": "main"}], fmt,
                 horizontal=True, end="value", logos=_ids(df["team_id"]), links=[f"#/jogador/{i}" for i in df["player_id"]])


def _stacked_players(f, cols, labels, title, subtitle, min_maps, team_region, team_id, limit):
    """Monta barras empilhadas por jogador somando as colunas informadas."""
    df = stats.player_table(f, team_id=team_id, team_region=team_region, min_maps=int(min_maps))
    if df.empty:
        return _empty()
    df = df.assign(_tot=df[cols].sum(axis=1)).sort_values("_tot", ascending=False).head(int(limit))
    df = df[df["_tot"] > 0]
    if df.empty:
        return _empty("Sem dados de performance para o filtro atual")
    return _bars(title, subtitle, _player_labels(df),
                 [{"label": lab, "data": [int(v) for v in df[c]], "color": f"s{i}"} for i, (c, lab) in enumerate(zip(cols, labels))],
                 "int", horizontal=True, stacked=True, end="total", logos=_ids(df["team_id"]),
                 links=[f"#/jogador/{i}" for i in df["player_id"]])


def player_multikills(f, min_maps=0, team_region=None, team_id=None, limit=15, **_):
    """Gera o ranking de multikills (2K a 5K) por jogador."""
    return _stacked_players(f, ["k2", "k3", "k4", "k5"], ["2K (duas)", "3K (triple)", "4K (quadra)", "5K (ace)"],
                            "Multikills", "Rounds com 2+ abates do mesmo jogador", min_maps, team_region,
                            None if team_id is None else int(team_id), limit)


def player_clutches(f, min_maps=0, team_region=None, team_id=None, limit=15, **_):
    """Gera o ranking de clutches vencidos (1v1 a 1v5) por jogador."""
    return _stacked_players(f, ["c1v1", "c1v2", "c1v3", "c1v4", "c1v5"], ["1v1", "1v2", "1v3", "1v4", "1v5"],
                            "Clutches vencidos", "Rounds vencidos como último vivo do time, por situação",
                            min_maps, team_region, None if team_id is None else int(team_id), limit)


def _kde(values, grid, scale):
    """Calcula a densidade KDE gaussiana dos valores sobre a grade, escalada."""
    v = np.asarray(values, dtype=float)
    bw = 1.06 * v.std(ddof=1) * len(v) ** (-1 / 5)
    if not bw > 0:
        return [0.0] * len(grid)
    z = (grid[:, None] - v[None, :]) / bw
    dens = np.exp(-0.5 * z ** 2).sum(axis=1) / (len(v) * bw * np.sqrt(2 * np.pi))
    return dens * scale


def hs_distribution(f, min_maps=20, team_region=None, **_):
    """Gera o histograma com KDE da taxa de headshot dos jogadores."""
    df = stats.player_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["hs"])
    if len(df) < 5:
        return _empty("Poucos jogadores para a distribuição")
    counts, edges = np.histogram(df["hs"], bins=30)
    width = float(edges[1] - edges[0])
    centers = (edges[:-1] + edges[1:]) / 2
    grid = np.linspace(edges[0], edges[-1], 120)
    kde = _kde(df["hs"], grid, len(df) * width)
    med = float(df["hs"].median())
    best = df.nlargest(3, "hs")
    callout = ["Maiores HS%"] + [f"{i}. {r['player_name']} ({_short(r['team_name'], 16) if isinstance(r['team_name'], str) else '—'})"
                                 f" · {r['hs']:.1f}%".replace(".", ",") for i, (_, r) in enumerate(best.iterrows(), 1)]
    return {"kind": "bar", "title": "Distribuição da taxa de headshot",
            "subtitle": f"{len(df)} jogadores com {min_maps}+ mapas · HS% ponderado por kills", "fmt": "int",
            "linear_x": True, "bin_width": width,
            "datasets": [{"label": "Jogadores", "data": [{"x": _num(c, 3), "y": int(n)} for c, n in zip(centers, counts)],
                          "color": "main", "tip": "bin"},
                         {"label": "Densidade (KDE)", "type": "line", "color": "text2", "tip": "none",
                          "data": [{"x": _num(x, 3), "y": _num(y, 3)} for x, y in zip(grid, kde)]}],
            "x": {"title": "HS %", "fmt": "hs0", "min": float(edges[0]), "max": float(edges[-1])},
            "y": {"title": "Jogadores"},
            "refs": [{"axis": "x", "value": med, "label": f"mediana {med:.1f}%".replace(".", ",")}],
            "callout": callout, "height": 360}


def rating_vs_hs(f, min_maps=20, team_region=None, **_):
    """Gera o gráfico de dispersão rating × headshot com reta de tendência e correlação."""
    df = stats.player_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["hs", "rating"])
    if len(df) < 5:
        return _empty("Poucos jogadores para comparar")
    corr = float(np.corrcoef(df["hs"], df["rating"])[0, 1])
    slope, icpt = np.polyfit(df["hs"], df["rating"], 1)
    x0, x1 = float(df["hs"].min()), float(df["hs"].max())
    df = df.sort_values("rating", ascending=False)
    points = [{"x": _num(r.hs, 2), "y": _num(r.rating, 3), "name": r.player_name,
               "note": _short(r.team_name, 20) if isinstance(r.team_name, str) else "",
               "link": f"#/jogador/{int(r.player_id)}"} for r in df.itertuples()]
    return {"kind": "scatter", "title": "Rating × headshot",
            "subtitle": f"Cada ponto é um jogador com {min_maps}+ mapas · correlação de Pearson r = {corr:.2f}".replace(".", ","),
            "fmt": "n2",
            "datasets": [{"label": "Jogadores", "data": points, "color": "main"},
                         {"label": "Tendência linear", "data": [{"x": x0, "y": _num(slope * x0 + icpt)}, {"x": x1, "y": _num(slope * x1 + icpt)}],
                          "color": "text2", "role": "fit"}],
            "x": {"title": "HS %", "fmt": "hs0"}, "y": {"title": "Rating", "fmt": "n2"}, "x_fmt": "hs",
            "label_top": 8, "height": 440}


def player_year(f, player_id=None, **_):
    """Gera a linha de rating por ano de um jogador."""
    if player_id is None:
        return _empty("Selecione um jogador")
    by = pd.DataFrame(stats.player_detail(int(player_id), f).get("by_year", []))
    if by.empty:
        return _empty()
    return {"kind": "line", "title": "Rating por ano", "subtitle": "Média ponderada por rounds jogados",
            "labels": [str(int(y)) for y in by["year"]], "fmt": "n2", "end": "value",
            "notes": [f"{int(m)} mapas" for m in by["maps"]],
            "datasets": [{"label": "Rating", "data": _nums(by["rating"], 3), "color": "main"}],
            "refs": [{"axis": "y", "value": 1.0}]}


def player_agents(f, player_id=None, **_):
    """Gera os agentes mais jogados por um jogador com seu rating."""
    if player_id is None:
        return _empty("Selecione um jogador")
    ag = pd.DataFrame(stats.player_detail(int(player_id), f).get("agents", []))
    if ag.empty:
        return _empty()
    ag = ag.head(10)
    return _bars("Agentes mais jogados", "Mapas por agente · rótulo com o rating no agente",
                 [stats.agent_name(a) for a in ag["agent"]], [{"label": "Mapas", "data": [int(v) for v in ag["maps"]], "color": "main"}],
                 "int", horizontal=True, end="value",
                 notes=[f"(rating {r:.2f})".replace(".", ",") if not pd.isna(r) else "" for r in ag["rating"]])


def map_side_bias(f, min_maps=20, **_):
    """Gera o quanto cada mapa favorece ataque ou defesa em pontos percentuais."""
    df = stats.map_table(f)
    df = df[df["maps"] >= int(min_maps)].sort_values("atk_wr", ascending=False)
    if df.empty:
        return _empty()
    diff = (df["atk_wr"] - 0.5).to_numpy()
    raw = max(0.02, float(np.abs(diff).max())) * 1.9
    step = 0.05 if raw > 0.06 else 0.02 if raw > 0.03 else 0.01
    span = float(np.ceil(raw / step) * step)
    notes = [f"{_pct_txt(max(w, 1 - w), 1)} {'ataque' if d > 0 else 'defesa'} · {int(m)} mapas"
             for d, w, m in zip(diff, df["atk_wr"], df["maps"])]
    return _bars("Lado favorecido em cada mapa", "Quanto o ataque vence acima (+) ou abaixo (−) de 50% dos rounds, em pontos percentuais (pp)", df["map_name"],
                 [{"label": "Favorece o ataque", "data": [_num(d) if d > 0 else None for d in diff], "color": "atk"},
                  {"label": "Favorece a defesa", "data": [_num(d) if d <= 0 else None for d in diff], "color": "def"}],
                 "pp", horizontal=True, stacked=True, end="note", notes=notes,
                 x={"min": -span, "max": span, "step": step, "fmt": "pp0"}, refs=[{"axis": "x", "value": 0, "strong": True}])


def _heat(title, subtitle, pivot, row_label):
    """Monta a especificação JSON de um mapa de calor a partir de uma tabela pivô."""
    pivot = pivot.replace(0, np.nan)
    return {"kind": "heatmap", "title": title, "subtitle": subtitle, "fmt": "pct0", "row_label": row_label,
            "cols": [str(int(c)) for c in pivot.columns], "rows": [str(r) for r in pivot.index],
            "values": [_nums(row) for row in pivot.to_numpy()]}


def map_heatmap(f, **_):
    """Gera o mapa de calor da presença de cada mapa no pool por ano."""
    mc = f.apply(store["map_cube"])
    if mc.empty:
        return _empty()
    p = mc.groupby(["map_name", "year"])["maps"].sum().unstack(fill_value=0)
    share = p / p.sum(axis=0)
    share = share.loc[share.sum(axis=1).sort_values(ascending=False).index]
    return _heat("Map pool ao longo dos anos", "% dos mapas jogados em cada ano (vazio = fora do pool)", share, "Mapa")


def agent_heatmap(f, limit=20, **_):
    """Gera o mapa de calor do pick rate dos agentes por ano."""
    ac = f.apply(store["agent_cube"])
    if ac.empty:
        return _empty()
    p = ac.groupby(["agent", "year"])["picks"].sum().unstack(fill_value=0)
    rate = p / (p.sum(axis=0) / 10)
    rate = rate.loc[rate.sum(axis=1).sort_values(ascending=False).index[: int(limit)]]
    rate.index = [stats.agent_name(a) for a in rate.index]
    return _heat("Meta de agentes por ano", "Pick rate: % das composições que usaram o agente", rate / 2, "Agente")


def agent_pickrate(f, map_name=None, limit=15, **_):
    """Gera o ranking de pick rate dos agentes, opcionalmente por mapa."""
    df = stats.agent_table(f, map_name=map_name).head(int(limit))
    if df.empty:
        return _empty()
    sub = f"Mapa: {map_name}" if map_name else "Todos os mapas"
    return _bars("Agentes mais escolhidos", f"{sub} · % das composições · rótulo com a win rate",
                 [stats.agent_name(a) for a in df["agent"]], [{"label": "Pick rate", "data": _nums(df["pick_rate"] / 2), "color": "main"}],
                 "pct1", horizontal=True, end="value", end_fmt="pct0", notes=[f"(vence {_pct_txt(w)})" for w in df["win_rate"]],
                 x={"fmt": "pct0"})


SPECS = {
    "matches_by_year": matches_by_year, "matches_by_tier": matches_by_tier, "side_by_year": side_by_year, "win_types": win_types,
    "titles_top": titles_top, "intl_titles_region": intl_titles_region,
    "team_winrate": team_winrate, "team_sides": team_sides, "team_year": team_year, "team_maps": team_maps,
    "team_players": team_players, "h2h_maps": h2h_maps,
    "player_top": player_top, "player_multikills": player_multikills, "player_clutches": player_clutches,
    "hs_distribution": hs_distribution, "rating_vs_hs": rating_vs_hs, "player_year": player_year,
    "player_agents": player_agents,
    "map_side_bias": map_side_bias, "map_heatmap": map_heatmap, "agent_heatmap": agent_heatmap,
    "agent_pickrate": agent_pickrate,
}


@lru_cache(maxsize=512)
def build(name: str, f: Filters, params: tuple, version: int) -> dict:
    """Monta (com cache) a especificação JSON do gráfico pedido."""
    kwargs = dict(params)
    kwargs.pop("wide", None)
    return SPECS[name](f, **kwargs)
