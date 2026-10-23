from __future__ import annotations

import json
import time

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

import config
from etl.classify import REGIONS
from etl.spark import lake_uri

PERF = ("k2", "k3", "k4", "k5", "c1v1", "c1v2", "c1v3", "c1v4", "c1v5", "plants", "defuses")


def _read(spark, name) -> DataFrame:
    """Lê uma tabela Parquet da camada silver."""
    return spark.read.parquet(lake_uri(config.SILVER_DIR / name))


def _team_maps(maps: DataFrame) -> DataFrame:
    """Transforma cada mapa em duas linhas, uma por time, com rounds por lado."""
    def side(me, opp, start):
        """Seleciona as colunas do mapa sob a perspectiva de um dos times."""
        return maps.select(
            "game_id", "match_id", "year", "map_name", "picked_by", "winner_id", "duration_sec",
            F.col(f"{me}_id").alias("team_id"), F.col(f"{opp}_id").alias("opp_id"),
            F.col(f"{me}_score").alias("score"), F.col(f"{opp}_score").alias("opp_score"),
            F.col(f"{me}_atk").alias("atk_won"), F.col(f"{me}_def").alias("def_won"), F.col(f"{me}_ot").alias("ot_won"),
            F.col(f"{opp}_atk").alias("opp_atk"), F.col(f"{opp}_def").alias("opp_def"), F.col(f"{opp}_ot").alias("opp_ot"),
            start.alias("start_side"))

    flip = F.when(F.col("team1_start") == "atk", "def").when(F.col("team1_start") == "def", "atk")
    tm = side("team1", "team2", F.col("team1_start")).unionByName(side("team2", "team1", flip))
    return (tm.withColumn("won", (F.col("winner_id") == F.col("team_id")).cast("int"))
              .withColumn("atk_played", F.col("atk_won") + F.col("opp_def"))
              .withColumn("def_played", F.col("def_won") + F.col("opp_atk"))
              .withColumn("ot_played", F.col("ot_won") + F.col("opp_ot"))
              .withColumn("picked", (F.col("picked_by") == F.col("team_id")).cast("int"))
              .withColumn("rounds", F.col("score") + F.col("opp_score")))


def _rename_players(df: DataFrame) -> DataFrame:
    """Aplica os nomes de jogador corrigidos manualmente na configuração."""
    for pid, name in config.PLAYER_NAME_OVERRIDES.items():
        df = df.withColumn("player_name", F.when(F.col("player_id") == pid, F.lit(name)).otherwise(F.col("player_name")))
    return df


def _latest(df: DataFrame, key: str, ts: str, cols: list[str]) -> DataFrame:
    """Mantém, para cada chave, as colunas da linha mais recente."""
    w = Window.partitionBy(key).orderBy(F.col(ts).desc_nulls_last())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").select(key, *cols)


