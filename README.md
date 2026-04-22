# Spark Fraud Detection — Real-Time Streaming Pipeline

## Overview

A production-style real-time fraud detection system built on Google Cloud Platform. Synthetic credit card transaction data is generated, streamed through Google Pub/Sub, processed by Apache Spark Structured Streaming for anomaly detection, and results are stored in ClickHouse for analytical querying and Grafana dashboards.

---

## Architecture

```
┌─────────────────────┐
│   GCP VM: Server 1  │
│   (e2-medium)       │
│                     │
│  Python Data        │
│  Generator          │
│  - Faker library    │
│  - Taxonomy-based   │
│    fraud patterns   │
│  - Configurable     │
│    volume & speed   │
│                     │
└────────┬────────────┘
         │ publishes JSON messages
         ▼
┌─────────────────────┐
│  Google Cloud        │
│  Pub/Sub             │
│                      │
│  Topic:              │
│  transactions-stream │
│                      │
└────────┬─────────────┘
         │ Spark reads via subscription
         ▼
┌─────────────────────┐
│   GCP VM: Server 2  │
│   (e2-standard-4)   │
│                     │
│  Apache Spark 3.5   │
│  Structured         │
│  Streaming          │
│                     │
│  Fraud Detection:   │
│  - Rule-based       │
│  - Z-score          │
│  - Isolation Forest │
│                     │
└────────┬────────────┘
         │ writes processed results
         ▼
┌─────────────────────┐       ┌─────────────────────┐
│  ClickHouse Cloud   │◄──────│  Grafana Dashboard  │
│  (Free Tier)        │       │                     │
│                     │       │  - Fraud rate/time  │
│  Tables:            │       │  - Fraud by type    │
│  - raw_transactions │       │  - Amount distrib.  │
│  - fraud_alerts     │       │  - Geo heatmap      │
│  - processing_stats │       │  - Live alerts      │
└─────────────────────┘       └─────────────────────┘
```
Generator → Pub/Sub → Spark → ClickHouse
The key insight: **Pub/Sub is a pipe, not a database.** Messages flow through it. 
Spark grabs them, processes them, and writes to ClickHouse. GCS is only for 
Spark's internal "I was here" marker.
We need google cloud storage for 

---

## Tech Stack

| Component            | Technology                          | Purpose                              |
|----------------------|-------------------------------------|--------------------------------------|
| Data Generation      | Python 3.11, Faker, NumPy           | Generate synthetic transaction data  |
| Message Queue        | Google Cloud Pub/Sub                | Decouple generator from processor    |
| Stream Processing    | Apache Spark 3.5 (Structured Streaming) | Real-time fraud detection        |
| Analytical Database  | ClickHouse Cloud (Free Tier)        | Store & query processed results      |
| Visualization        | Grafana + ClickHouse Plugin         | Real-time dashboards                 |
| Infrastructure       | Google Cloud Platform (e2 VMs)      | Compute instances                    |
| Version Control      | Git + GitHub                        | Code management                      |

---

## Synthetic Data Design (Inspired by Google's Simula Framework)

