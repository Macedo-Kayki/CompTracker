import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DATA_DIR = Path(os.environ.get("COMPTRACKER_DATA", ROOT / "data")).resolve()
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
SERVING_DIR = DATA_DIR / "serving"
HADOOP_HOME = ROOT / "hadoop"

START_DATE = date(2021, 1, 1)
END_DATE = date(2026, 10, 20)
VLR_TIERS = {60: 1, 61: 2, 62: 3}
DEFAULT_TIERS = (60, 61, 62)
DEFAULT_MIN_PRIZE = {62: 5000}

VLR_BASE = "https://www.vlr.gg"
USER_AGENT = "Mozilla/5.0 (CompTracker; projeto academico de Big Data)"
CONTACT_EMAIL = "macedokayki@gmail.com"
LIQUIPEDIA_USER_AGENT = f"CompTracker/1.0 (projeto academico de Big Data em Python; {CONTACT_EMAIL})"
REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 40
MAX_RETRIES = 4

PLAYER_NAME_OVERRIDES = {
    28716: "luk xo",
}

TEAM_COLORS = {
    2059: "#f5e100",
    624: "#e5397f",
    8877: "#1fb6e8",
    11058: "#e1251b",
    257: "#e1251b",
    474: "#1d5fbf",
}
