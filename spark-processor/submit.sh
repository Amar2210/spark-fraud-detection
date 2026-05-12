#!/bin/bash

SPARK_HOME=${SPARK_HOME:-/opt/spark}
KAFKA_PACKAGE="org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8"

$SPARK_HOME/bin/spark-submit \
    --master local[*] \
    --driver-memory 4g \
    --executor-memory 4g \
    --packages $KAFKA_PACKAGE \
    --conf spark.sql.streaming.checkpointLocation=/tmp/spark-checkpoints \
    --conf spark.sql.adaptive.enabled=true \
    --conf spark.sql.adaptive.coalescePartitions.enabled=true \
    jobs/transaction_stream.py