The data generator doesn't just produce random transactions. It uses a taxonomy-driven approach
inspired by [Google's Simula framework](https://research.google/blog/designing-synthetic-datasets-for-the-real-world-mechanism-design-and-reasoning-from-first-principles/):

### Fraud Taxonomy

```
Fraud Types
├── Card-Not-Present (CNP) Fraud
│   ├── Stolen card details used online
│   ├── Small test transactions followed by large ones
│   └── Multiple cards, single shipping address
├── Account Takeover
│   ├── Sudden change in spending pattern
│   ├── New device + high-value purchase
│   └── Password reset followed by transaction
├── Geographic Anomaly
│   ├── Two transactions far apart within minutes
│   ├── Transaction from unusual country
│   └── VPN/proxy indicators
├── Velocity Abuse
│   ├── Rapid-fire small transactions
│   ├── Multiple merchants in short window
│   └── Card testing patterns (small amounts)
└── Friendly Fraud
    ├── Legitimate-looking but disputed
    ├── High-value electronics purchases
    └── Chargeback patterns
```

### Complexity Levels

- **Easy**: Clear-cut fraud (e.g., $10,000 transaction at 3 AM from a new country)
- **Medium**: Requires multiple signals (e.g., slightly elevated amount + unusual merchant + odd hour)
- **Hard**: Subtle patterns that need historical context (e.g., gradual spending increase over weeks)

---

## Transaction Schema

Each generated transaction contains:

```json
{
  "transaction_id": "txn_a1b2c3d4",
  "timestamp": "2026-04-19T14:23:45.123Z",
  "card_id": "card_00001",
  "card_holder": "John Doe",
  "merchant_name": "Amazon",
  "merchant_category": "online_retail",
  "amount": 249.99,
  "currency": "USD",
  "location_lat": 37.7749,
  "location_lon": -122.4194,
  "city": "San Francisco",
  "country": "US",
  "is_online": true,
  "device_id": "device_x1y2",
  "is_fraud": false,
  "fraud_type": null,
  "fraud_confidence": 0.0
}
```

---

## Fraud Detection Methods

### 1. Rule-Based Detection
- Transaction amount > 3x user's average
- More than 5 transactions within 10 minutes
- Two transactions > 500km apart within 30 minutes
- Transaction between 1 AM – 5 AM in cardholder's timezone + amount > $500

### 2. Statistical Detection (Z-Score)
- Flag transactions where the amount Z-score > 3 compared to the user's history
- Rolling window statistics (mean, std dev) per card_id

### 3. Machine Learning (Isolation Forest)
- Train on normal transaction features
- Flag outliers in multi-dimensional space (amount, frequency, time-of-day, merchant category)

---

## Project Structure

```
spark-fraud-detection/
├── README.md                          # This file
├── NOTES.md                           # Setup steps & learnings
├── data-generator/
│   ├── requirements.txt               # Python dependencies
│   ├── generator.py                   # Main data generation script
│   ├── config.py                      # Configuration (rates, Pub/Sub topic, etc.)
│   └── schemas/
│       └── transaction_schema.py      # Transaction data models
├── spark-processor/
│   ├── requirements.txt               # PySpark dependencies
│   ├── fraud_detector.py              # Spark Structured Streaming job
│   └── config.py                      # Spark & ClickHouse config
├── clickhouse/
│   └── schema.sql                     # ClickHouse table definitions
├── grafana/
│   └── dashboard.json                 # Grafana dashboard export
├── scripts/
│   ├── setup-generator-server.sh      # Server 1 setup automation
│   ├── setup-spark-server.sh          # Server 2 setup automation
│   └── setup-clickhouse.sh            # ClickHouse table creation
└── docs/
    └── architecture.md                # Detailed architecture notes
```

---

## GCP Resources Used

| Resource                  | Name                        | Region       | Cost Estimate   |
|---------------------------|-----------------------------|--------------|-----------------|
| VM Instance (Server 1)   | data-generator              | asia-south1  | ~$25/month      |
| VM Instance (Server 2)   | spark-processor             | asia-south1  | ~$100/month     |
| Pub/Sub Topic             | transactions-stream         | -            | Free tier       |
| GCS Bucket                | spark-fraud-*-data          | asia-south1  | ~$1–2/month     |
| ClickHouse Cloud          | Free tier cluster           | -            | Free            |
| **Total**                 |                             |              | **~$127/month** |

Budget: $300 GCP Free Trial Credit (valid 90 days)

---

## How to Run

> Detailed setup instructions are in [NOTES.md](./NOTES.md)

### Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/<your-username>/spark-fraud-detection.git

# 2. Set up Server 1 (data generator)
# SSH into your GCP VM and run:
bash scripts/setup-generator-server.sh

# 3. Set up Server 2 (Spark processor)
# SSH into your GCP VM and run:
bash scripts/setup-spark-server.sh

# 4. Set up ClickHouse tables
bash scripts/setup-clickhouse.sh

# 5. Start the data generator
cd data-generator && python generator.py

# 6. Start the Spark streaming job
cd spark-processor && spark-submit fraud_detector.py

# 7. Open Grafana dashboard at http://<server-2-ip>:3000
```

---

## Key Learnings

- Real-time streaming architecture with Pub/Sub + Spark Structured Streaming
- Synthetic data generation using taxonomy-driven design (inspired by Google's Simula)
- GCP infrastructure setup — VMs, networking, APIs, billing management
- ClickHouse as an analytical database for high-speed aggregations
- Grafana dashboarding connected to ClickHouse
- Production workflow: local development → Git → server deployment

---

## License

MIT