def build_gold(spark: SparkSession) -> dict:
    """Monta as dimensões, cubos e fatos da camada gold e exporta para CSV."""
    events = _read(spark, "events")
    events = events.withColumn("name", F.regexp_replace("name", "China Evolution Series", "VCT CN"))
    if "logo_url" not in events.columns:
        events = events.withColumn("logo_url", F.lit(None).cast("string"))
    placements = _read(spark, "placements")
    logos_path = config.SILVER_DIR / "team_logos"
    team_logos = (spark.read.parquet(lake_uri(logos_path)).select("team_id", "logo_url") if logos_path.exists()
                  else spark.createDataFrame([], "team_id long, logo_url string"))
    matches = _read(spark, "matches")
    maps = _read(spark, "maps")
    rounds = _read(spark, "rounds")
    players = _rename_players(_read(spark, "player_maps"))

    ev_attr = events.select("event_id", F.col("name").alias("event_name"), "region", "event_type", "tier")
    m_ev = matches.select("match_id", "event_id", "match_ts", "match_date")

    gf = (matches.where(F.lower("round_label").contains("grand final") | F.lower("series_text").contains("grand final"))
          .withColumn("loser_id", F.when(F.col("winner_id") == F.col("team1_id"), F.col("team2_id")).otherwise(F.col("team1_id")))
          .withColumn("_rn", F.row_number().over(Window.partitionBy("event_id").orderBy(F.col("match_ts").desc_nulls_last())))
          .where("_rn = 1").select("event_id", F.col("winner_id").alias("gf_winner"), F.col("loser_id").alias("gf_loser")))
    first = placements.where("place = 1").groupBy("event_id").agg(F.first("team_id").alias("p1"))
    second = placements.where("place = 2").groupBy("event_id").agg(F.first("team_id").alias("p2"))
    champs = (events.where(F.col("status") == "completed").select("event_id")
              .join(first, "event_id", "left").join(second, "event_id", "left").join(gf, "event_id", "left")
              .select("event_id", F.coalesce("p1", "gf_winner").alias("champion_id"),
                      F.coalesce("p2", "gf_loser").alias("runner_up_id"))
              .where(F.col("champion_id").isNotNull()))

    match_teams = (matches.select("match_ts", F.col("team1_id").alias("team_id"), F.col("team1_name").alias("team_name"))
                   .unionByName(matches.select("match_ts", F.col("team2_id").alias("team_id"), F.col("team2_name").alias("team_name"))))
    tm = _team_maps(maps).join(m_ev, "match_id")
    team_region = (tm.join(ev_attr.select("event_id", "region"), "event_id")
                   .where(F.col("region").isin(*REGIONS))
                   .groupBy("team_id", "region").count()
                   .withColumn("_rn", F.row_number().over(Window.partitionBy("team_id").orderBy(F.desc("count"))))
                   .where("_rn = 1").select("team_id", F.col("region").alias("team_region")))
    if "team_country" in placements.columns:
        placed = (placements.where(F.col("team_country").isNotNull() & (F.col("team_country") != ""))
                  .join(events.select("event_id", "end_date"), "event_id")
                  .select("team_id", "team_country", "end_date"))
        from_placements = _latest(placed, "team_id", "end_date", ["team_country"])
    else:
        from_placements = spark.createDataFrame([], "team_id long, team_country string")
    roster = (players.where(F.col("country").isNotNull()).groupBy("team_id", "country").count()
              .withColumn("_rn", F.row_number().over(Window.partitionBy("team_id").orderBy(F.desc("count"))))
              .where("_rn = 1").select("team_id", F.col("country").alias("roster_country")))
    team_country = (from_placements.join(roster, "team_id", "full")
                    .select("team_id", F.coalesce("team_country", "roster_country").alias("team_country")))
    dim_teams = (_latest(match_teams, "team_id", "match_ts", ["team_name"])
                 .join(match_teams.groupBy("team_id").agg(F.year(F.min("match_ts")).alias("first_year"),
                                                          F.year(F.max("match_ts")).alias("last_year")), "team_id")
                 .join(team_region, "team_id", "left")
                 .join(team_logos, "team_id", "left")
                 .join(team_country, "team_id", "left")
                 .fillna({"team_region": "Outros"}))
    tname = dim_teams.select("team_id", "team_name")

    pl_ts = players.join(m_ev.select("match_id", "match_ts"), "match_id")
    dim_players = (_latest(pl_ts, "player_id", "match_ts", ["player_name", "country", "team_id"])
                   .withColumnRenamed("team_id", "current_team_id")
                   .join(tname.withColumnRenamed("team_id", "current_team_id")
                              .withColumnRenamed("team_name", "current_team_name"), "current_team_id", "left"))

    place_prize = placements.groupBy("event_id", "place").agg(F.max("prize_usd").alias("place_prize"))
    champ_prize = place_prize.where("place = 1").select("event_id", F.col("place_prize").alias("champion_prize_usd"))
    vice_prize = place_prize.where("place = 2").select("event_id", F.col("place_prize").alias("runner_up_prize_usd"))
    dim_events = (events.join(champs, "event_id", "left")
                  .join(champ_prize, "event_id", "left").join(vice_prize, "event_id", "left")
                  .join(tname.select(F.col("team_id").alias("champion_id"), F.col("team_name").alias("champion_name")), "champion_id", "left")
                  .join(tname.select(F.col("team_id").alias("runner_up_id"), F.col("team_name").alias("runner_up_name")), "runner_up_id", "left")
                  .select("event_id", "name", "year", "region", "event_type", "tier", "status", "prize_usd", "logo_url",
                          "location", "start_date", "end_date", "n_matches", "champion_id", "champion_name",
                          "champion_prize_usd", "runner_up_id", "runner_up_name", "runner_up_prize_usd", "slug"))

    team_prizes = (placements.where(F.col("team_id").isNotNull())
                   .groupBy("team_id", "event_id").agg(F.min("place").alias("place"), F.max("prize_usd").alias("prize_usd"))
                   .join(events.select("event_id", "year", "tier", "region", "event_type"), "event_id", "inner"))

    pistols = (rounds.where(F.col("round_no").isin(1, 13)).select("game_id", "winner_id")
               .join(tm.select("game_id", "team_id"), "game_id")
               .groupBy("game_id", "team_id")
               .agg(F.count("*").alias("pistols_played"),
                    F.sum((F.col("winner_id") == F.col("team_id")).cast("int")).alias("pistols_won")))
    tm_full = tm.join(pistols, ["game_id", "team_id"], "left").fillna({"pistols_played": 0, "pistols_won": 0})

    map_meas = [F.count("*").alias("maps"), F.sum("won").alias("map_wins"),
                F.sum("score").alias("rounds_won"), F.sum("opp_score").alias("rounds_lost"),
                F.sum("atk_won").alias("atk_won"), F.sum("atk_played").alias("atk_played"),
                F.sum("def_won").alias("def_won"), F.sum("def_played").alias("def_played"),
                F.sum("ot_won").alias("ot_won"), F.sum("ot_played").alias("ot_played"),
                F.sum("picked").alias("picks"), F.sum(F.col("picked") * F.col("won")).alias("pick_wins"),
                F.sum("pistols_won").alias("pistols_won"), F.sum("pistols_played").alias("pistols_played"),
                F.sum((F.col("start_side") == "atk").cast("int")).alias("start_atk_maps"),
                F.sum(((F.col("start_side") == "atk") & (F.col("won") == 1)).cast("int")).alias("start_atk_wins"),
                F.sum((F.col("start_side") == "def").cast("int")).alias("start_def_maps"),
                F.sum(((F.col("start_side") == "def") & (F.col("won") == 1)).cast("int")).alias("start_def_wins")]
    team_maps_agg = tm_full.groupBy("team_id", "event_id", "year").agg(*map_meas)

    mt = (matches.select("match_id", "event_id", "year", "winner_id", F.col("team1_id").alias("team_id"))
          .unionByName(matches.select("match_id", "event_id", "year", "winner_id", F.col("team2_id").alias("team_id"))))
    team_matches_agg = (mt.groupBy("team_id", "event_id", "year")
                        .agg(F.count("*").alias("matches"),
                             F.sum((F.col("winner_id") == F.col("team_id")).cast("int")).alias("match_wins")))
    team_cube = (team_matches_agg.join(team_maps_agg, ["team_id", "event_id", "year"], "left").fillna(0)
                 .join(ev_attr, "event_id", "left"))

    team_map_cube = (tm_full.groupBy("team_id", "event_id", "year", "map_name")
                     .agg(*map_meas[:12]).join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    pm = (players.join(maps.select("game_id", "map_name", (F.col("team1_score") + F.col("team2_score")).alias("rounds")), "game_id")
          .join(tm.select("game_id", "team_id", "won"), ["game_id", "team_id"], "left")
          .join(m_ev.select("match_id", "event_id"), "match_id"))

    def wsum(stat, weight):
        """Soma a estatística ponderada pelo peso, ignorando nulos."""
        return F.sum(F.when(F.col(stat).isNotNull(), F.col(stat) * F.col(weight)))

    def wden(stat, weight):
        """Soma os pesos das linhas em que a estatística não é nula."""
        return F.sum(F.when(F.col(stat).isNotNull(), F.col(weight)))

    player_cube = (pm.groupBy("player_id", "team_id", "event_id", "year").agg(
        F.count("*").alias("maps"), F.sum("won").alias("map_wins"), F.sum("rounds").alias("rounds"),
        *[F.sum(c).alias(c) for c in ("k", "d", "a", "fk", "fd", "k_atk", "k_def", "d_atk", "d_def")],
        wsum("rating", "rounds").alias("rating_x_rounds"), wden("rating", "rounds").alias("rating_rounds"),
        wsum("acs", "rounds").alias("acs_x_rounds"), wden("acs", "rounds").alias("acs_rounds"),
        wsum("adr", "rounds").alias("adr_x_rounds"), wden("adr", "rounds").alias("adr_rounds"),
        wsum("kast", "rounds").alias("kast_x_rounds"), wden("kast", "rounds").alias("kast_rounds"),
        wsum("hs", "k").alias("hs_x_kills"), wden("hs", "k").alias("hs_kills"),
        F.sum(F.col("has_perf").cast("int")).alias("perf_maps"),
        *[F.sum(c).alias(c) for c in PERF],
        F.countDistinct("agent").alias("agents_used"))
        .withColumn("clutches", sum(F.col(c) for c in ("c1v1", "c1v2", "c1v3", "c1v4", "c1v5")))
        .join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    agent_cube = (pm.where(F.col("agent").isNotNull()).groupBy("agent", "map_name", "event_id", "year")
                  .agg(F.count("*").alias("picks"), F.sum("won").alias("wins"), F.sum("rounds").alias("rounds"),
                       F.sum("k").alias("k"), F.sum("d").alias("d"))
                  .join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    player_agent_cube = (pm.where(F.col("agent").isNotNull()).groupBy("player_id", "agent", "event_id", "year")
                         .agg(F.count("*").alias("maps"), F.sum("won").alias("wins"), F.sum("k").alias("k"),
                              F.sum("d").alias("d"), F.sum("rounds").alias("rounds"),
                              wsum("rating", "rounds").alias("rating_x_rounds"), wden("rating", "rounds").alias("rating_rounds"))
                         .join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    map_cube = (maps.join(m_ev.select("match_id", "event_id"), "match_id")
                .groupBy("map_name", "event_id", "year")
                .agg(F.count("*").alias("maps"),
                     F.sum(F.col("team1_atk") + F.col("team2_atk")).alias("atk_won"),
                     F.sum(F.col("team1_def") + F.col("team2_def")).alias("def_won"),
                     F.sum((F.col("team1_ot") + F.col("team2_ot") > 0).cast("int")).alias("ot_maps"),
                     F.sum(F.col("picked_by").isNotNull().cast("int")).alias("picks"),
                     F.sum(F.col("duration_sec")).alias("duration_sum"),
                     F.sum(F.col("duration_sec").isNotNull().cast("int")).alias("duration_maps"))
                .join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    round_kind = (F.when(F.col("round_no").isin(1, 13), "pistol")
                  .when(F.col("round_no") > 24, "overtime").otherwise("normal"))
    round_cube = (rounds.join(m_ev.select("match_id", "event_id"), "match_id")
                  .withColumn("round_kind", round_kind)
                  .groupBy("event_id", "year", "winner_side", "win_type", "round_kind").count()
                  .withColumnRenamed("count", "rounds")
                  .join(ev_attr.select("event_id", "region", "event_type", "tier"), "event_id", "left"))

    matches_fact = (matches.join(ev_attr, "event_id", "left")
                    .select("match_id", "match_date", "year", "event_id", "event_name", "region", "event_type", "tier",
                            "stage_label", "round_label", "best_of", "team1_id", "team1_name", "team2_id",
                            "team2_name", "team1_score", "team2_score", "winner_id", "patch"))

    opp = tm.select("game_id", "team_id", "opp_id")
    perf_rows = (pm.join(opp, ["game_id", "team_id"], "left")
                 .join(tname.select(F.col("team_id").alias("opp_id"), F.col("team_name").alias("opp_name")), "opp_id", "left")
                 .join(m_ev.select("match_id", "match_date"), "match_id"))
    player_maps_fact = (perf_rows.join(ev_attr.select("event_id", "tier", "region", "event_type"), "event_id", "left")
                        .select("game_id", "match_id", "match_date", "year", "event_id", "tier", "region", "event_type",
                                "player_id", "team_id", "opp_id", "map_name", "agent", "rounds", "won",
                                "k", "d", "a", "acs", "rating", "adr", "hs", "fk", "k4", "k5"))
    ranked = None
    for metric in ("k", "rating", "acs"):
        w = Window.partitionBy("event_id").orderBy(F.col(metric).desc_nulls_last())
        part = perf_rows.withColumn("_rn", F.row_number().over(w)).where("_rn <= 25").drop("_rn")
        ranked = part if ranked is None else ranked.unionByName(part)
    top_performances = (ranked.dropDuplicates(["game_id", "player_id"])
                        .join(ev_attr, "event_id", "left")
                        .select("game_id", "match_id", "match_date", "year", "event_id", "event_name", "region",
                                "event_type", "tier", "player_id", "player_name", "team_id", "team_name", "opp_id", "opp_name",
                                "map_name", "agent", "rounds", "won", "k", "d", "a", "acs", "rating", "adr", "hs",
                                "fk", "k4", "k5"))

    gold = {
        "dim_events": dim_events, "dim_teams": dim_teams, "dim_players": dim_players,
        "team_cube": team_cube, "team_map_cube": team_map_cube, "player_cube": player_cube,
        "agent_cube": agent_cube, "player_agent_cube": player_agent_cube, "map_cube": map_cube, "round_cube": round_cube,
        "matches_fact": matches_fact, "top_performances": top_performances, "team_prizes": team_prizes,
        "player_maps_fact": player_maps_fact,
    }
    config.SERVING_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, df in gold.items():
        df.write.mode("overwrite").parquet(lake_uri(config.GOLD_DIR / name))
        pdf = spark.read.parquet(lake_uri(config.GOLD_DIR / name)).toPandas()
        pdf.to_csv(config.SERVING_DIR / f"{name}.csv", index=False, encoding="utf-8")
        counts[name] = len(pdf)
        print(f"  gold/{name}: {counts[name]:,} linhas", flush=True)
    return counts


def write_manifest(spark: SparkSession, silver_counts: dict, gold_counts: dict):
    """Grava o manifesto do lake com tamanho de cada camada e contagens."""
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    layers = {}
    for name, folder in (("bronze", config.BRONZE_DIR), ("silver", config.SILVER_DIR),
                         ("gold", config.GOLD_DIR), ("serving", config.SERVING_DIR)):
        if not folder.exists():
            continue
        path = jvm.org.apache.hadoop.fs.Path(lake_uri(folder))
        fs = path.getFileSystem(conf)
        cs = fs.getContentSummary(path)
        layers[name] = {"bytes": cs.getLength(), "files": cs.getFileCount(), "dirs": cs.getDirectoryCount(),
                        "uri": lake_uri(folder), "filesystem": fs.getClass().getName()}
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "spark_version": spark.version,
        "hadoop_version": jvm.org.apache.hadoop.util.VersionInfo.getVersion(),
        "period": [config.START_DATE.isoformat(), config.END_DATE.isoformat()],
        "layers": layers, "silver_rows": silver_counts, "gold_rows": gold_counts,
    }
    (config.SERVING_DIR / "lake_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
