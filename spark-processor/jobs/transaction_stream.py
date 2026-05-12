"""
Fraud Detection Stream Processing Job

Kafka -> Spark Structured Streaming -> Console/ClickHouse

This is the main streaming job for real-time fraud detection.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, window, count, avg
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType, TimestampType

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.transaction_schema import TRANSACTION_SCHEMA
from configs.streaming_config import (
    KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, KAFKA_CONSUMER_GROUP,
    CHECKPOINT_PATH, SPARK_APP_NAME
)


def create_spark_session():
    """Create and configure SparkSession for streaming."""
    spark = SparkSession.builder \
        .appName(SPARK_APP_NAME) \
        .config("spark.sql.streaming.checkpointLocation", CHECKPOINT_PATH) \
        .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8") \
        .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")
    return spark


def read_from_kafka(spark):
    """Read streaming data from Kafka topic."""
    return spark \
        .readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS) \
        .option("subscribe", KAFKA_TOPIC) \
        .option("startingOffsets", "latest") \
        .option("failOnDataLoss", "false") \
        .load()


def parse_json(df):
    """Parse JSON value from Kafka into structured DataFrame."""
    return df \
        .select(from_json(col("value").cast("string"), TRANSACTION_SCHEMA).alias("data")) \
        .select("data.*")


def main():
    spark = create_spark_session()

    raw_kafka_df = read_from_kafka(spark)
    parsed_df = parse_json(raw_kafka_df)

    base_df = parsed_df.withWatermark("timestamp", "30 minutes")

    # TODO: Add window-based features (transactions_last_1hr, transactions_last_24hr, avg_transaction_amount_30d)
    # TODO: Add stateful features (minutes_since_last_txn, distance_from_last_txn_km, is_new_merchant)
    # TODO: Join all features
    # TODO: Write to console sink

    query = base_df \
        .writeStream \
        .format("console") \
        .option("checkpointLocation", CHECKPOINT_PATH) \
        .outputMode("append") \
        .trigger(processingTime="5 seconds") \
        .start()

    query.awaitTermination()


if __name__ == "__main__":
    main()