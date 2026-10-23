from __future__ import annotations

import json
import threading
from dataclasses import dataclass

import pandas as pd

import config

TABLES = ("dim_events", "dim_teams", "dim_players", "team_cube", "team_map_cube", "player_cube",
          "agent_cube", "player_agent_cube", "map_cube", "round_cube", "matches_fact", "top_performances",
          "team_prizes", "player_maps_fact")


@dataclass(frozen=True)
class Filters:
    """Filtros globais (ano, tier, região, tipo e evento) aplicados às tabelas."""
    year: int | None = None
    tier: int | None = None
    region: str | None = None
    event_type: str | None = None
    event_id: int | None = None

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtra o DataFrame pelas colunas de filtro que ele possuir."""
        mask = pd.Series(True, index=df.index)
        if self.year is not None and "year" in df:
            mask &= df["year"] == self.year
        if self.tier is not None and "tier" in df:
            mask &= df["tier"] == self.tier
        if self.region and "region" in df:
            mask &= df["region"] == self.region
        if self.event_type and "event_type" in df:
            mask &= df["event_type"] == self.event_type
        if self.event_id is not None and "event_id" in df:
            mask &= df["event_id"] == self.event_id
        return df[mask]


class Store:
    """Guarda em memória as tabelas da camada de serving."""
    def __init__(self):
        """Inicializa o armazenamento vazio."""
        self._lock = threading.Lock()
        self.tables: dict[str, pd.DataFrame] = {}
        self.manifest: dict = {}
        self.version = 0

    @property
    def ready(self) -> bool:
        """Indica se as tabelas já foram carregadas."""
        return bool(self.tables)

    def load(self):
        """Carrega os CSVs da camada de serving e o manifesto do lake."""
        tables = {}
        for name in TABLES:
            path = config.SERVING_DIR / f"{name}.csv"
            if not path.exists():
                return False
            tables[name] = pd.read_csv(path, low_memory=False)
        for name in ("dim_events", "matches_fact", "top_performances", "player_maps_fact"):
            for col in ("start_date", "end_date", "match_date"):
                if col in tables[name]:
                    tables[name][col] = pd.to_datetime(tables[name][col], errors="coerce")
        mpath = config.SERVING_DIR / "lake_manifest.json"
        with self._lock:
            self.tables = tables
            self.manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
            self.version += 1
        return True

    def __getitem__(self, name: str) -> pd.DataFrame:
        """Retorna a tabela pelo nome."""
        return self.tables[name]


store = Store()
