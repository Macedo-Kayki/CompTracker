from __future__ import annotations

import json
import re
import threading
from urllib.parse import urlparse

import requests

import config

API = "https://valorant-api.com/v1"
CACHE = config.SERVING_DIR / "assets"
ALLOWED_HOSTS = {"media.valorant-api.com"}
HEADERS = {"User-Agent": config.USER_AGENT}
KINDS = {
    "map": ("maps", {}, ("splash",)),
    "agent": ("agents", {"isPlayableCharacter": "true"}, ("fullPortrait", "background")),
}
_lock = threading.Lock()
_catalog: dict[str, dict] = {}


def key(name: str) -> str:
    """Normaliza um nome para chave de busca (minúsculas, só letras e dígitos)."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def catalog(kind: str) -> dict:
    """Carrega o catálogo de mapas ou agentes da valorant-api, com cache em disco e memória."""
    if kind in _catalog:
        return _catalog[kind]
    path = CACHE / f"{kind}s.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        endpoint, params, _fields = KINDS[kind]
        r = requests.get(f"{API}/{endpoint}", params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = {}
        for item in r.json().get("data", []):
            data.setdefault(key(item.get("displayName")), {
                "name": item.get("displayName"),
                "colors": item.get("backgroundGradientColors"),
                **{f: item.get(f) for f in KINDS[kind][2]},
            })
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _catalog[kind] = data
    return data


def info(kind: str, name: str) -> dict | None:
    """Retorna os metadados de um mapa ou agente pelo nome, ou None se falhar."""
    try:
        return catalog(kind).get(key(name))
    except requests.RequestException:
        return None


def image(kind: str, name: str, field: str) -> tuple[bytes, str] | None:
    """Baixa (com cache) a imagem de um mapa ou agente e retorna bytes e tipo MIME."""
    meta = info(kind, name)
    if not meta or field not in KINDS[kind][2] or not meta.get(field):
        return None
    jpeg = field == "splash"
    path = CACHE / kind / f"{key(name)}-{field}.{'jpg' if jpeg else 'webp'}"
    if not path.exists():
        url = meta[field]
        if urlparse(url).hostname not in ALLOWED_HOSTS:
            return None
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        data = _to_jpeg(r.content) if jpeg else _to_webp(r.content)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return path.read_bytes(), "image/jpeg" if jpeg else "image/webp"


def _to_webp(raw: bytes) -> bytes:
    """Converte bytes de imagem para WEBP com transparência."""
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=86, method=5)
    return buf.getvalue()


def _to_jpeg(raw: bytes, width: int = 1920) -> bytes:
    """Converte bytes de imagem para JPEG, reduzindo à largura máxima informada."""
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return buf.getvalue()
