from __future__ import annotations

import io
import json
import threading
from urllib.parse import urlparse

import requests

import config

MAPPING = config.BRONZE_DIR / "catalog" / "player_photos.jsonl"
CACHE = config.SERVING_DIR / "photos" / "liquipedia"
ALLOWED_HOSTS = {"liquipedia.net"}
HEADERS = {"User-Agent": config.LIQUIPEDIA_USER_AGENT}
PHOTO_EVENT_TYPES = ("Liga", "Kickoff", "Masters", "Champions")
PHOTO_MIN_MAPS = 10
MAX_WIDTH = 1600
QUALITY = 80
_lock = threading.Lock()
_index: dict[int, dict] = {}
_index_mtime = None


LEADERS = config.BRONZE_DIR / "catalog" / "photo_leaders.json"
FLICKR_MAPPING = config.BRONZE_DIR / "catalog" / "player_photos_flickr.jsonl"
FLICKR_CACHE = config.SERVING_DIR / "photos" / "flickr"
_flickr: dict = {"mtime": None, "index": {}}


def flickr_info(player_id: int) -> dict | None:
    """Retorna o registro de foto do Flickr de um jogador, recarregando se mudou."""
    if not FLICKR_MAPPING.exists():
        return None
    mtime = FLICKR_MAPPING.stat().st_mtime
    if mtime != _flickr["mtime"]:
        index = {}
        for line in FLICKR_MAPPING.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("pid"):
                index[int(rec["player_id"])] = rec
        _flickr.update(mtime=mtime, index=index)
    return _flickr["index"].get(int(player_id))


def eligible_players(player_cube) -> set[int]:
    """Retorna os jogadores com mapas suficientes no VCT para ter foto."""
    vct = player_cube[(player_cube["tier"] == 1) & player_cube["event_type"].isin(PHOTO_EVENT_TYPES)]
    maps = vct.groupby("player_id")["maps"].sum()
    return set(int(p) for p in maps[maps >= PHOTO_MIN_MAPS].index)


