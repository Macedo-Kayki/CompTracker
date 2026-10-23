"""Pipeline Spark: bronze -> silver -> gold -> serving.

Uso:
    python -m etl.run              # pipeline completo
    python -m etl.run --only gold  # reaproveita a silver já gerada
    python -m etl.run --full       # refaz o parsing de todo o HTML (por padrão só os arquivos novos)
"""
from __future__ import annotations

import argparse
import json
import time

import config
from etl.gold import build_gold, write_manifest
from etl.logos import build_team_logos
from etl.silver import build_silver
from etl.spark import get_spark


def main(argv=None):
    """Executa o pipeline Spark silver e gold conforme os argumentos da linha de comando."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["silver", "gold"])
    ap.add_argument("--memory", default="4g", help="memória do driver Spark")
    ap.add_argument("--full", action="store_true",
                    help="refaz o parsing de todo o HTML; por padrão a staging é incremental")
    args = ap.parse_args(argv)

    spark = get_spark(memory=args.memory)
    t0 = time.time()
    silver_counts, gold_counts = {}, {}
    try:
        if args.only != "gold":
            print("== silver (parsing do HTML bruto em paralelo)", flush=True)
            silver_counts = build_silver(spark, full=args.full)
            print("== logos dos times (cabeçalho das partidas)", flush=True)
            silver_counts["team_logos"] = build_team_logos(spark)
        else:
            old = config.SERVING_DIR / "lake_manifest.json"
            if old.exists():
                silver_counts = json.loads(old.read_text(encoding="utf-8")).get("silver_rows", {})
        if args.only != "silver":
            print("== gold (cubos agregados) + serving (CSV)", flush=True)
            gold_counts = build_gold(spark)
        manifest = write_manifest(spark, silver_counts, gold_counts)
        for name, layer in manifest["layers"].items():
            print(f"  {name:8s} {layer['files']:>7,} arquivos  {layer['bytes'] / 2**20:>9.1f} MB")
        print(f"ok em {time.time() - t0:.0f}s", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
