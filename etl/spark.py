from __future__ import annotations

import os
import sys

import config


def get_spark(app: str = "CompTracker", memory: str = "4g"):
    """Configura o ambiente Hadoop e cria a sessão Spark local."""
    hadoop_bin = config.HADOOP_HOME / "bin"
    os.environ["HADOOP_HOME"] = str(config.HADOOP_HOME)
    os.environ["PATH"] = str(hadoop_bin) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable
    os.environ["PYTHONPATH"] = str(config.ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")

    from pyspark.sql import SparkSession

    lib_path = hadoop_bin.as_posix()
    spark = (
        SparkSession.builder.appName(app)
        .master("local[*, 4]")
        .config("spark.driver.memory", memory)
        .config("spark.driver.extraJavaOptions", f"-Djava.library.path={lib_path}")
        .config("spark.sql.execution.arrow.pyspark.enabled", "false")
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def lake_uri(path) -> str:
    """Converte um caminho local em URI file:// para o Spark."""
    posix = path.resolve().as_posix()
    return "file://" + posix if posix.startswith("/") else "file:///" + posix
