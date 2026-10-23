"""Jogadores que aparecem como top 1 no banner da página Jogadores, em todas as combinações de filtros.

Uso:
    python -m scraper.leaders    # grava bronze/catalog/photo_leaders.json
"""
from __future__ import annotations

import itertools
import json
import time

import pandas as pd

import config
from api import stats
from api.store import Filters, store

OUT = config.BRONZE_DIR / "catalog" / "photo_leaders.json"
TEAM_REGIONS = (None, "Americas", "EMEA", "Pacific", "China", "Outros")
COUNT_METRICS = {"kills", "clutches", "aces", "k4", "k3", "k2", "assists", "fk"}
CLUTCH = ["c1v1", "c1v2", "c1v3", "c1v4", "c1v5"]
MULTI = ["k2", "k3", "k4", "k5"]


def auto_min(f: Filters) -> int:
    """Define o mínimo de mapas para métricas de taxa conforme o filtro."""
    return 1 if f.event_id else 5 if f.event_type else 20 if f.year else 40


def _top(df: pd.DataFrame, col: str, positive: bool) -> int | None:
    """Retorna o ID do jogador com maior valor na coluna informada."""
    df = df.dropna(subset=[col])
    if positive:
        df = df[df[col] > 0]
    return None if df.empty else int(df.sort_values(col, ascending=False).iloc[0]["player_id"])


def combo_leaders(f: Filters) -> set[int]:
    """Retorna os jogadores líderes de alguma métrica no filtro, por região."""
    rate_min = auto_min(f)
    full = stats.player_table(f, min_maps=1)
    if full.empty:
        return set()
    full = full.assign(_c=full[CLUTCH].sum(axis=1), _m=full[MULTI].sum(axis=1))
    out = set()
    for region in TEAM_REGIONS:
        counts = full if region is None else full[full["team_region"] == region]
        rates = counts[counts["maps"] >= rate_min]
        for metric, (_label, col) in stats.PLAYER_METRICS.items():
            df = counts if metric in COUNT_METRICS else rates
            out.add(_top(df, col, col not in ("rating", "hs")))
        out.add(_top(counts, "_c", True))
        out.add(_top(counts, "_m", True))
        out.add(_top(rates, "hs", False))
        out.add(_top(rates, "rating", False))
    out.discard(None)
    return out


def main():
    """Conta os líderes em todas as combinações de filtros e grava o JSON."""
    store.load()
    pc = store["player_cube"]
    tiers = [None, *sorted(int(t) for t in pc["tier"].unique())]
    years = [None, *sorted(int(y) for y in pc["year"].unique())]
    regions = [None, *sorted(pc["region"].dropna().unique())]
    types = [None, *sorted(pc["event_type"].dropna().unique())]
    combos = [Filters(year=y, tier=t, region=r, event_type=e) for t, y, r, e in itertools.product(tiers, years, regions, types)]
    combos += [Filters(event_id=int(e)) for e in sorted(pc["event_id"].unique())]
    leaders: dict[int, int] = {}
    t0 = time.time()
    for i, f in enumerate(combos, 1):
        for pid in combo_leaders(f):
            leaders[pid] = leaders.get(pid, 0) + 1
        if i % 250 == 0 or i == len(combos):
            print(f"{i}/{len(combos)} combinações · {len(leaders)} líderes · {time.time() - t0:.0f}s", flush=True)
    OUT.write_text(json.dumps(dict(sorted(leaders.items(), key=lambda kv: -kv[1]))), encoding="utf-8")
    print(f"{len(leaders)} jogadores gravados em {OUT}", flush=True)


if __name__ == "__main__":
    main()
