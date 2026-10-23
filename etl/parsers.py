from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_INT = re.compile(r"-?\d+")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _soup(html: str) -> BeautifulSoup:
    """Cria o objeto BeautifulSoup do HTML."""
    return BeautifulSoup(html, "html.parser")


def _text(node) -> str:
    """Retorna o texto do nó com espaços normalizados."""
    return _WS.sub(" ", node.get_text(" ", strip=True)).strip() if node else ""


def _own_text(node) -> str:
    """Retorna só o texto direto do nó, sem o dos filhos."""
    if node is None:
        return ""
    return _WS.sub(" ", " ".join(node.find_all(string=True, recursive=False))).strip()


def _int(s, default=None):
    """Extrai o primeiro inteiro do texto."""
    m = _INT.search(s or "")
    return int(m.group()) if m else default


def _num(s, default=None):
    """Extrai o primeiro número decimal do texto."""
    m = _NUM.search((s or "").replace(",", ""))
    return float(m.group()) if m else default


def _usd(text: str):
    """Extrai um valor em dólares do texto, se houver."""
    text = text or ""
    if "~" in text:
        text = text.split("~", 1)[1]
    elif "$" not in text:
        return None
    return _num(text)


def _img(node):
    """Retorna a URL absoluta da imagem, ignorando o placeholder do VLR."""
    src = (node.get("src") or "") if node is not None else ""
    if not src or "/img/vlr/tmp/vlr.png" in src:
        return None
    return "https:" + src if src.startswith("//") else ("https://www.vlr.gg" + src if src.startswith("/") else src)


def _id_from_href(href: str | None, kind: str):
    """Extrai o ID numérico de um link do tipo /kind/ID."""
    m = re.search(rf"/{kind}/(\d+)", href or "")
    return int(m.group(1)) if m else None


def parse_events_listing(html: str, tier: int) -> list[dict]:
    """Extrai os eventos da página de listagem do VLR."""
    out = []
    for card in _soup(html).select("a.event-item"):
        m = re.match(r"/event/(\d+)/([^/?]+)", card.get("href", ""))
        if not m:
            continue
        status = card.select_one(".event-item-desc-item-status")
        flag = card.select_one(".mod-location i.flag")
        flag_cls = [c for c in (flag.get("class", []) if flag else []) if c.startswith("mod-")]
        out.append({
            "event_id": int(m.group(1)),
            "slug": m.group(2),
            "title": _text(card.select_one(".event-item-title")),
            "status": _text(status).lower(),
            "tier": tier,
            "prize_usd": _usd(_text(card.select_one(".event-item-desc-item.mod-prize"))) or 0.0,
            "flag": flag_cls[0][4:] if flag_cls else None,
        })
    return out


_CURRENCY = re.compile(r"\b([A-Z]{3})\b")


def _local_rate(total_text: str):
    """Obtém a moeda local e a taxa de conversão para dólar do texto do prêmio."""
    if "~" not in (total_text or ""):
        return None, None
    local, usd = total_text.split("~", 1)
    code = _CURRENCY.search(local)
    amount, usd_amount = _num(local), _num(usd)
    if not code or not amount or not usd_amount:
        return None, None
    return code.group(1), usd_amount / amount


def _placement_usd(text: str, code: str | None, rate: float | None):
    """Converte o prêmio de uma colocação para dólares."""
    usd = _usd(text)
    if usd is not None or not code or not rate:
        return usd
    if _num(text) and "$" not in (text or ""):
        return round(_num(text) * rate, 2)
    return None


def parse_event_page(html: str, event_id: int) -> dict:
    """Extrai dados do evento e a tabela de colocações da página do evento."""
    s = _soup(html)
    meta, flag = {}, None
    for block in s.select(".event-header-main-meta > div"):
        label = _text(block.select_one(".label")).lower()
        meta[label] = _text(block.select_one(".value"))
        icon = block.select_one(".value i.flag")
        if label == "location" and icon is not None:
            mods = [c for c in icon.get("class", []) if c.startswith("mod-")]
            flag = mods[0][4:] if mods else None
    circuit = _text(s.select_one(".event-header-main-bc > a"))
    code, rate = _local_rate(meta.get("prize", ""))
    placements = []
    for row in s.select(".wf-ptable--standings .row"):
        cells = row.select(".cell")
        team = row.select_one('a[href^="/team/"]')
        if len(cells) < 3 or not team:
            continue
        name_div = team.select_one(".text-of")
        team_name = _own_text(name_div) if name_div else _text(team)
        placements.append({
            "event_id": event_id,
            "place_text": _text(cells[0]).replace(" ", ""),
            "place": _int(_text(cells[0])),
            "prize_usd": _placement_usd(_text(cells[1]), code, rate),
            "team_id": _id_from_href(team["href"], "team"),
            "team_name": team_name or _text(name_div),
            "team_logo": _img(team.find("img")),
            "team_country": _text(name_div.select_one(".ge-text-light")) if name_div else None,
        })
    return {
        "event_id": event_id,
        "name": _text(s.select_one(".event-header-main-title")),
        "circuit": circuit,
        "dates_text": meta.get("dates", ""),
        "prize_usd": _usd(meta.get("prize", "")),
        "location": meta.get("location", ""),
        "flag": flag,
        "logo_url": _img(s.select_one(".event-header-thumb img")),
        "placements": placements,
    }


