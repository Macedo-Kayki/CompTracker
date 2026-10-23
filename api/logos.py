from __future__ import annotations

import threading
from urllib.parse import urlparse

import pandas as pd
import requests

import config
from api.store import store

CACHE = config.SERVING_DIR / "logos"
ALLOWED_HOSTS = {"owcdn.net", "www.owcdn.net"}
_MAGIC = {b"\x89PNG": ("png", "image/png"), b"\xff\xd8\xff": ("jpg", "image/jpeg"), b"RIFF": ("webp", "image/webp")}
_lock = threading.Lock()
_missing: set[str] = set()


def _kind(data: bytes):
    """Detecta o formato da imagem (png, jpg, webp) pelos bytes iniciais."""
    for magic, kind in _MAGIC.items():
        if data.startswith(magic):
            return kind
    return None


def _url(kind: str, key: int) -> str | None:
    """Busca a URL do logo de um time ou evento nas dimensões carregadas."""
    if kind == "team":
        df, col, id_col = store["dim_teams"], "logo_url", "team_id"
    else:
        df, col, id_col = store["dim_events"], "logo_url", "event_id"
    if col not in df:
        return None
    row = df.loc[df[id_col] == key, col]
    return row.iloc[0] if len(row) and isinstance(row.iloc[0], str) else None


def get(kind: str, key: int):
    """Retorna o logo de um time ou evento, baixando e salvando em cache se preciso."""
    for ext, media in (("png", "image/png"), ("jpg", "image/jpeg"), ("webp", "image/webp")):
        path = CACHE / kind / f"{key}.{ext}"
        if path.exists():
            return path.read_bytes(), media, ext
    url = _url(kind, key)
    if not url or url in _missing or urlparse(url).hostname not in ALLOWED_HOSTS:
        return None
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT})
        data = r.content if r.ok else b""
    except requests.RequestException:
        data = b""
    kind_info = _kind(data)
    if not kind_info or len(data) > 2_000_000:
        _missing.add(url)
        return None
    ext, media = kind_info
    with _lock:
        (CACHE / kind).mkdir(parents=True, exist_ok=True)
        (CACHE / kind / f"{key}.{ext}").write_bytes(data)
    return data, media, ext


def _tone(path) -> str | None:
    """Classifica o logo como monocromático escuro, claro ou nenhum dos dois."""
    from PIL import Image

    im = Image.open(path).convert("RGBA").resize((64, 64))
    px = [p for p in im.getdata() if p[3] > 128]
    if not px:
        return None
    sat = sum(max(p[:3]) - min(p[:3]) for p in px) / len(px)
    lum = sum(sum(p[:3]) / 3 for p in px) / len(px)
    if sat < 20 and lum < 70:
        return "dark"
    if sat < 20 and lum > 200:
        return "light"
    return None


def themed(kind: str, key: int, theme: str | None):
    """Retorna o logo adaptado ao tema, recolorindo logos monocromáticos sem contraste."""
    got = get(kind, key)
    if got is None:
        return None
    src = CACHE / kind / f"{key}.{got[2]}"
    original = (*got, src)
    if theme not in ("dark", "light"):
        return original
    try:
        tone = _tone(src)
    except Exception:
        return original
    if tone != theme:
        return original
    out = CACHE / kind / f"{key}_{theme}.png"
    if not out.exists():
        from PIL import Image

        im = Image.open(src).convert("RGBA")
        r, g, b, a = im.split()
        fill = (231, 230, 227) if theme == "dark" else (43, 42, 41)
        recolored = Image.merge("RGBA", (*(Image.new("L", im.size, c) for c in fill), a))
        with _lock:
            recolored.save(out, "PNG")
    return out.read_bytes(), "image/png", "png", out


def team_logo_path(team_id, theme: str | None = None) -> str | None:
    """Retorna o caminho do logo do time já adaptado ao tema."""
    if team_id is None or pd.isna(team_id):
        return None
    got = themed("team", int(team_id), theme)
    return str(got[3]) if got else None


_colors: dict = {}


def team_color(team_id) -> str | None:
    """Retorna a cor principal do time (manual ou extraída do logo), com cache."""
    import colorsys

    import numpy as np
    from PIL import Image

    if team_id in _colors:
        return _colors[team_id]
    if int(team_id) in config.TEAM_COLORS:
        return config.TEAM_COLORS[int(team_id)]
    path = team_logo_path(team_id, "dark")
    color = None
    if path:
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((96, 96))
                px = np.asarray(im, dtype=np.float32).reshape(-1, 4)
            px = px[px[:, 3] > 200][:, :3] / 255
            if len(px):
                hsv = np.array([colorsys.rgb_to_hsv(*p) for p in px])
                vivid = hsv[(hsv[:, 1] > 0.35) & (hsv[:, 2] > 0.25)]
                if len(vivid) >= len(px) * 0.04:
                    hist, edges = np.histogram(vivid[:, 0], bins=24, range=(0, 1))
                    k = int(np.argmax(hist))
                    sel = vivid[(vivid[:, 0] >= edges[k]) & (vivid[:, 0] < edges[k + 1])]
                    h, s, v = np.median(sel, axis=0)
                    r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s), max(0.55, min(0.9, v)))
                    color = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        except Exception:
            color = None
    _colors[team_id] = color
    return color
