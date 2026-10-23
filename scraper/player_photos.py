"""Fotos dos jogadores do Tier 1 a partir da Liquipedia (foto da ficha de cada jogador).

Uso:
    python -m scraper.player_photos                  # mapeia e baixa (jogadores do VCT com 10+ mapas)
    python -m scraper.player_photos --retry          # consulta de novo quem ficou sem foto
    python -m scraper.player_photos --only download  # só baixa as fotos já mapeadas
    python -m scraper.player_photos --deep           # busca mais a fundo quem ainda está sem foto
    python -m scraper.player_photos --leaders        # líderes do banner de Jogadores
"""
from __future__ import annotations

import argparse
import json
import re
import time

import pandas as pd
import requests

import config
from api import photos

API = "https://liquipedia.net/valorant/api.php"
HEADERS = {"User-Agent": config.LIQUIPEDIA_USER_AGENT, "Accept-Encoding": "gzip"}
OUT = photos.MAPPING
BATCH = 20
DELAY = 10.0
VERSION = 2

_FIELD = re.compile(r"^\s*\|\s*(image|country\d?|team)\s*=\s*([^\n|}]*)", re.M | re.I)
_ALIASES = {"united states": "usa", "south korea": "korea", "türkiye": "turkey", "czechia": "czech republic",
            "united kingdom": "uk"}
_WILDCARD = {"", "international", "europe", "none", "nan"}
_ID = re.compile(r"^\s*\|\s*id\s*=\s*([^\n|}]*)", re.M | re.I)
_LINK = re.compile(r"\[\[([^\]|#]+)")
_SKIP_NS = ("file:", "category:", "template:", "image:", "liquipedia:")


class RateLimited(Exception):
    """Erro lançado quando a Liquipedia limita as requisições."""
    pass


def _get(params):
    """Chama a API da Liquipedia com retentativas e pausa entre requisições."""
    for attempt in range(4):
        try:
            r = requests.get(API, params={**params, "format": "json"}, headers=HEADERS, timeout=60)
        except requests.RequestException:
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 429:
            raise RateLimited()
        if r.status_code == 200:
            data = r.json()
            time.sleep(DELAY)
            if "error" in data:
                raise RateLimited() if data["error"].get("code") == "ratelimited" else RuntimeError(data["error"])
            return data
        time.sleep(30 * (attempt + 1))
    raise RateLimited()


def _query_all(params):
    """Executa uma consulta na API seguindo a paginação e junta os resultados."""
    pages, cont, merged = {}, {}, {"normalized": [], "redirects": []}
    while True:
        data = _get({**params, **cont})
        q = data.get("query", {})
        merged["normalized"] += q.get("normalized", [])
        merged["redirects"] += q.get("redirects", [])
        for pid, page in q.get("pages", {}).items():
            cur = pages.setdefault(pid, page)
            if page.get("revisions"):
                cur["revisions"] = page["revisions"]
            if page.get("imageinfo"):
                cur["imageinfo"] = page["imageinfo"]
        if "continue" not in data:
            break
        cont = data["continue"]
    merged["pages"] = pages
    return merged


def _norm(s):
    """Normaliza o nome de um país aplicando apelidos conhecidos."""
    s = (s or "").strip().lower()
    return _ALIASES.get(s, s)


def _matches(ours_country, ours_team, fields):
    """Confere se país ou time da ficha da Liquipedia batem com os nossos dados."""
    countries = {_norm(v) for k, v in fields.items() if k.startswith("country") and v.strip()}
    if _norm(ours_country) in _WILDCARD or not countries:
        return True
    if _norm(ours_country) in countries:
        return True
    team = (fields.get("team") or "").strip().lower()
    ours_team = ours_team if isinstance(ours_team, str) else ""
    return bool(ours_team) and bool(team) and (team in ours_team.lower() or ours_team.lower() in team)


def _player_cube():
    """Lê do serving as colunas do cubo de jogadores usadas aqui."""
    return pd.read_csv(config.SERVING_DIR / "player_cube.csv", usecols=["player_id", "tier", "event_type", "maps"])


def _targets(pc):
    """Retorna os jogadores elegíveis a foto somados aos líderes."""
    return photos.eligible_players(pc) | photos.leader_players()


def _tier1_players():
    """Lista os jogadores alvo com nome, país e time, ordenados por prioridade."""
    pc = _player_cube()
    eligible = _targets(pc)
    maps = pc[pc["tier"] == 1].groupby("player_id")["maps"].sum()
    dp = pd.read_csv(config.SERVING_DIR / "dim_players.csv",
                     usecols=["player_id", "player_name", "country", "current_team_name"])
    dp = dp[dp["player_id"].isin(eligible)].dropna(subset=["player_name"])
    dp = dp[~dp["player_name"].str.contains(r"[#<>\[\]|{}]", regex=True)]
    dp["maps"] = dp["player_id"].map(maps)
    dp["leads"] = dp["player_id"].map(photos.leader_counts()).fillna(0)
    return dp.sort_values(["leads", "maps"], ascending=False)


