"""
Configuration — All tuneable settings for the data generator.

Every setting can be overridden via environment variables.
This means you can change behavior without editing code:

    # On the VM, before running the generator:
    export FRAUD_RATE=0.05          # increase fraud to 5%
    export NUM_CARDHOLDERS=50000    # double the cardholders
    python generator.py

If no env var is set, the default value is used.
"""

import os


# =============================================================================
# GENERATOR SETTINGS
# =============================================================================

# Number of simulated cardholders (people with cards)
# 25,000 gives ~1 transaction/day per person at our target volume
NUM_CARDHOLDERS = int(os.getenv("NUM_CARDHOLDERS", "25000"))

# Target transactions per day (approximate, varies with time-of-day curve)
# The hourly rate multipliers in transaction_schema.py shape the distribution
TARGET_DAILY_TRANSACTIONS = int(os.getenv("TARGET_DAILY_TRANSACTIONS", "24000"))

# Fraud rate: what percentage of transactions are fraudulent
# Real-world is 0.1-0.5%, but we inflate to 3-5% so dashboards have
# enough fraud data to show meaningful patterns
FRAUD_RATE = float(os.getenv("FRAUD_RATE", "0.04"))  # 4% default


# =============================================================================
# PUB/SUB SETTINGS (for when we wire up Pub/Sub later)
# =============================================================================

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "spark-fraud-detection")
PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC", "transactions-stream")

# How many messages to batch before publishing
# Pub/Sub is more efficient when you send messages in batches
# rather than one at a time
PUBSUB_BATCH_SIZE = int(os.getenv("PUBSUB_BATCH_SIZE", "50"))


# =============================================================================
# OUTPUT MODE
# =============================================================================
# "local"  → prints JSON to console (for testing)
# "csv"    → writes to a CSV file (for testing with files)
# "pubsub" → publishes to Google Cloud Pub/Sub (production)

OUTPUT_MODE = os.getenv("OUTPUT_MODE", "local")

# CSV output path (only used when OUTPUT_MODE=csv)
CSV_OUTPUT_PATH = os.getenv("CSV_OUTPUT_PATH", "output/transactions.csv")


# =============================================================================
# INTERNAL TRACKING
# =============================================================================

# How many recent transactions to keep per cardholder in memory
# Used internally to craft realistic fraud (e.g., geographic anomaly
# needs to know last transaction location). NOT included in output.
# 10 is enough for all fraud patterns and uses ~3KB per cardholder.
MAX_RECENT_TRANSACTIONS = int(os.getenv("MAX_RECENT_TRANSACTIONS", "10"))

# How many unique merchants to remember per cardholder
# Used internally to decide "is this a new merchant for this person?"
# The generator needs this to craft account_takeover fraud realistically.
MAX_KNOWN_MERCHANTS = int(os.getenv("MAX_KNOWN_MERCHANTS", "20"))


# =============================================================================
# LOGGING
# =============================================================================

# How often to print a status line (every N transactions)
LOG_EVERY_N = int(os.getenv("LOG_EVERY_N", "100"))

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
