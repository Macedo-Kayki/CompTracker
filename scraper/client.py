from __future__ import annotations

import gzip
import threading
import time
from pathlib import Path

import requests

import config


class RateLimiter:
    """Limita a taxa de requisições entre threads a um intervalo fixo."""

    def __init__(self, rps: float):
        """Define o intervalo mínimo entre requisições a partir do RPS."""
        self.interval = 1.0 / rps
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        """Aguarda até a próxima requisição ser permitida."""
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


class VLRClient:
    """Cliente HTTP do VLR.gg com limite de taxa, retentativas e cache em disco."""
    def __init__(self, rps: float = 2.0):
        """Inicializa o limitador, as sessões por thread e os contadores."""
        self.limiter = RateLimiter(rps)
        self._local = threading.local()
        self.requests_made = 0
        self.bytes_downloaded = 0
        self._stats_lock = threading.Lock()

    def _session(self) -> requests.Session:
        """Retorna a sessão HTTP da thread atual, criando-a se preciso."""
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
            self._local.session = s
        return self._local.session

    def get(self, path: str) -> str | None:
        """Baixa uma página do VLR com retentativas, retornando None em 404."""
        url = path if path.startswith("http") else config.VLR_BASE + path
        for attempt in range(config.MAX_RETRIES + 1):
            self.limiter.wait()
            try:
                r = self._session().get(url, timeout=config.REQUEST_TIMEOUT)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code == 200:
                with self._stats_lock:
                    self.requests_made += 1
                    self.bytes_downloaded += len(r.content)
                r.encoding = "utf-8"
                return r.text
            if r is not None and r.status_code == 404:
                return None
            time.sleep(min(60, 2 ** attempt * 3))
        raise RuntimeError(f"falha ao baixar {url}")

    def cached(self, path: str, dest: Path, refresh: bool = False) -> str | None:
        """Retorna a página do cache gzip ou baixa e salva se não existir."""
        if dest.exists() and not refresh:
            return gzip.decompress(dest.read_bytes()).decode("utf-8")
        html = self.get(path)
        if html is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(gzip.compress(html.encode("utf-8"), compresslevel=6))
        tmp.replace(dest)
        return html