def _save(done):
    """Grava o mapeamento de fotos em JSONL."""
    with open(OUT, "w", encoding="utf-8") as fh:
        for rec in done.values():
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def map_photos(retry):
    """Mapeia na Liquipedia a imagem da ficha de cada jogador alvo."""
    players = _tier1_players()
    done = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["player_id"]] = rec
    if retry:
        settled = [p for p, r in done.items() if r.get("url") or r.get("v") == VERSION]
        todo = players[~players["player_id"].isin(settled)]
    else:
        todo = players[~players["player_id"].isin(done)]
    print(f"{len(players)} jogadores do VCT; {len(todo)} para consultar", flush=True)

    rows = list(todo.itertuples(index=False))
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        titles = {}
        for r in chunk:
            titles.setdefault(r.player_name[:1].upper() + r.player_name[1:], r)
        q = _query_all({"action": "query", "titles": "|".join(titles), "redirects": 1,
                        "prop": "revisions", "rvprop": "content", "rvslots": "main"})
        alias = {n["from"]: n["to"] for n in q["normalized"] + q["redirects"]}
        pages = {p["title"]: p for p in q["pages"].values()}
        files = {}
        for title, r in titles.items():
            final = title
            for _ in range(3):
                final = alias.get(final, final)
            page = pages.get(final)
            text = ""
            if page and page.get("revisions"):
                text = page["revisions"][0].get("slots", {}).get("main", {}).get("*", "")
            fields = {m.group(1).lower(): m.group(2) for m in _FIELD.finditer(text)}
            rec = {"player_id": int(r.player_id), "player_name": r.player_name, "v": VERSION,
                   "lp_title": final if page and "missing" not in page else None, "file": None, "url": None}
            image = (fields.get("image") or "").strip()
            if "{{Infobox player" in text and image and _matches(r.country, r.current_team_name, fields):
                rec["file"] = image
                files["File:" + image] = rec
            done[rec["player_id"]] = rec
        if files:
            info = _query_all({"action": "query", "titles": "|".join(files), "prop": "imageinfo",
                               "iiprop": "url|size", "iiurlwidth": 1600})
            ialias = {n["from"]: n["to"] for n in info["normalized"]}
            by_title = {p.get("title"): p for p in info["pages"].values()}
            for fname, rec in files.items():
                ii = (by_title.get(ialias.get(fname, fname)) or {}).get("imageinfo") or []
                if ii:
                    rec["url"] = ii[0].get("thumburl") or ii[0].get("url")
        _save(done)
        found = sum(1 for v in done.values() if v.get("url"))
        print(f"{min(start + BATCH, len(rows))}/{len(rows)} consultados · {found} com foto", flush=True)


def _key(s):
    """Normaliza um nome removendo espaços e pontuação para comparação."""
    return re.sub(r"[\s_.\-]", "", str(s or "")).lower()


def _player_teams():
    """Mapeia cada jogador para os nomes dos times em que já jogou."""
    pc = pd.read_csv(config.SERVING_DIR / "player_cube.csv", usecols=["player_id", "team_id"]).drop_duplicates()
    dt = pd.read_csv(config.SERVING_DIR / "dim_teams.csv", usecols=["team_id", "team_name"])
    pc = pc.merge(dt, on="team_id")
    return {int(p): {n.lower() for n in g["team_name"] if isinstance(n, str) and len(n) >= 3}
            for p, g in pc.groupby("player_id")}


def _text(page):
    """Retorna o wikitexto da última revisão da página."""
    if not page or not page.get("revisions"):
        return ""
    return page["revisions"][0].get("slots", {}).get("main", {}).get("*", "")


def _accept(r, text, teams):
    """Retorna a imagem da ficha se a página corresponder ao jogador."""
    if "{{Infobox player" not in text:
        return None
    fields = {m.group(1).lower(): m.group(2) for m in _FIELD.finditer(text)}
    image = (fields.get("image") or "").strip()
    if not image:
        return None
    pid = _ID.search(text)
    if pid and _key(pid.group(1)) != _key(r.player_name):
        return None
    if _matches(r.country, r.current_team_name, fields):
        return image
    low = text.lower()
    return image if any(t in low for t in teams) else None


def _links(text):
    """Lista até 10 links internos de uma página que não é ficha de jogador."""
    if "{{Infobox player" in text:
        return []
    out = []
    for t in _LINK.findall(text):
        t = t.strip()
        if t and not t.lower().startswith(_SKIP_NS) and t not in out:
            out.append(t)
    return out[:10]


def _pages_by_title(q):
    """Cria uma função que resolve o título (com redirects) para a página."""
    alias = {n["from"]: n["to"] for n in q.get("normalized", []) + q.get("redirects", [])}
    pages = {p["title"]: p for p in q.get("pages", {}).values()}

    def get(title):
        """Resolve o título seguindo redirects e retorna título e página."""
        for _ in range(3):
            title = alias.get(title, title)
        return title, pages.get(title)
    return get