_DATE_LABEL = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def parse_event_matches(html: str, event_id: int) -> list[dict]:
    """Extrai a lista de partidas da página de partidas do evento."""
    s = _soup(html)
    out = []
    for label in s.select(".wf-label.mod-large"):
        m = _DATE_LABEL.search(_text(label))
        day = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat() if m else None
        card = label.find_next_sibling(class_="wf-card")
        if not card:
            continue
        for a in card.select("a.match-item"):
            mm = re.match(r"/(\d+)/", a.get("href", ""))
            if not mm:
                continue
            series = a.select_one(".match-item-event-series")
            stage = a.select_one(".match-item-event")
            stage_text = _text(stage)
            series_text = _text(series)
            if series_text and stage_text.startswith(series_text):
                stage_text = stage_text[len(series_text):].strip()
            out.append({
                "match_id": int(mm.group(1)),
                "event_id": event_id,
                "href": a["href"],
                "date": day,
                "status": _text(a.select_one(".ml-status")).lower(),
                "series": series_text,
                "stage": stage_text,
            })
    return out


_HEADER_RE = re.compile(r'<div class="[^"]*\bmatch-header"')
_NOISE_RE = re.compile(r"<script\b.*?</script>|<svg\b.*?</svg>|<style\b.*?</style>", re.S)


def _trim_match_html(html: str) -> str:
    """Recorta o HTML da partida na área útil e remove scripts, svgs e estilos."""
    m = _HEADER_RE.search(html)
    start = m.start() if m else 0
    end = html.find('<div class="match-h2h', start)
    if end < 0:
        end = html.find('id="comments"', start)
    body = html[start:end if end > 0 else len(html)]
    return _NOISE_RE.sub("", body)


def _sides(cell) -> tuple:
    """Retorna os valores total, ataque e defesa de uma célula de estatística."""
    if cell is None:
        return (None, None, None)
    vals = []
    for cls in ("mod-both", "mod-t", "mod-ct"):
        sp = cell.select_one(f"span.side.{cls}")
        vals.append(_num(_text(sp)) if sp else None)
    return tuple(vals)


def _team_side_scores(team_div) -> dict:
    """Soma os rounds do time por lado e identifica o lado inicial."""
    out = {"atk": 0, "def": 0, "ot": 0, "start": None}
    for sp in team_div.select("span.mod-t, span.mod-ct, span.mod-ot"):
        cls = sp.get("class", [])
        side = "atk" if "mod-t" in cls else "def" if "mod-ct" in cls else "ot"
        if out["start"] is None and side != "ot":
            out["start"] = side
        out[side] += _int(_text(sp), 0)
    return out


