import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "transactions")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "spark-fraud-processor")

SPARK_APP_NAME = os.getenv("SPARK_APP_NAME", "fraud-detection-stream")
SPARK_MASTER = os.getenv("SPARK_MASTER", "local[*]")

CHECKPOINT_PATH = os.getenv("CHECKPOINT_PATH", "/tmp/spark-checkpoints")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "")
CLICKHOUSE_PORT = os.getenv("CLICKHOUSE_PORT", "8443")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "fraud_detection")
CLICKHOUSE_TABLE = os.getenv("CLICKHOUSE_TABLE", "enriched_transactions")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")