def deep_map():
    """Busca mais a fundo, por links e pesquisa, fotos dos jogadores sem foto."""
    players = _tier1_players()
    done = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["player_id"]] = rec
    teams = _player_teams()
    rows = [r for r in players.itertuples(index=False) if not (done.get(int(r.player_id)) or {}).get("url")]
    print(f"{len(rows)} jogadores do VCT ainda sem foto", flush=True)
    found, follow = {}, {}

    known = [r for r in rows if (done.get(int(r.player_id)) or {}).get("lp_title")]
    for start in range(0, len(known), BATCH):
        chunk = known[start:start + BATCH]
        q = _query_all({"action": "query", "titles": "|".join(done[int(r.player_id)]["lp_title"] for r in chunk),
                        "redirects": 1, "prop": "revisions", "rvprop": "content", "rvslots": "main"})
        get = _pages_by_title(q)
        for r in chunk:
            title, page = get(done[int(r.player_id)]["lp_title"])
            text = _text(page)
            img = _accept(r, text, teams.get(int(r.player_id), set()))
            if img:
                found[int(r.player_id)] = (title, img)
            elif _links(text):
                follow[int(r.player_id)] = _links(text)
        print(f"  páginas conhecidas: {min(start + BATCH, len(known))}/{len(known)} · {len(found)} aceitas", flush=True)

    rest = [r for r in rows if int(r.player_id) not in found]
    for i, r in enumerate(rest, 1):
        pid = int(r.player_id)
        own = teams.get(pid, set())
        if pid in follow:
            q = _query_all({"action": "query", "titles": "|".join(follow[pid]), "redirects": 1,
                            "prop": "revisions", "rvprop": "content", "rvslots": "main"})
            pages = list(q["pages"].values())
        else:
            data = _get({"action": "query", "generator": "search", "gsrsearch": r.player_name, "gsrnamespace": 0,
                         "gsrlimit": 6, "prop": "revisions", "rvprop": "content", "rvslots": "main"})
            pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for page in pages:
            img = _accept(r, _text(page), own)
            if img:
                found[pid] = (page["title"], img)
                break
        if i % 10 == 0 or i == len(rest):
            print(f"  busca: {i}/{len(rest)} · {len(found)} aceitas no total", flush=True)

    files = {}
    for pid, (title, img) in found.items():
        rec = done.setdefault(pid, {"player_id": pid})
        rec.update(lp_title=title, file=img, url=None, v=VERSION, deep=True)
        files.setdefault("File:" + img, []).append(rec)
    names = list(files)
    for start in range(0, len(names), BATCH):
        chunk = names[start:start + BATCH]
        info = _query_all({"action": "query", "titles": "|".join(chunk), "prop": "imageinfo",
                           "iiprop": "url|size", "iiurlwidth": 1600})
        ialias = {n["from"]: n["to"] for n in info["normalized"]}
        by_title = {p.get("title"): p for p in info["pages"].values()}
        for fname in chunk:
            ii = (by_title.get(ialias.get(fname, fname)) or {}).get("imageinfo") or []
            for rec in files[fname]:
                rec["url"] = (ii[0].get("thumburl") or ii[0].get("url")) if ii else None
    _save(done)
    print(f"{sum(1 for recs in files.values() for rec in recs if rec.get('url'))} fotos novas mapeadas", flush=True)


def download_photos(delay):
    """Baixa as fotos mapeadas ainda não salvas, por prioridade."""
    index = photos.load_index()
    pc = _player_cube()
    eligible = _targets(pc)
    t1 = pc[pc["tier"] == 1].groupby("player_id")["maps"].sum()
    leads = photos.leader_counts()
    todo = sorted((pid for pid in index if pid in eligible and not photos.cached_path(pid)),
                  key=lambda p: (-leads.get(p, 0), -t1.get(p, 0)))
    print(f"{len(index)} fotos mapeadas; {len(todo)} para baixar", flush=True)
    for i, pid in enumerate(todo, 1):
        status = photos.download(pid)
        if status == 429:
            raise RateLimited()
        time.sleep(delay)
        if i % 50 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} baixadas", flush=True)


def main(argv=None):
    """Executa o mapeamento e o download das fotos conforme os argumentos."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--only", choices=["map", "download"])
    ap.add_argument("--download-delay", type=float, default=15.0)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--leaders", action="store_true", help="líderes do banner de Jogadores")
    args = ap.parse_args(argv)
    try:
        if args.leaders:
            map_photos(retry=True)
            download_photos(args.download_delay)
            return 0
        if args.deep:
            deep_map()
            download_photos(args.download_delay)
            return 0
        if args.only != "map":
            download_photos(args.download_delay)
        if args.only != "download":
            map_photos(args.retry)
        if args.only != "map":
            download_photos(args.download_delay)
    except RateLimited:
        print("a Liquipedia limitou as requisições (429); rode de novo mais tarde para continuar", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
