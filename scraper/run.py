"""Coleta do cenário competitivo (VLR.gg) para a camada bronze do data lake.

Uso:
    python -m scraper.run                    # VCT (tier 60), 2021 -> 20/10/2026
    python -m scraper.run --tiers 60       # só o Tier 1 (o padrão é T1 + T2 + T3 com prêmio >= US$5 mil)
    python -m scraper.run --rps 1.5 --workers 4
    python -m scraper.run --only discover    # só monta o catálogo de partidas

É retomável: tudo que já está em data/bronze é lido do cache.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from etl import classify, parsers
from scraper.client import VLRClient

BRONZE = config.BRONZE_DIR
CATALOG = BRONZE / "catalog"


def log(msg: str):
    """Imprime uma mensagem com horário."""
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def write_jsonl(path, rows):
    """Grava uma lista de registros em arquivo JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def discover_events(client: VLRClient, tiers, min_prize: dict[int, float]) -> list[dict]:
    """Lista os eventos de cada tier no VLR e filtra por status, prêmio e gênero."""
    events = {}
    for tier in tiers:
        page = 1
        while True:
            html = client.cached(f"/events/?tier={tier}&page={page}",
                                 BRONZE / "listings" / f"tier{tier}_p{page}.html.gz", refresh=True)
            cards = parsers.parse_events_listing(html or "", tier)
            if not cards:
                break
            for c in cards:
                events.setdefault(c["event_id"], c)
            log(f"tier {tier} página {page}: {len(cards)} eventos")
            page += 1
    keep = [e for e in events.values() if e["status"] in ("completed", "ongoing")
            and e["prize_usd"] >= min_prize.get(e["tier"], 0) and classify.is_mens_event(e["title"])]
    log(f"{len(keep)} eventos concluídos/em andamento acima do prêmio mínimo (de {len(events)} listados)")
    return keep


def discover_matches(client: VLRClient, events: list[dict], workers: int) -> list[dict]:
    """Baixa as páginas dos eventos e monta o catálogo de partidas do período."""
    def one(ev):
        """Baixa a página e a lista de partidas de um evento."""
        refresh = ev["status"] == "ongoing"
        eid = ev["event_id"]
        client.cached(f"/event/{eid}/{ev['slug']}", BRONZE / "events" / f"{eid}.html.gz", refresh=refresh)
        html = client.cached(f"/event/matches/{eid}/?series_id=all&group=all",
                             BRONZE / "event_matches" / f"{eid}.html.gz", refresh=refresh)
        return parsers.parse_event_matches(html or "", eid)

    start, end = config.START_DATE.isoformat(), config.END_DATE.isoformat()
    matches = []
    with ThreadPoolExecutor(workers) as pool:
        futs = {pool.submit(one, ev): ev for ev in events}
        for i, fut in enumerate(as_completed(futs), 1):
            for m in fut.result():
                if m["status"] == "completed" and m["date"] and start <= m["date"] <= end:
                    m["year"] = int(m["date"][:4])
                    matches.append(m)
            if i % 25 == 0 or i == len(futs):
                log(f"eventos processados: {i}/{len(futs)} — partidas no recorte: {len(matches)}")
    matches.sort(key=lambda m: (m["date"], m["match_id"]))
    return matches


def fetch_matches(client: VLRClient, matches: list[dict], workers: int):
    """Baixa em paralelo as páginas de partida e performance ainda ausentes."""
    def paths(m):
        """Retorna os caminhos na bronze das páginas de uma partida."""
        part = f"year={m['year']}"
        return (BRONZE / "matches" / part / f"{m['match_id']}.html.gz",
                BRONZE / "performance" / part / f"{m['match_id']}.html.gz")

    todo = sorted((m for m in matches if not all(p.exists() for p in paths(m))),
                  key=lambda m: (m["date"], m["match_id"]), reverse=True)
    log(f"{len(matches)} partidas no catálogo; {len(todo)} ainda não baixadas")
    failures = []

    def one(m):
        """Baixa as páginas de visão geral e performance de uma partida."""
        ov, perf = paths(m)
        client.cached(m["href"], ov)
        client.cached(f"/{m['match_id']}/?game=all&tab=performance", perf)

    t0 = time.monotonic()
    with ThreadPoolExecutor(workers) as pool:
        futs = {pool.submit(one, m): m for m in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
            except Exception as exc:
                failures.append({**futs[fut], "error": str(exc)})
            if i % 50 == 0 or i == len(futs):
                rate = i / max(1e-9, time.monotonic() - t0)
                eta = (len(futs) - i) / max(rate, 1e-9) / 60
                log(f"partidas: {i}/{len(futs)} | {rate:.2f}/s | ETA {eta:.0f} min | "
                    f"{client.bytes_downloaded / 2**20:.0f} MB baixados | falhas {len(failures)}")
    write_jsonl(CATALOG / "failures.jsonl", failures)


def main(argv=None):
    """Executa a coleta do VLR (descoberta e download) conforme os argumentos."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiers", type=int, nargs="+", default=list(config.DEFAULT_TIERS))
    ap.add_argument("--min-prize", nargs="*", default=[f"{k}={v}" for k, v in config.DEFAULT_MIN_PRIZE.items()],
                    help="prêmio mínimo (US$) por tier do VLR, ex.: 62=10000")
    ap.add_argument("--rps", type=float, default=2.0, help="requisições por segundo (total)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", choices=["discover", "matches"], help="executa só uma etapa")
    args = ap.parse_args(argv)

    client = VLRClient(rps=args.rps)
    if args.only != "matches":
        min_prize = {int(k): float(v) for k, v in (x.split("=") for x in args.min_prize)}
        events = discover_events(client, args.tiers, min_prize)
        write_jsonl(CATALOG / "events.jsonl", events)
        matches = discover_matches(client, events, args.workers)
        write_jsonl(CATALOG / "matches.jsonl", matches)
        log(f"catálogo: {len(matches)} partidas entre {config.START_DATE} e {config.END_DATE}")
    else:
        with open(CATALOG / "matches.jsonl", encoding="utf-8") as f:
            matches = [json.loads(line) for line in f]
    if args.only != "discover":
        fetch_matches(client, matches, args.workers)
    log(f"fim — {client.requests_made} requisições, {client.bytes_downloaded / 2**20:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
