"""Fotos dos líderes do banner de Jogadores a partir dos Flickr oficiais da Riot (quando a Liquipedia não tem).

A foto só é aceita quando a legenda cita o jogador e ele aparece sozinho (sem "and", "(L)", "vs" etc.).

Uso:
    python -m scraper.flickr_photos --limit 600
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import time
from urllib.parse import quote

import requests

import config
from api import photos

ACCOUNTS = {"vctamericas": "197181792@N06", "valorantesports": "192820496@N05"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.flickr.com/"}
ITEM = re.compile(r'"description":"((?:[^"\\]|\\.)*)","license":\d+,"sizes":\{"data":\{"sq":\{"data":\{"displayUrl":'
                  r'"\\/\\/live\.staticflickr\.com\\/(\d+)\\/(\d+)_([0-9a-f]+)_s\.jpg"')
GROUP = re.compile(r"\band\b|\(l\)|\(r\)|\(l-r\)|\bvs\.?\b|\bwith\b|\bfans?\b|\bteammates?\b|\bcoach\b", re.I)
CREDIT = re.compile(r"\(Photo by:?\s*([^/)]+?)\s*/\s*Riot Games", re.I)
DELAY = 3.0


def _get(url):
    """Faz GET no Flickr com retentativas e pausa entre requisições."""
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
        except requests.RequestException:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 200:
            time.sleep(DELAY)
            return r
        if r.status_code == 404:
            return None
        time.sleep(60 * (attempt + 1))
    return None


def _norm(s):
    """Normaliza um texto para comparação (minúsculas, só letras e dígitos)."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _solo(desc, name):
    """Indica se a legenda da foto cita só o jogador, sem outras pessoas."""
    head = re.split(r" at | during | poses| competes| walks| celebrates| reacts", html.unescape(desc), maxsplit=1)[0]
    if GROUP.search(head):
        return False
    if not any(_norm(w) == _norm(name) for w in re.findall(r"[\w.\-']+", head.replace('"', " "))):
        return False
    quoted = [q for q in re.findall(r'"([^"]+)"', head) if _norm(q) != _norm(name)]
    return not quoted


def _team_ok(desc, teams):
    """Confere se a legenda cita algum time em que o jogador jogou."""
    text = _norm(html.unescape(desc))
    return any(len(t) >= 2 and t in text for t in teams)


def player_teams():
    """Monta, para cada jogador, os nomes normalizados dos times em que ele jogou."""
    import pandas as pd

    pc = pd.read_csv(config.SERVING_DIR / "player_cube.csv", usecols=["player_id", "team_id"]).drop_duplicates()
    dt = pd.read_csv(config.SERVING_DIR / "dim_teams.csv", usecols=["team_id", "team_name"])
    pc = pc.merge(dt, on="team_id")
    out = {}
    for pid, names in pc.groupby("player_id")["team_name"]:
        keys = set()
        for n in names.dropna():
            keys.add(_norm(n))
            short = re.sub(r"\b(esports|gaming|team|club)\b", "", n, flags=re.I)
            if len(_norm(short)) >= 3:
                keys.add(_norm(short))
        out[int(pid)] = keys
    return out


def search(name, teams=()):
    """Procura nos Flickr oficiais da Riot uma foto solo do jogador."""
    for acct, nsid in ACCOUNTS.items():
        r = _get(f"https://www.flickr.com/search/?text={quote(name)}&user_id={quote(nsid)}&view_all=1")
        if r is None:
            continue
        for desc, server, pid, secret in ITEM.findall(r.text):
            try:
                desc = json.loads('"' + desc + '"')
            except ValueError:
                continue
            if _solo(desc, name) and _team_ok(desc, teams):
                credit = CREDIT.search(html.unescape(desc))
                return {"acct": acct, "pid": pid, "server": server, "secret": secret,
                        "credit": f"{credit.group(1).strip()} / Riot Games" if credit else "Riot Games",
                        "source": f"https://www.flickr.com/photos/{acct}/{pid}/", "desc": html.unescape(desc)[:300]}
    return None


def download(rec, dest):
    """Baixa a foto do Flickr no maior tamanho disponível e salva em JPEG."""
    from PIL import Image

    for size in ("b", "c", "z"):
        r = _get(f"https://live.staticflickr.com/{rec['server']}/{rec['pid']}_{rec['secret']}_{size}.jpg")
        if r is None:
            continue
        try:
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=84, optimize=True, progressive=True)
        return True
    return False


def main(argv=None):
    """Busca e baixa fotos do Flickr para os líderes ainda sem foto."""
    import pandas as pd

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=600, help="quantos líderes sem foto consultar, dos que lideram mais")
    args = ap.parse_args(argv)
    done = {}
    if photos.FLICKR_MAPPING.exists():
        for line in photos.FLICKR_MAPPING.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["player_id"]] = rec
    dp = pd.read_csv(config.SERVING_DIR / "dim_players.csv", usecols=["player_id", "player_name", "current_team_name"])
    names = dp.set_index("player_id")
    leads = photos.leader_counts()
    todo = [p for p in sorted(leads, key=lambda p: -leads[p])
            if not photos.cached_path(p) and p not in done and p in names.index][: args.limit]
    teams = player_teams()
    print(f"{len(todo)} líderes sem foto; buscando nos Flickr oficiais da Riot", flush=True)
    found = 0
    for i, pid in enumerate(todo, 1):
        row = names.loc[pid]
        rec = {"player_id": int(pid), "player_name": row["player_name"]}
        hit = search(str(row["player_name"]), teams.get(int(pid), set()))
        if hit and download(hit, photos.FLICKR_CACHE / f"{int(pid)}.jpg"):
            rec.update(hit)
            found += 1
        done[int(pid)] = rec
        with open(photos.FLICKR_MAPPING, "w", encoding="utf-8") as fh:
            for r in done.values():
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        if i % 10 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} consultados · {found} com foto", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
