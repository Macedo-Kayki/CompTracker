"""Baixa as fotos dos títulos do Tier 1 a partir dos Flickr oficiais da Riot.

As fotos não ficam no repositório (direitos da Riot Games). O arquivo web/img/titulos/creditos.json guarda,
para cada evento, o link da foto original e o fotógrafo; este comando lê esse arquivo e baixa o que faltar.

Uso:
    python -m scraper.title_photos
"""
from __future__ import annotations

import io
import json
import re
import sys
import time

import requests

import config

FOLDER = config.ROOT / "web" / "img" / "titulos"
CREDITS = FOLDER / "creditos.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (CompTracker; projeto academico de Big Data)", "Referer": "https://www.flickr.com/"}
SIZES = ("k", "h", "b")
MAX_WIDTH = 1920
DELAY = 3.0


def _get(url):
    """Faz um GET com algumas tentativas e espera entre elas; devolve None se falhar."""
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            time.sleep(DELAY)
            return r
        if r is not None and r.status_code == 404:
            return None
        time.sleep(15 * (attempt + 1))
    return None


def _image_url(page_url):
    """Encontra na página do Flickr o link da maior versão disponível da foto."""
    pid = page_url.rstrip("/").split("/")[-1]
    page = _get(page_url)
    if page is None:
        return None
    for size in SIZES:
        m = re.search(r"live\.staticflickr\.com\\?/(\d+)\\?/" + pid + r"_([0-9a-f]+)_" + size + r"\.jpg", page.text)
        if m:
            return f"https://live.staticflickr.com/{m.group(1)}/{pid}_{m.group(2)}_{size}.jpg"
    return None


def download(event_id, source):
    """Baixa a foto de um evento, reduz para no máximo 1920 px e grava como JPEG."""
    from PIL import Image

    url = _image_url(source)
    raw = _get(url) if url else None
    if raw is None:
        return False
    im = Image.open(io.BytesIO(raw.content)).convert("RGB")
    if im.width > MAX_WIDTH:
        im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
    im.save(FOLDER / f"{event_id}.jpg", "JPEG", quality=82, optimize=True, progressive=True)
    return True


def main():
    """Baixa as fotos de títulos que ainda não existem na pasta web/img/titulos."""
    credits = json.loads(CREDITS.read_text(encoding="utf-8"))
    todo = {eid: rec for eid, rec in credits.items() if rec.get("source") and not (FOLDER / f"{eid}.jpg").exists()}
    print(f"{len(credits)} fotos no catálogo; {len(todo)} para baixar", flush=True)
    failed = []
    for i, (eid, rec) in enumerate(todo.items(), 1):
        if not download(eid, rec["source"]):
            failed.append(eid)
        print(f"  {i}/{len(todo)} · evento {eid} · {rec.get('credit', '')}", flush=True)
    if failed:
        print(f"não foi possível baixar {len(failed)}: {', '.join(failed)} (rode de novo mais tarde)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