def _duration_sec(text: str):
    """Converte uma duração no formato h:mm:ss ou mm:ss para segundos."""
    parts = [int(p) for p in re.findall(r"\d+", text or "")]
    if not parts:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_match_page(html: str, match_id: int) -> dict:
    """Extrai partida, mapas, rounds e estatísticas dos jogadores da página."""
    s = _soup(_trim_match_html(html))
    hdr = s.select_one(".match-header")
    ev = hdr.select_one(".match-header-event") if hdr else None
    links = hdr.select(".match-header-link") if hdr else []
    teams = []
    for a in links[:2]:
        teams.append({
            "id": _id_from_href(a.get("href"), "team"),
            "name": _text(a.select_one(".wf-title-med")),
        })
    while len(teams) < 2:
        teams.append({"id": None, "name": ""})
    score_spans = [sp for sp in (hdr.select(".match-header-vs-score span") if hdr else [])
                   if "match-header-vs-score-colon" not in sp.get("class", [])]
    scores = [_int(_text(sp)) for sp in score_spans[:2]] + [None, None]
    notes = [_text(n) for n in hdr.select(".match-header-vs-note")] if hdr else []
    bo = next((_int(n) for n in notes if n.lower().startswith("bo")), None)
    ts = hdr.select_one(".moment-tz-convert[data-utc-ts]") if hdr else None
    patch = None
    if hdr:
        pm = re.search(r"Patch\s+([\d.]+)", _text(hdr.select_one(".match-header-date")))
        patch = pm.group(1) if pm else None
    t1s, t2s = scores[0], scores[1]
    winner = None
    if t1s is not None and t2s is not None and t1s != t2s:
        winner = teams[0]["id"] if t1s > t2s else teams[1]["id"]

    match = {
        "match_id": match_id,
        "event_id": _id_from_href(ev.get("href") if ev else None, "event"),
        "series_text": _text(hdr.select_one(".match-header-event-series")) if hdr else "",
        "utc_ts": ts.get("data-utc-ts") if ts else None,
        "patch": patch,
        "best_of": bo,
        "team1_id": teams[0]["id"], "team1_name": teams[0]["name"],
        "team2_id": teams[1]["id"], "team2_name": teams[1]["name"],
        "team1_score": t1s, "team2_score": t2s,
        "winner_id": winner,
        "veto": _text(hdr.select_one(".match-header-note")) if hdr else "",
    }

    nav = {a.get("data-game-id"): _text(a) for a in s.select(".vm-stats-gamesnav-item")}
    maps, rounds, players = [], [], []
    order = 0
    for g in s.select(".vm-stats-game"):
        gid = g.get("data-game-id")
        header = g.select_one(".vm-stats-game-header")
        if not gid or gid == "all" or header is None:
            continue
        order += 1
        tdivs = header.select(".team")
        if len(tdivs) < 2:
            continue
        sc1 = _int(_text(tdivs[0].select_one(".score")))
        sc2 = _int(_text(tdivs[1].select_one(".score")))
        s1, s2 = _team_side_scores(tdivs[0]), _team_side_scores(tdivs[1])
        map_name_div = header.select_one(".map-name")
        picked = header.select_one(".map-name .picked")
        picked_by = None
        if picked is not None:
            pcls = picked.get("class", [])
            picked_by = teams[0]["id"] if "mod-1" in pcls else teams[1]["id"] if "mod-2" in pcls else None
        map_name = _text(map_name_div.find("span") or map_name_div).replace("PICK", "").strip()
        if not map_name:
            map_name = re.sub(r"^\d+\s*", "", nav.get(gid, "")).strip()
        gwin = None
        if sc1 is not None and sc2 is not None and sc1 != sc2:
            gwin = teams[0]["id"] if sc1 > sc2 else teams[1]["id"]
        maps.append({
            "game_id": int(gid), "match_id": match_id, "map_order": order,
            "map_name": map_name, "picked_by": picked_by,
            "duration_sec": _duration_sec(_text(header.select_one(".map-duration"))),
            "team1_id": teams[0]["id"], "team2_id": teams[1]["id"],
            "team1_score": sc1, "team2_score": sc2,
            "team1_atk": s1["atk"], "team1_def": s1["def"], "team1_ot": s1["ot"],
            "team2_atk": s2["atk"], "team2_def": s2["def"], "team2_ot": s2["ot"],
            "team1_start": s1["start"],
            "winner_id": gwin,
        })

        for col in g.select(".vlr-rounds-row-col"):
            num = col.select_one(".rnd-num")
            if num is None:
                continue
            sqs = col.select(".rnd-sq")
            win_idx = next((i for i, q in enumerate(sqs[:2]) if "mod-win" in q.get("class", [])), None)
            if win_idx is None:
                continue
            sq = sqs[win_idx]
            img = sq.find("img")
            wtype = None
            if img is not None:
                wm = re.search(r"/round/(\w+)\.", img.get("src", ""))
                wtype = wm.group(1) if wm else None
            rounds.append({
                "game_id": int(gid), "match_id": match_id,
                "round_no": _int(_text(num)),
                "winner_id": teams[win_idx]["id"],
                "winner_side": "atk" if "mod-t" in sq.get("class", []) else "def",
                "win_type": wtype,
                "score_after": col.get("title"),
            })

        for t_idx, table in enumerate(g.select(".ovw-table")[:2]):
            team = teams[t_idx]
            for row in table.select(".ovw-row"):
                if "mod-head" in row.get("class", []):
                    continue
                pa = row.select_one('a[href^="/player/"]')
                if pa is None:
                    continue
                cells = {c.get("data-col"): c for c in row.select("[data-col]")}
                flag = row.select_one(".mod-player i.flag")
                agent_img = row.select_one(".mod-agents img")
                rec = {
                    "game_id": int(gid), "match_id": match_id,
                    "team_id": team["id"], "team_name": team["name"],
                    "player_id": _id_from_href(pa["href"], "player"),
                    "player_name": _text(pa.select_one(".ovw-player-name")),
                    "team_tag": _text(pa.select_one(".ovw-player-tag")),
                    "country": flag.get("title") if flag else None,
                    "agent": (agent_img.get("title") or agent_img.get("alt") or "").lower() if agent_img else None,
                }
                for col, key in (("rating2", "rating"), ("acs", "acs"), ("kills", "k"), ("deaths", "d"),
                                 ("assists", "a"), ("kast", "kast"), ("adr", "adr"), ("hsp", "hs"),
                                 ("fb", "fk"), ("fd", "fd")):
                    both, atk, dfn = _sides(cells.get(col))
                    rec[key] = both
                    rec[f"{key}_atk"] = atk
                    rec[f"{key}_def"] = dfn
                players.append(rec)
    return {"match": match, "maps": maps, "rounds": rounds, "players": players}


