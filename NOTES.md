# NOTES — Setup Steps, Commands & Learnings

> Personal notes for setting up the Spark Fraud Detection project from scratch.
> Follow these steps in order if you ever need to rebuild everything.

---

## Phase 0: GCP Account Setup

### Creating a GCP Account with Free Credits

1. Go to [cloud.google.com/free](https://cloud.google.com/free)
2. Click "Get started for free"
3. Sign in with your Google account
4. Add payment method (credit card or UPI mandate for India)
5. For India: GCP may require a one-time prepayment of ₹1,000 to activate the billing account
6. Once payment is verified, you get **$300 in free credits valid for 90 days**

### Finding Your Credits

- Go to: **Billing → Click your Billing Account → Overview**
- The credit balance and expiry date appear on the Overview page
- Alternatively, look for "Credit Details" link on the billing overview

### Key Billing Concepts

- **Organization**: Top-level container (like a company). You may already have one (e.g., `yourname-org`). Don't need to create a new one.
- **Project**: Where all resources live (VMs, Pub/Sub, storage). All billing is per-project. One project = one isolated environment.
- **Billing Account**: Where the $300 credit lives. Link it to your project.
- **Parent Resource**: Just means "where does this project sit in the hierarchy" — select your organization or "No organization". Not a big deal for personal projects.

### Cost Safety: Setting Up Billing Alerts

**DO THIS BEFORE CREATING ANY RESOURCES.**

1. Go to **Billing → Budgets & Alerts → Create Budget**
2. Budget name: `spark-project-limit`
3. Scope: Select your project
4. Budget amount: **$250** (keeps $50 as safety buffer)
5. Alert thresholds: **50%, 75%, 90%**
6. Enable email notifications
7. Done — you'll get emails when you're approaching your limit

### Cost-Saving Tips

- **Stop instances** when not working — stopped VMs cost $0 for compute (only ~$0.04/day for disk)
- **Delete instances** when project is done — $0 ongoing cost
- **Check billing dashboard** every few days — it updates with a few hours delay
- **GCP won't charge you beyond credits** if you're on the Free Trial (account auto-closes)
- **Estimated burn rate**: Both servers running = ~$4–5/day. At 8 hours/day, roughly $60–75/month.

---

## Phase 1: GCP Project & Infrastructure Setup

### Step 1 — Create the Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top
3. Click **"New Project"**
4. Project name: `spark-fraud-detection`
5. Billing account: Select the one with your $300 credit (probably "My Billing Account")
6. Organization: Your existing org or "No organization"
7. Click **Create**, then select it as your active project

### Step 2 — Enable APIs

Search for each in the GCP console search bar and click **Enable**:

1. **Compute Engine API** (takes 1–2 min to provision)
2. **Cloud Pub/Sub API**
3. **Cloud Storage** (usually enabled by default)

## Why We Need Google Cloud Storage (GCS)

### The Bookmark Analogy

GCS acts as a **ledger/bookmark** for Spark. It does NOT store any transaction data.

Think of it like reading a long book over multiple days:
- **Without a bookmark**: You fall asleep at page 247, wake up, and have no idea where you stopped. 
  Start over from page 1? Guess and risk missing pages?
- **With a bookmark**: You marked page 247 before sleeping. Wake up, open to the bookmark, continue. 
  No pages missed, no pages re-read.

### What Actually Happens in Our Project

**Without GCS checkpoint:**
10:00 AM — Generator sends transactions #1 to #5000 through Pub/Sub
10:01 AM — Spark processes #1 to #3000, writes results to ClickHouse
10:02 AM — Spark crashes (out of memory, network issue, etc.)
10:03 AM — Spark restarts → "Where was I?" → NO IDEA
Option A: Reprocess from #1 → duplicates in ClickHouse (BAD)
Option B: Start from #5001 → transactions #3001-5000 LOST forever (BAD)

**With GCS checkpoint:**
10:00 AM — Generator sends transactions #1 to #5000 through Pub/Sub
10:01 AM — Spark processes #1 to #3000, writes results to ClickHouse
Spark writes to GCS: "Last processed: #3000" (tiny file, few KB)
10:02 AM — Spark crashes
10:03 AM — Spark restarts → reads GCS → "Last checkpoint: #3000"
Resumes from #3001 → no duplicates, no lost data (PERFECT)

### What's Actually Stored in GCS
gs://spark-fraud-yourname-data/
└── checkpoints/
├── offsets/       → which Pub/Sub messages were read (few bytes each)
├── commits/       → which batches were fully processed (few bytes each)
└── metadata       → stream query info (few bytes)

### Step 3 — Create Pub/Sub Topic

1. Hamburger menu ☰ → **Pub/Sub** → **Topics**
2. Click **"Create Topic"**
3. Topic ID: `transactions-stream`
4. ✅ Check "Add a default subscription"
5. Click **Create**

> **What is Pub/Sub?**
> It's a managed message queue. Your data generator "publishes" messages to a topic,
> and your Spark job "subscribes" to read them. Like a mailbox — generator drops letters in,
> Spark picks them up. Google manages all the infrastructure.
> Pub/Sub is the location where the messages wait as if they are in mailbox, until the downstream service picks it up
> We require such system because the speed at which the upstream system produces messages can be higher than the consumption by the downstream system or the downstream system may crash so we need such system where the messages can be queued for consumption
> It has three core concepts --> Topic the Mailbox, Subscription the recipients address and Message the letter

> Topic --> The Mailbox --> A topic is a named channel where messages are sent. 
>>Topic: "transactions-stream"     ← all transaction messages go here
>>Topic: "fraud-alerts"            ← all fraud alert messages go here
>>Topic: "system-logs"             ← all log messages go here
> The publisher (our generator) doesn't know or care who reads the messages. It just drops them into the topic. 
> This is the "Pub" part — Publish.

> Subscription --> The Recipients --> A subscription is like registering yourself as a recipient for a specific mailbox. 
> It says "I want to receive messages from this topic."
> Topic: "transactions-stream"
>    │
>    ├── Subscription: "spark-subscription"     ← Spark reads from here
>    ├── Subscription: "logging-subscription"   ← a logging service reads from here
>    └── Subscription: "backup-subscription"    ← a backup service reads from here

> This is the "Sub" part — Subscribe. Each subscription gets its own copy of every message. So if three services subscribe, each one gets all the messages independently. They don't interfere with each other.

## Pub/Sub Core Concept (In My Words)

**Topic** = A mailbox where raw, rich data is dropped by the publisher (data generator). 
The richer the data, the more useful it is — because you can never add fields after publishing. 
Design the message to serve multiple use cases from day one.

**Subscription** = A subscriber registered to receive data from a topic. Each subscription gets 
its own independent copy of every message. Subscribers don't know about each other, don't wait 
for each other, and don't compete for messages.

**One Topic → Many Subscriptions (one-to-many):**
The same transaction data can feed fraud detection, loan eligibility, credit risk scoring, and 
customer segmentation — all simultaneously, all independently.

**Each subscriber cherry-picks what it needs:**
- Fraud team looks at: amount, location, velocity, time
- Loan team looks at: income, EMI burden, credit utilization
- Risk team looks at: default history, debt ratio, spending patterns

They all receive the same message but extract different fields based on their use case.

**Key rule:** Make the publisher data as rich as possible. Subscribers can always ignore fields 
they don't need, but they can never access fields that were never published.

> Finally we have Message --> The Letter
> A message is the actual data being sent. In our case, each message is a JSON object representing one transaction:
> {
>  "transaction_id": "txn_a1b2c3d4",
>  "card_id": "card_00001",
>  "amount": 249.99,
>  "merchant": "Amazon",
>  "is_fraud": false
>}
> Every message will have data, attributes, message id, and publish time

STEP 1: Generator creates a fake transaction
        {"transaction_id": "txn_001", "amount": 50.00, ...}

STEP 2: Generator PUBLISHES it to the topic
        generator.py → publish("transactions-stream", message)

STEP 3: Pub/Sub receives the message and stores it
        The message sits in the topic, waiting to be picked up
        (messages are retained for 7 days by default)

STEP 4: Spark has a SUBSCRIPTION to this topic
        Spark continuously asks: "Any new messages?"
        This is called "pulling" messages

STEP 5: Pub/Sub delivers the message to Spark
        Spark receives: {"transaction_id": "txn_001", "amount": 50.00, ...}

STEP 6: Spark processes it (fraud detection) and sends an ACK
        ACK = "acknowledgement" = "I got it, you can remove it from my queue"

STEP 7: Pub/Sub removes the message from that subscription's queue
        (other subscriptions still have their copy if they haven't ACK'd)

> **Why Pub/Sub over Kafka?**
> Kafka is powerful but needs ZooKeeper/KRaft, broker config, and eats lots of RAM.
> Pub/Sub is zero-infrastructure — create a topic and start publishing. You get the same
> streaming semantics without the operational overhead. Free tier = 10GB/month.

### Step 4 — Create GCS Bucket

1. Hamburger menu ☰ → **Cloud Storage** → **Buckets**
2. Click **"Create"**
3. Bucket name: `spark-fraud-<your-initials>-data` (globally unique)
4. Region: `asia-south1 (Mumbai)`
5. Storage class: Standard
6. Click **Create**

> **What's the bucket for?**
> Spark Structured Streaming needs a "checkpoint location" to track what messages it has
> already processed. If Spark crashes and restarts, it picks up where it left off using
> these checkpoints. The GCS bucket stores these checkpoints.

---

## Phase 2: Data Generator Server (Server 1)

### Step 5 — Create the VM

1. Go to **Compute Engine → VM Instances → Create Instance**
2. Settings:
   - Name: `data-generator`
   - Region: `asia-south1` (Mumbai)
   - Zone: `asia-south1-a`
   - Machine type: `e2-medium` (2 vCPU, 4 GB RAM)
   - Boot disk: Click **Change**
     - OS: Ubuntu
     - Version: Ubuntu 22.04 LTS
     - Size: 20 GB
     - Disk type: Standard persistent disk
   - Firewall: ✅ Allow HTTP, ✅ Allow HTTPS
3. Click **Create**

> **Machine types explained:**
> - `e2-medium` = 2 vCPU, 4 GB RAM (~$25/month). Enough for a Python script that generates data.
> - `e2-standard-4` = 4 vCPU, 16 GB RAM (~$100/month). Needed for Spark which is memory-hungry.
> - These are GCP names. AWS equivalents would be `t3.medium` and `m5.xlarge`.

### Step 6 — SSH and Install Dependencies

Click **SSH** button next to your instance in the Compute Engine dashboard (opens browser terminal).

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.11 and pip
sudo apt install -y python3.11 python3-pip python3.11-venv git

# Create project directory
mkdir -p ~/spark-fraud-detection/data-generator
cd ~/spark-fraud-detection

# Clone your repo (replace with your GitHub URL)
git clone https://github.com/<your-username>/spark-fraud-detection.git .

# Or if already cloned, pull latest
# git pull origin main

# Set up virtual environment
cd data-generator
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### Step 7 — Configure GCP Authentication on the VM

The VM needs permission to publish to Pub/Sub. Since it's a GCP VM, it uses a "service account" automatically.

```bash
# Verify the VM can access GCP services
gcloud auth list

# Set the project
gcloud config set project spark-fraud-detection

# Test Pub/Sub access (should return the topic info)
gcloud pubsub topics describe transactions-stream
```

> **If you get permission errors:**
> Go to GCP Console → IAM & Admin → IAM → Find the Compute Engine default service account
> → Make sure it has "Pub/Sub Publisher" role.

### Step 8 — Run the Data Generator

```bash
cd ~/spark-fraud-detection/data-generator
source venv/bin/activate
python generator.py
```

> **Verify messages are flowing:**
> Go to GCP Console → Pub/Sub → Topics → transactions-stream
> Click on the "Messages" tab → Pull → you should see your JSON transaction messages.

---

## Phase 3: Spark + Kafka Processing Server (Server 2)

> **Architecture Decision: Why Kafka Instead of Pub/Sub for Spark?**
>
> We originally planned to have Spark read directly from Pub/Sub. But Google Cloud
> Pub/Sub (standard) does NOT have a native Spark Structured Streaming connector.
> Pub/Sub Lite had one, but was shut down in March 2026.
>
> Our options were:
> 1. Stay with Pub/Sub, use a Python pull-loop to feed Spark (hacky, loses streaming features)
> 2. Use Google Managed Kafka (costs money, not free tier)
> 3. Self-host Kafka on the spark-processor VM (free, native Spark connector, industry standard)
>
> We chose **Option 3** because:
> - Spark has a first-class Kafka connector (`spark-sql-kafka`) — proper streaming with
>   watermarks, stateful processing, and checkpointing all work natively
> - Kafka is THE industry standard for streaming — every data engineering job mentions it
> - It's free — runs on our existing 16 GB VM alongside Spark
> - KRaft mode (Kafka 3.x+) eliminated the ZooKeeper dependency, making self-hosting simple
>
> **The updated pipeline:**
> ```
> Generator (VM1) → Kafka (on VM2) → Spark (on VM2) → ClickHouse → Grafana
> ```
> The generator now publishes directly to Kafka instead of Pub/Sub.
> Pub/Sub topic still exists but is no longer in the main data path.

---

### Kafka Concepts (My Understanding)

> **What is Kafka?**
> Apache Kafka is a distributed event streaming platform. Think of it as a high-performance
> message queue that stores messages durably on disk (not just in memory like some queues).
> It was originally built by LinkedIn to handle their activity stream data.

> **Kafka vs Pub/Sub — The Differences That Matter:**
>
> | Concept | Pub/Sub | Kafka |
> |---------|---------|-------|
> | Message storage | Google manages it, 7-day retention | You manage it, configurable retention |
> | Consumer model | Pull + ACK (message removed after ACK) | Offset-based (consumer tracks position, messages stay) |
> | Replay | Can't re-read acknowledged messages | Can re-read from any point (rewind the offset) |
> | Partitioning | Google handles it | You choose partition count + partition key |
> | Infrastructure | Fully managed (zero setup) | Self-managed (install + configure) |
> | Spark support | No native connector | Native connector (`spark-sql-kafka`) |
>
> The biggest conceptual difference is **offset-based consumption**:
>
> **Pub/Sub model (mailbox):**
> ```
> Message arrives → you pick it up → you ACK it → message is GONE from your queue
> If you want to re-read it, too bad — it's been acknowledged and removed
> ```
>
> **Kafka model (book with a bookmark):**
> ```
> Message arrives → stored at position #47 in the topic
> You read position #47 → your bookmark moves to #48
> Want to re-read #47? Just move your bookmark back to #47
> The message is still there (until retention period expires)
> ```
>
> This is why Kafka is better for Spark streaming — if Spark crashes at position #3000,
> it restarts and moves the bookmark back to #3000. No messages lost, no duplicates.
> This is exactly what GCS checkpoints were supposed to do for Pub/Sub, but Kafka
> handles it natively and more reliably.

> **Core Kafka Concepts:**
>
> **Broker** = The Kafka server process. In our case, one broker running on the
> spark-processor VM. In production, you'd have 3+ brokers for redundancy.
>
> **Topic** = A named stream of messages (like Pub/Sub topic). Our topic: `transactions`.
> Messages are appended to the end of the topic and stay there for the retention period.
>
> **Partition** = A topic is split into partitions for parallelism. Each partition is an
> ordered, immutable sequence of messages. We'll use 3 partitions (enough for our volume).
> Messages within a partition are ordered; messages across partitions are NOT ordered.
>
> **Offset** = The position number of a message within a partition. Offset 0 is the first
> message, offset 1 is the second, etc. Consumers track their offset to know where they
> left off.
>
> **Producer** = Something that writes messages to a topic (our data generator).
>
> **Consumer / Consumer Group** = Something that reads messages from a topic (our Spark job).
> A consumer group is a set of consumers that share the work of reading partitions.
> Each partition is read by exactly one consumer in the group.
>
> **KRaft mode** = Kafka's newer consensus protocol that replaces ZooKeeper.
> ZooKeeper was a separate service that Kafka needed for cluster coordination.
> KRaft builds this into Kafka itself, so we only need to run one process.
>
> **Visual:**
> ```
> Producer (generator.py)
>       │
>       ▼
> ┌─────────────────────────────────────────┐
> │  Topic: "transactions"                  │
> │  ┌──────────────┐                       │
> │  │ Partition 0  │  msg0, msg3, msg6...  │
> │  └──────────────┘                       │
> │  ┌──────────────┐                       │
> │  │ Partition 1  │  msg1, msg4, msg7...  │
> │  └──────────────┘                       │
> │  ┌──────────────┐                       │
> │  │ Partition 2  │  msg2, msg5, msg8...  │
> │  └──────────────┘                       │
> └─────────────────────────────────────────┘
>       │
>       ▼
> Consumer Group: "spark-fraud-processor"
>   Consumer 1 reads Partition 0
>   Consumer 2 reads Partition 1
>   Consumer 3 reads Partition 2
> ```

---

### Step 9 — Create the VM

1. Go to **Compute Engine → Create Instance**
2. Settings:
   - Name: `spark-processor`
   - Region: `asia-south1` (Mumbai)
   - Zone: `asia-south1-a`
   - Machine type: `e2-standard-4` (4 vCPU, 16 GB RAM)
   - Boot disk: Ubuntu 22.04 LTS, **30 GB**, Standard persistent disk
   - Identity and API access: **Allow full access to all Cloud APIs**
   - Firewall: ✅ Allow HTTP, ✅ Allow HTTPS
3. Click **Create**

### Step 10 — SSH and Install Java + Spark

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Java 11 (required by both Spark and Kafka)
sudo apt install -y openjdk-11-jdk

# Verify Java
java -version
# Should show: openjdk version "11.x.x"

# Download and install Spark 3.5.8
cd /opt
sudo wget https://dlcdn.apache.org/spark/spark-3.5.8/spark-3.5.8-bin-hadoop3.tgz
sudo tar xzf spark-3.5.8-bin-hadoop3.tgz
sudo mv spark-3.5.8-bin-hadoop3 /opt/spark

# Set environment variables
echo 'export SPARK_HOME=/opt/spark' >> ~/.bashrc
echo 'export PATH=$PATH:$SPARK_HOME/bin:$SPARK_HOME/sbin' >> ~/.bashrc
echo 'export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64' >> ~/.bashrc
source ~/.bashrc

# Verify Spark
spark-submit --version
```

### Step 11 — Install Kafka (KRaft mode, no ZooKeeper)

```bash
# Download Kafka 3.7.x (uses KRaft mode by default)
cd /opt
sudo wget https://dlcdn.apache.org/kafka/3.7.2/kafka_2.13-3.7.2.tgz
sudo tar xzf kafka_2.13-3.7.2.tgz
sudo mv kafka_2.13-3.7.2 /opt/kafka

# Set environment variables
echo 'export KAFKA_HOME=/opt/kafka' >> ~/.bashrc
echo 'export PATH=$PATH:$KAFKA_HOME/bin' >> ~/.bashrc
source ~/.bashrc

# Generate a unique cluster ID for KRaft
KAFKA_CLUSTER_ID=$(/opt/kafka/bin/kafka-storage.sh random-uuid)

# Format the Kafka storage directory
/opt/kafka/bin/kafka-storage.sh format -t $KAFKA_CLUSTER_ID \
    -c /opt/kafka/config/kraft/server.properties

# Start Kafka (runs in background)
/opt/kafka/bin/kafka-server-start.sh -daemon /opt/kafka/config/kraft/server.properties

# Wait a few seconds, then verify Kafka is running
sleep 5
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
# Should return empty (no topics yet) but no errors = Kafka is running
```

### Step 12 — Create the Kafka Topic

```bash
# Create the transactions topic with 3 partitions
/opt/kafka/bin/kafka-topics.sh --create \
    --topic transactions \
    --bootstrap-server localhost:9092 \
    --partitions 3 \
    --replication-factor 1

# Verify it exists
/opt/kafka/bin/kafka-topics.sh --describe \
    --topic transactions \
    --bootstrap-server localhost:9092
```

> **Why 3 partitions?**
> Each partition can be read by one Spark task in parallel. 3 partitions = 3 parallel
> readers. For our volume (~1,000 txn/hr), even 1 partition would be enough, but 3
> gives us some parallelism for faster processing and is more realistic.
>
> **Why replication-factor 1?**
> We only have one broker (one VM). Replication requires multiple brokers.
> In production you'd use 3 brokers with replication-factor 3 for fault tolerance.

### Step 13 — Install Python, Clone Repo, Set Up Environments

```bash
# Install Python
sudo apt install -y python3.11 python3-pip python3.11-venv git

# Clone repo
cd ~
git clone https://github.com/Amar2210/spark-fraud-detection.git

# Set up Spark processor environment
cd ~/spark-fraud-detection/spark-processor
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install pyspark==3.5.8
pip install -r requirements.txt
```

### Step 14 — Run the Spark Streaming Job

```bash
cd ~/spark-fraud-detection/spark-processor
source venv/bin/activate

spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8 \
  fraud_detector.py
```

> **What does `--packages` do?**
> It tells Spark to download the Kafka connector JAR from Maven Central
> and add it to the classpath. This JAR contains the code that lets Spark
> do `readStream.format("kafka")`. First run downloads it; subsequent runs use cache.

---

## Phase 4: ClickHouse + Grafana

### Step 12 — Set Up ClickHouse Cloud

1. Go to [clickhouse.cloud](https://clickhouse.cloud)
2. Sign up / log in to your free tier account
3. Create a new service (select the free tier)
4. Note down: **host**, **port**, **username**, **password**
5. Open the SQL Console

### Step 13 — Create Tables

Run the SQL from `clickhouse/schema.sql` in the ClickHouse SQL Console.

> **Why ClickHouse?**
> It's a column-oriented analytical database designed for fast aggregation queries.
> A query like "total fraud by category in the last hour" that might take seconds in
> PostgreSQL runs in milliseconds in ClickHouse. Perfect for real-time dashboards.

### Step 14 — Set Up Grafana

```bash
# On Server 2 (spark-processor), install Grafana
sudo apt install -y adduser libfontconfig1
wget https://dl.grafana.com/oss/release/grafana_10.4.1_amd64.deb
sudo dpkg -i grafana_10.4.1_amd64.deb

# Start Grafana
sudo systemctl start grafana-server
sudo systemctl enable grafana-server

# Grafana runs on port 3000
# Access it at: http://<server-2-external-ip>:3000
# Default login: admin / admin (change on first login)
```

> **Connecting Grafana to ClickHouse:**
> 1. Go to Grafana → Settings (gear icon) → Data Sources → Add data source
> 2. Search for "ClickHouse"
> 3. Enter your ClickHouse Cloud host, port, username, password
> 4. Click "Save & Test"
>
> **Note:** You may need to install the ClickHouse Grafana plugin first:
> ```bash
> sudo grafana-cli plugins install grafana-clickhouse-datasource
> sudo systemctl restart grafana-server
> ```

---

## Phase 5: Polish & Shutdown

### Step 15 — Document and Push to GitHub

```bash
# On your local machine
cd spark-fraud-detection
git add .
git commit -m "Complete project: streaming fraud detection pipeline"
git push origin main
```

### Step 16 — Shut Down GCP Resources

1. **Stop VMs** (if you might come back):
   - Compute Engine → Select both VMs → Click **Stop**
   - Cost: ~$0.04/day per disk (negligible)

2. **Delete everything** (when project is fully done):
   - Delete VMs: Compute Engine → Select VMs → Delete
   - Delete Pub/Sub: Pub/Sub → Topics → Delete `transactions-stream`
   - Delete GCS Bucket: Cloud Storage → Select bucket → Delete
   - Verify: Billing dashboard should show $0/day after deletion

---

## Useful Commands Reference

```bash
# SSH into GCP VM (from local terminal, alternative to browser SSH)
gcloud compute ssh data-generator --zone=asia-south1-a
gcloud compute ssh spark-processor --zone=asia-south1-a

# Start/stop VMs from terminal
gcloud compute instances start data-generator --zone=asia-south1-a
gcloud compute instances stop data-generator --zone=asia-south1-a

# Check Pub/Sub messages (legacy, before Kafka migration)
gcloud pubsub subscriptions pull transactions-stream-sub --limit=5

# Kafka commands (run on spark-processor VM)
# Start Kafka
/opt/kafka/bin/kafka-server-start.sh -daemon /opt/kafka/config/kraft/server.properties

# Stop Kafka
/opt/kafka/bin/kafka-server-stop.sh

# List all topics
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

# Describe a topic (see partitions, offsets)
/opt/kafka/bin/kafka-topics.sh --describe --topic transactions --bootstrap-server localhost:9092

# Read messages from topic (console consumer — for debugging)
/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
    --topic transactions --from-beginning --max-messages 5

# Check consumer group offsets (see how far Spark has read)
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
    --group spark-fraud-processor --describe

# Monitor costs
gcloud billing accounts list
gcloud billing projects describe spark-fraud-detection

# Git workflow: local → GitHub → server
# On local machine:
git add . && git commit -m "update generator" && git push origin main
# On server:
cd ~/spark-fraud-detection && git pull origin main
```

---

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| "Permission denied" on Pub/Sub | Add "Pub/Sub Publisher" role to the VM's service account in IAM |
| Spark out of memory | Increase `spark.driver.memory` and `spark.executor.memory` in spark-submit |
| Can't SSH into VM | Check firewall rules — make sure port 22 is open |
| ClickHouse connection refused | Whitelist your Server 2's external IP in ClickHouse Cloud settings |
| Grafana not loading | Open port 3000 in GCP firewall rules for Server 2 |
| VM won't start after stopping | Check if billing account is still active and has credits |
| Kafka won't start | Check Java is installed (`java -version`). Check logs: `cat /opt/kafka/logs/server.log` |
| Kafka "connection refused" on 9092 | Kafka isn't running. Start it: `/opt/kafka/bin/kafka-server-start.sh -daemon ...` |
| Spark can't connect to Kafka | Make sure Kafka is running on same VM. Check `--packages` flag includes kafka connector |
| Generator can't publish to Kafka | Verify topic exists: `kafka-topics.sh --list`. Check Kafka is on port 9092 |
| ACCESS_TOKEN_SCOPE_INSUFFICIENT | Stop VM → Edit → Change scopes to "Allow full access to all Cloud APIs" → Start |

---

## Learning Notes

> Add personal notes and "aha moments" below as you build the project.

### GCP Concepts Learned
- Organization → Project → Resources hierarchy
- Billing accounts are separate from projects and can be linked/unlinked
- e2 machine types are GCP's cost-optimized VMs (AWS equivalent: t3 family)
- Stopped VMs = no compute cost, only disk cost (~$0.04/day for 20GB)

### Pub/Sub vs Kafka
- Pub/Sub = managed, zero infrastructure, great for GCP-native projects
- Kafka = self-managed, more configurable, better for multi-cloud or on-premise
- For portfolio projects, Pub/Sub saves days of configuration time
- **BUT** Pub/Sub has no native Spark Structured Streaming connector (Pub/Sub Lite had one, shut down March 2026)
- We started with Pub/Sub (tested it, confirmed it works) then migrated to Kafka for the Spark integration
- Kafka runs on the spark-processor VM in KRaft mode (no ZooKeeper needed)
- Kafka uses ~2-3 GB RAM — fits comfortably alongside Spark on 16 GB VM

### Why Kafka Won (Architecture Decision)
- Spark has a native Kafka connector (`spark-sql-kafka-0-10`) — proper streaming
- Kafka's offset-based model: consumer tracks position, can rewind and replay
- Pub/Sub's ACK model: once acknowledged, message is gone — no replay
- Kafka offsets + Spark checkpoints = exactly-once semantics naturally
- "Kafka → Spark Streaming" is the most recognized pattern in data engineering interviews

### Kafka Key Concepts Learned
- **Broker**: the Kafka server process (we run 1, production uses 3+)
- **Topic**: named stream of messages (`transactions`), like Pub/Sub topic
- **Partition**: topic split for parallelism; messages ordered within partition, not across
- **Offset**: position number within a partition (0, 1, 2...) — consumer's bookmark
- **Consumer Group**: set of consumers sharing the work; each partition → 1 consumer
- **KRaft**: Kafka's built-in consensus (replaced ZooKeeper in Kafka 3.x+)
- **Retention**: messages stay on disk for configurable time (default 7 days, unlike Pub/Sub where ACK removes them)

### Sync vs Async (Learned from Pub/Sub Flush Bug)
- Synchronous: do one thing, wait for it to finish, then do the next thing
- Asynchronous: fire off many things at once, collect results later
- `publisher.publish()` returns a "future" (a promise of a result that doesn't exist yet)
- `future.result()` blocks until the result actually arrives
- Our flush bug: program exited before futures resolved → messages lost
- Fix: collect all futures, then wait for each one before exiting

### Batching & Flushing (Learned from Generator)
- Batching: collect N messages in a pile, send them all at once (1 network trip instead of N)
- Flushing: the act of sending the accumulated batch to the destination
- If batch_size=50 and you only generate 10, flush() must be called manually before exit
- Every API call has network overhead: TCP handshake (~30ms) + TLS (~50ms) + send + confirm
- Batching amortizes this overhead across many messages

### Synthetic Data Design (from Google's Simula paper)
- Don't generate random data — design a taxonomy of what you're simulating
- Control 4 axes independently: global diversity, local diversity, complexity, quality
- Better data > more data (quality scales better than quantity)
- Embed realistic patterns (geographic impossibility, velocity abuse, etc.)