def leader_counts() -> dict[int, int]:
    """Lê quantas vezes cada jogador aparece como líder de métricas."""
    if not LEADERS.exists():
        return {}
    data = json.loads(LEADERS.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {int(p): 1 for p in data}


def leader_players() -> set[int]:
    """Retorna o conjunto de jogadores líderes de métricas."""
    return set(leader_counts())


def load_index() -> dict[int, dict]:
    """Carrega o índice de fotos da Liquipedia, recarregando se o arquivo mudou."""
    global _index, _index_mtime
    if not MAPPING.exists():
        return {}
    mtime = MAPPING.stat().st_mtime
    if mtime != _index_mtime:
        index = {}
        for line in MAPPING.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("url") and urlparse(rec["url"]).hostname in ALLOWED_HOSTS:
                index[int(rec["player_id"])] = rec
        _index, _index_mtime = index, mtime
    return _index


def cached_path(player_id: int):
    """Retorna o caminho da foto em cache do jogador (Liquipedia ou Flickr)."""
    for folder in (CACHE, FLICKR_CACHE):
        path = folder / f"{int(player_id)}.jpg"
        if path.exists():
            return path
    return None


def photo_info(player_id: int) -> dict | None:
    """Retorna o arquivo e a página da Liquipedia da foto do jogador."""
    rec = load_index().get(int(player_id))
    if not rec:
        return None
    return {"file": rec.get("file"), "page": f"https://liquipedia.net/valorant/{(rec.get('lp_title') or '').replace(' ', '_')}"}


def download(player_id: int) -> int:
    """Baixa e salva em JPEG a foto do jogador, retornando o status HTTP."""
    from PIL import Image

    rec = load_index().get(int(player_id))
    if not rec:
        return 404
    try:
        r = requests.get(rec["url"], timeout=30, headers=HEADERS)
    except requests.RequestException:
        return 0
    if r.status_code != 200:
        return r.status_code
    try:
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        if im.width > MAX_WIDTH:
            im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    except Exception:
        return 415
    with _lock:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{int(player_id)}.jpg").write_bytes(buf.getvalue())
    return 200


_sizes: dict[int, tuple] = {}


def photo_meta(player_id: int) -> dict | None:
    """Retorna versão, dimensões, fonte e crédito da foto do jogador."""
    from PIL import Image

    path = cached_path(player_id)
    if not path:
        return None
    mtime = int(path.stat().st_mtime)
    hit = _sizes.get(int(player_id))
    if not hit or hit[0] != mtime:
        with Image.open(path) as im:
            hit = (mtime, im.width, im.height)
        _sizes[int(player_id)] = hit
    _m, w, h = hit
    if path.parent == FLICKR_CACHE:
        info = flickr_info(player_id) or {}
        return {"version": mtime, "width": w, "height": h, "portrait": h > w * 1.1, "source": "flickr",
                "credit": info.get("credit") or "Riot Games", "page": info.get("source")}
    return {"version": mtime, "width": w, "height": h, "portrait": h > w * 1.1, "source": "liquipedia",
            "credit": "Liquipedia", "page": (photo_info(player_id) or {}).get("page")}


FOCUS_FILE = CACHE / "focus.json"
_focus: dict[str, list] = {}


def _face_center(path) -> tuple[float, float]:
    """Estima a posição do rosto na foto (em %) por cor de pele e textura."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("YCbCr")
        im.thumbnail((240, 240))
        ycc = np.asarray(im, dtype=np.float32)
    h, w = ycc.shape[:2]
    y, cb, cr = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    skin = ((cr > 135) & (cr < 175) & (cb > 85) & (cb < 130) & (y > 55) & (y < 235)).astype(np.float32)
    skin[: int(h * 0.03)] = 0
    skin[int(h * 0.8):] = 0
    gy, gx = np.gradient(y)
    edges = np.clip(np.hypot(gx, gy) / 40.0, 0, 1)
    win = max(6, int(min(w, h) * 0.16))

    def box(a):
        """Calcula a média de cada janela quadrada via imagem integral."""
        integral = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (integral[win:, win:] - integral[:-win, win:] - integral[win:, :-win] + integral[:-win, :-win]) / (win * win)

    skin_frac, texture = box(skin), box(edges)
    dark = box(((y < 70) & (skin == 0)).astype(np.float32))
    score = skin_frac * np.clip(texture / 0.18, 0, 1) * (0.55 + np.clip(dark / 0.08, 0, 1) * 0.45)
    score *= np.linspace(1.0, 0.75, score.shape[0], dtype=np.float32)[:, None]
    if score.size == 0 or score.max() < 0.05:
        return 50.0, 22.0
    r, c = np.unravel_index(np.argmax(score), score.shape)
    return round((c + win / 2) / w * 100, 1), round((r + win / 2) / h * 100, 1)


FOCUS_OVERRIDES = config.BRONZE_DIR / "catalog" / "photo_focus.json"


def focus(player_id: int) -> tuple[float, float]:
    """Retorna o ponto de foco da foto do jogador, manual ou estimado, com cache."""
    path = cached_path(player_id)
    if not path:
        return 50.0, 40.0
    if FOCUS_OVERRIDES.exists():
        manual = json.loads(FOCUS_OVERRIDES.read_text(encoding="utf-8")).get(str(int(player_id)))
        if manual:
            return float(manual[0]), float(manual[1])
    key = f"{int(player_id)}:{int(path.stat().st_mtime)}"
    if not _focus and FOCUS_FILE.exists():
        _focus.update(json.loads(FOCUS_FILE.read_text(encoding="utf-8")))
    if key not in _focus:
        _focus[key] = list(_face_center(path))
        with _lock:
            FOCUS_FILE.write_text(json.dumps(_focus), encoding="utf-8")
    return tuple(_focus[key])


def player_photo(player_id: int):
    """Retorna os bytes e o tipo MIME da foto em cache do jogador."""
    path = cached_path(player_id)
    return (path.read_bytes(), "image/jpeg") if path else None