PERF_COLS = ("k2", "k3", "k4", "k5", "c1v1", "c1v2", "c1v3", "c1v4", "c1v5", "econ", "plants", "defuses")
_PERF_HEAD = {"2K": "k2", "3K": "k3", "4K": "k4", "5K": "k5", "1v1": "c1v1", "1v2": "c1v2",
              "1v3": "c1v3", "1v4": "c1v4", "1v5": "c1v5", "ECON": "econ", "PL": "plants", "DE": "defuses"}


_GAME_RE = re.compile(r'<div class="vm-stats-game[^"]*"[^>]*data-game-id="(\w+)"')


def _adv_tables(html: str):
    """Percorre as tabelas de estatísticas avançadas de cada mapa."""
    starts = [(m.start(), m.group(1)) for m in _GAME_RE.finditer(html)]
    for i, (pos, gid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        k = html.find("mod-adv-stats", pos, end)
        if gid == "all" or k < 0:
            continue
        t0 = html.rfind("<table", pos, k)
        t1 = html.find("</table>", k, end)
        if t0 >= 0 and t1 > 0:
            yield gid, _soup(html[t0:t1 + 8]).find("table")


def parse_performance_page(html: str, match_id: int) -> list[dict]:
    """Extrai multikills, clutches, plants e defuses da aba de performance."""
    out = []
    for gid, table in _adv_tables(html):
        if table is None:
            continue
        rows = table.select("tr")
        if not rows:
            continue
        heads = [_text(th) for th in rows[0].find_all(["th", "td"])]
        for tr in rows[1:]:
            tds = tr.find_all("td", recursive=False)
            team_div = tds[0].select_one(".team") if tds else None
            if not team_div:
                continue
            tag = _text(team_div.select_one(".team-tag"))
            name_holder = team_div.find("div", recursive=False) or team_div
            name = _own_text(name_holder) or _text(name_holder).replace(tag, "").strip()
            rec = {"game_id": int(gid), "match_id": match_id, "player_name": name, "team_tag": tag}
            for key in PERF_COLS:
                rec[key] = 0
            for head, td in zip(heads, tds):
                key = _PERF_HEAD.get(head)
                if not key:
                    continue
                rec[key] = _int(_own_text(td.select_one(".stats-sq")), 0)
            out.append(rec)
    return out


_MATRIX_RE = re.compile(r'<table class="wf-table-inset mod-matrix mod-(normal|fkfd|op)".*?</table>', re.S)
MATRIX_KINDS = {"normal": "all", "fkfd": "fk", "op": "op"}


def _matrix_player(td):
    """Extrai nome e tag do jogador de uma célula da matriz de abates."""
    team_div = td.select_one(".team") if td else None
    if not team_div:
        return None
    tag = _text(team_div.select_one(".team-tag"))
    holder = team_div.find("div", recursive=False) or team_div
    return {"name": _own_text(holder) or _text(holder).replace(tag, "").strip(), "tag": tag}


def parse_kill_matrix(html: str) -> dict:
    """Extrai as matrizes de abates (geral, first kills, op) de cada mapa."""
    out = {}
    starts = [(m.start(), m.group(1)) for m in _GAME_RE.finditer(html)]
    for i, (pos, gid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        for m in _MATRIX_RE.finditer(html, pos, end):
            rows = _soup(m.group(0)).find("table").find_all("tr", recursive=False)
            if len(rows) < 2:
                continue
            cols = [_matrix_player(td) for td in rows[0].find_all("td", recursive=False)[1:]]
            body, kills, deaths = [], [], []
            for tr in rows[1:]:
                tds = tr.find_all("td", recursive=False)
                who = _matrix_player(tds[0]) if tds else None
                if not who:
                    continue
                body.append(who)
                krow, drow = [], []
                for td in tds[1:len(cols) + 1]:
                    sq = td.select(".stats-sq")
                    krow.append(_int(_text(sq[0]), 0) if sq else 0)
                    drow.append(_int(_text(sq[1]), 0) if len(sq) > 1 else 0)
                kills.append(krow)
                deaths.append(drow)
            if body and cols:
                out.setdefault(gid, {})[MATRIX_KINDS[m.group(1)]] = {"rows": body, "cols": cols, "kills": kills, "deaths": deaths}
    return out
