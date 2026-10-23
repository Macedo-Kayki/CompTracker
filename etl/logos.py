from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

import config
from etl.spark import lake_uri

HEAD_BYTES = 120_000


def _logos(rows):
    """Extrai do cabeçalho do HTML de cada partida os logos dos dois times."""
    import re
    import zlib

    anchor = re.compile(r'<a\b[^>]*\bmatch-header-link\b[^>]*>(.*?)</a>', re.S)
    team = re.compile(r'href="/team/(\d+)/')
    img = re.compile(r'<img[^>]*\bsrc="([^"]+)"')
    for r in rows:
        mid = int(re.search(r"(\d+)\.html\.gz$", r.path).group(1))
        try:
            head = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(bytes(r.content), HEAD_BYTES).decode("utf-8", "ignore")
        except zlib.error:
            continue
        for m in anchor.finditer(head):
            tag = head[m.start():m.start() + 300]
            tm, im = team.search(tag), img.search(m.group(1))
            if not tm or not im:
                continue
            src = im.group(1)
            if "/img/vlr/tmp/vlr.png" in src:
                continue
            yield (int(tm.group(1)), "https:" + src if src.startswith("//") else src, mid)


def build_team_logos(spark: SparkSession) -> int:
    """Gera na silver o logo mais recente de cada time a partir das partidas."""
    files = [lake_uri(p) for p in sorted(Path(config.BRONZE_DIR / "matches").rglob("*.html.gz"))]
    df = (spark.read.format("binaryFile").load(files).select("path", "content")
          .repartition(spark.sparkContext.defaultParallelism * 2))
    logos = spark.createDataFrame(df.rdd.mapPartitions(_logos), "team_id long, logo_url string, match_id long")
    w = Window.partitionBy("team_id").orderBy(F.col("match_id").desc())
    latest = logos.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")
    out = lake_uri(config.SILVER_DIR / "team_logos")
    latest.write.mode("overwrite").parquet(out)
    n = spark.read.parquet(out).count()
    print(f"  silver/team_logos: {n:,} linhas", flush=True)
    return n
