"""
Data Generator — Produces realistic synthetic credit card transactions.

This script runs continuously on a GCP VM, generating transactions at a
rate that follows real-world patterns (busy during day, quiet at night,
occasional burst events). Transactions are published to stdout (local mode),
a CSV file, or Google Cloud Pub/Sub.

Architecture:
  1. Create 25,000 CardHolder objects (persistent identities)
  2. Enter main loop:
     a. Check current hour → get rate multiplier from traffic curve
     b. Apply random jitter + check for burst events
     c. Calculate sleep time between transactions
     d. Pick a random cardholder
     e. Roll dice: fraud or normal? (4% fraud rate)
     f. Generate the transaction
     g. Publish it (console / CSV / Pub/Sub)
     h. Sleep until next transaction

Usage:
  python generator.py                    # local mode, prints to console
  python generator.py --mode csv         # writes to output/transactions.csv
  python generator.py --mode pubsub      # publishes to Pub/Sub
  python generator.py --count 100        # generate exactly 100, then stop
"""

import argparse
import json
import logging
import math
import os
import random
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from faker import Faker

from config import (
    NUM_CARDHOLDERS, TARGET_DAILY_TRANSACTIONS, FRAUD_RATE,
    GCP_PROJECT_ID, PUBSUB_TOPIC, PUBSUB_BATCH_SIZE,
    CSV_OUTPUT_PATH, MAX_RECENT_TRANSACTIONS, MAX_KNOWN_MERCHANTS,
    LOG_EVERY_N, LOG_LEVEL,
)
from schemas.transaction_schema import (
    MERCHANT_CATEGORIES, INDIAN_CITIES, FRAUD_TAXONOMY, FRAUD_COMPLEXITY,
    CARDHOLDER_PROFILES, DEVICE_TYPES, CHANNELS,
    HOURLY_RATE_MULTIPLIERS, BURST_CONFIG,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Indian locale for realistic names like "Ravi Sharma", "Priya Patel"
fake = Faker("en_IN")
Faker.seed(42)  # Reproducible names across runs
random.seed(42)

# Indian Standard Time offset (+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# CARDHOLDER CLASS
# =============================================================================

class CardHolder:
    """
    Represents a persistent person with a credit/debit card.

    Each CardHolder has a fixed identity (name, income, home city) and a
    small rolling history of recent transactions. The identity never changes
    during the generator's lifetime. The history is used INTERNALLY by the
    generator to craft realistic fraud patterns — it is NOT included in
    the output JSON.

    Memory per cardholder: ~3 KB (fixed, doesn't grow over time)
      - Identity fields: ~500 bytes
      - recent_transactions deque(maxlen=10): ~2,000 bytes
      - known_merchants set (capped at 20): ~500 bytes
    Total for 25,000 cardholders: ~75 MB
    """

    def __init__(self, card_id: str):
        self.card_id = card_id

        # --- Assign a profile based on weighted distribution ---
        # This determines income range, card type, spending habits, etc.
        profile_name = random.choices(
            list(CARDHOLDER_PROFILES.keys()),
            weights=[p["weight"] for p in CARDHOLDER_PROFILES.values()],
            k=1,
        )[0]
        profile = CARDHOLDER_PROFILES[profile_name]
        self.profile_name = profile_name

        # --- Identity (fixed for lifetime) ---
        self.card_holder = fake.name()
        self.card_type = random.choice(profile["card_types"])

        # Home city — weighted by city population/activity
        city_names = list(INDIAN_CITIES.keys())
        city_weights = [INDIAN_CITIES[c]["weight"] for c in city_names]
        self.home_city = random.choices(city_names, weights=city_weights, k=1)[0]

        # --- Financial profile (fixed for lifetime) ---
        inc_lo, inc_hi = profile["monthly_income_range"]
        self.monthly_income = round(random.uniform(inc_lo, inc_hi))

        lim_lo, lim_hi = profile["card_limit_range"]
        self.card_limit = round(random.uniform(lim_lo, lim_hi))

        self.card_age_months = random.randint(1, 120)  # 1 month to 10 years

        spend_lo, spend_hi = profile["avg_monthly_spend_factor"]
        self.avg_monthly_spend = round(self.monthly_income * random.uniform(spend_lo, spend_hi))

        emi_lo, emi_hi = profile["emi_range"]
        self.active_emis = random.randint(emi_lo, emi_hi)
        # Each EMI is roughly 5-15% of income
        self.total_emi_amount = round(
            self.active_emis * self.monthly_income * random.uniform(0.05, 0.15)
        ) if self.active_emis > 0 else 0

        self.credit_utilization_pct = round(random.uniform(5.0, 85.0), 1)

        # Months since last default (0 = never defaulted, has higher weight)
        if random.random() < profile["default_probability"]:
            self.months_since_last_default = random.randint(1, 60)
        else:
            self.months_since_last_default = 0  # never defaulted

        # --- Behavioral attributes ---
        self.preferred_categories = profile["preferred_categories"]

        # Each person has 1-3 devices
        num_devices = random.randint(1, 3)
        self.devices = [f"dev_{uuid.uuid4().hex[:8]}" for _ in range(num_devices)]

        # --- Internal tracking (NOT in output) ---
        # Rolling window of last N transactions for fraud pattern crafting
        self.recent_transactions: deque = deque(maxlen=MAX_RECENT_TRANSACTIONS)

        # Set of merchants this person has used (capped)
        self.known_merchants: set = set()

    def record_transaction(self, txn: Dict):
        """
        Record a transaction in internal history.
        Called AFTER generating a transaction, so the next transaction
        can reference this one (e.g., for geographic anomaly detection).
        """
        self.recent_transactions.append({
            "city": txn["city"],
            "lat": txn["location_lat"],
            "lon": txn["location_lon"],
            "time": txn["timestamp"],
            "amount": txn["amount"],
            "merchant": txn["merchant_name"],
        })

        # Track known merchants (cap the set size)
        self.known_merchants.add(txn["merchant_name"])
        if len(self.known_merchants) > MAX_KNOWN_MERCHANTS:
            # Remove a random old merchant to stay within cap
            self.known_merchants.pop()


# =============================================================================
# TRANSACTION GENERATOR
# =============================================================================

class TransactionGenerator:
    """
    Main engine that generates transactions.

    Holds all 25,000 cardholders and provides methods to generate
    normal transactions, fraudulent transactions, and manage the
    traffic rate pattern.
    """

    def __init__(self):
        logger.info(f"Initializing {NUM_CARDHOLDERS:,} cardholders...")
        self.cardholders: List[CardHolder] = [
            CardHolder(f"card_{i:05d}") for i in range(NUM_CARDHOLDERS)
        ]
        logger.info("Cardholders initialized.")

        # Stats tracking
        self.transaction_count = 0
        self.fraud_count = 0

        # Burst state
        self._burst_active = False
        self._burst_end_time: Optional[datetime] = None
        self._burst_multiplier = 1.0
        self._last_burst_check_hour = -1

        # Pre-compute city lists for weighted selection
        self._city_names = list(INDIAN_CITIES.keys())
        self._city_weights = [INDIAN_CITIES[c]["weight"] for c in self._city_names]

        # Pre-compute fraud type weights
        self._fraud_types = list(FRAUD_TAXONOMY.keys())
        self._fraud_weights = [FRAUD_TAXONOMY[f]["weight"] for f in self._fraud_types]

        # Pre-compute complexity weights
        self._complexity_levels = list(FRAUD_COMPLEXITY.keys())
        self._complexity_weights = [FRAUD_COMPLEXITY[c]["weight"] for c in self._complexity_levels]

        # Calculate base rate (transactions per hour at peak)
        # Sum of all hourly multipliers tells us the "effective hours" per day
        total_multiplier = sum(HOURLY_RATE_MULTIPLIERS.values())
        # base_rate × total_multiplier = target daily transactions
        self._base_rate_per_hour = TARGET_DAILY_TRANSACTIONS / total_multiplier
        logger.info(
            f"Base rate: {self._base_rate_per_hour:.1f} txn/hr at peak. "
            f"Target: ~{TARGET_DAILY_TRANSACTIONS:,} txn/day."
        )

    # -------------------------------------------------------------------------
    # Traffic Rate Management
    # -------------------------------------------------------------------------

    def _get_current_rate(self) -> float:
        """
        Calculate current transactions-per-hour based on:
          1. Time of day (hourly multiplier curve)
          2. Random jitter (±50%)
          3. Burst events (3-5x spike, rare)

        Returns the effective transactions per hour for right now.
        """
        now = datetime.now(IST)
        hour = now.hour

        # Layer 1: Base hourly curve
        multiplier = HOURLY_RATE_MULTIPLIERS.get(hour, 0.5)

        # Layer 2: Random jitter — makes each cycle slightly different
        jitter = random.uniform(0.5, 1.5)

        # Layer 3: Burst events — check once per hour
        if hour != self._last_burst_check_hour:
            self._last_burst_check_hour = hour
            if random.random() < BURST_CONFIG["probability_per_hour"]:
                # Start a burst!
                burst_mins = random.uniform(*BURST_CONFIG["duration_minutes"])
                self._burst_active = True
                self._burst_end_time = now + timedelta(minutes=burst_mins)
                self._burst_multiplier = random.uniform(*BURST_CONFIG["rate_multiplier"])
                logger.info(
                    f"BURST EVENT started! {self._burst_multiplier:.1f}x rate "
                    f"for {burst_mins:.0f} minutes."
                )

        # Check if burst has ended
        if self._burst_active:
            if now >= self._burst_end_time:
                self._burst_active = False
                self._burst_multiplier = 1.0
                logger.info("Burst event ended. Returning to normal rate.")

        burst_factor = self._burst_multiplier if self._burst_active else 1.0

        # Combine all layers
        effective_rate = self._base_rate_per_hour * multiplier * jitter * burst_factor
        return max(effective_rate, 1.0)  # At least 1 txn/hr even at the quietest

    def get_sleep_time(self) -> float:
        """
        Calculate how long to sleep before generating the next transaction.

        At 600 txn/hr → sleep ~6 seconds
        At 50 txn/hr  → sleep ~72 seconds
        At 2000 txn/hr (burst) → sleep ~1.8 seconds
        """
        rate = self._get_current_rate()
        base_sleep = 3600.0 / rate  # seconds between transactions
        # Add a small jitter to the sleep itself so transactions aren't perfectly spaced
        return base_sleep * random.uniform(0.7, 1.3)

    # -------------------------------------------------------------------------
    # Normal Transaction Generation
    # -------------------------------------------------------------------------

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance in km between two GPS coordinates.
        Used internally to verify geographic anomaly fraud makes sense.
        """
        R = 6371  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _pick_category_and_merchant(self, cardholder: CardHolder) -> Tuple[str, str]:
        """
        Pick a merchant category and specific merchant for a cardholder.

        70% of the time → pick from their preferred categories
        30% of the time → pick any category (people occasionally shop outside habits)
        """
        if random.random() < 0.70:
            category = random.choice(cardholder.preferred_categories)
        else:
            category = random.choice(list(MERCHANT_CATEGORIES.keys()))

        merchant = random.choice(MERCHANT_CATEGORIES[category]["merchants"])
        return category, merchant

    def _get_amount(self, category: str, cardholder: CardHolder) -> float:
        """
        Generate a realistic transaction amount based on category and income.

        Uses log-normal distribution: most transactions are small,
        occasional large ones. A student buying electronics gets a
        scaled-down amount compared to a high-income professional.
        """
        lo, hi = MERCHANT_CATEGORIES[category]["amount_range"]

        # Income scaling factor: high income → full range, student → compressed range
        # This prevents a student from buying ₹1,50,000 electronics
        income_factor = cardholder.monthly_income / 150000  # normalized to mid-high income
        income_factor = max(0.15, min(income_factor, 2.0))   # clamp between 0.15x and 2x

        # Log-normal: mean is the geometric center of the range, scaled by income
        mean_amount = math.sqrt(lo * hi) * income_factor
        # Standard deviation is 60% of mean — gives good spread
        std_amount = mean_amount * 0.6

        amount = random.lognormvariate(math.log(mean_amount), 0.5)
        amount = max(lo, min(amount, hi * income_factor))  # clamp within scaled range
        return round(amount, 2)

    def _pick_location(self, cardholder: CardHolder) -> Tuple[str, float, float]:
        """
        Pick a transaction location.

        80% of the time → home city (people mostly transact locally)
        20% of the time → random city weighted by population

        Adds slight GPS jitter (±0.01°) so not every transaction
        is at the exact city center.
        """
        if random.random() < 0.80:
            city = cardholder.home_city
        else:
            city = random.choices(self._city_names, weights=self._city_weights, k=1)[0]

        city_data = INDIAN_CITIES[city]
        lat = city_data["lat"] + random.uniform(-0.05, 0.05)
        lon = city_data["lon"] + random.uniform(-0.05, 0.05)
        return city, round(lat, 4), round(lon, 4)

    def _pick_device_and_channel(self, cardholder: CardHolder, is_online: bool) -> Tuple[str, str, str]:
        """
        Pick device type, device ID, and payment channel.

        If online → mobile/desktop/tablet
        If offline → pos_terminal
        """
        if is_online:
            device_type = random.choice(["mobile", "desktop", "tablet"])
        else:
            device_type = "pos_terminal"

        device_id = random.choice(cardholder.devices)
        channel = random.choice(CHANNELS[device_type])
        return device_id, device_type, channel

    def generate_normal_transaction(self, cardholder: CardHolder) -> Dict:
        """
        Generate a single normal (non-fraudulent) transaction.
        """
        timestamp = datetime.now(IST)
        category, merchant = self._pick_category_and_merchant(cardholder)
        amount = self._get_amount(category, cardholder)
        city, lat, lon = self._pick_location(cardholder)

        is_online = random.random() < MERCHANT_CATEGORIES[category]["online_probability"]
        device_id, device_type, channel = self._pick_device_and_channel(cardholder, is_online)

        return {
            "transaction_id": f"txn_{uuid.uuid4().hex[:12]}",
            "timestamp": timestamp.isoformat(),
            # Card & User
            "card_id": cardholder.card_id,
            "card_holder": cardholder.card_holder,
            "card_type": cardholder.card_type,
            "card_limit": cardholder.card_limit,
            "card_age_months": cardholder.card_age_months,
            # Transaction
            "amount": amount,
            "currency": "INR",
            "merchant_name": merchant,
            "merchant_category": category,
            "is_online": is_online,
            # Location
            "location_lat": lat,
            "location_lon": lon,
            "city": city,
            "country": "IN",
            # Device
            "device_id": device_id,
            "device_type": device_type,
            "channel": channel,
            # Financial Profile
            "monthly_income": cardholder.monthly_income,
            "active_emis": cardholder.active_emis,
            "total_emi_amount": cardholder.total_emi_amount,
            "credit_utilization_pct": cardholder.credit_utilization_pct,
            "months_since_last_default": cardholder.months_since_last_default,
            "avg_monthly_spend": cardholder.avg_monthly_spend,
            # Labels
            "is_fraud": False,
            "fraud_type": None,
            "fraud_confidence": 0.0,
        }

    # -------------------------------------------------------------------------
    # Fraud Transaction Generation
    # -------------------------------------------------------------------------

    def _pick_fraud_type(self) -> str:
        """Pick a fraud type based on weighted distribution."""
        return random.choices(self._fraud_types, weights=self._fraud_weights, k=1)[0]

    def _pick_complexity(self) -> Tuple[str, float]:
        """
        Pick a complexity level and confidence score.
        Returns (level_name, confidence_score).
        """
        level = random.choices(
            self._complexity_levels, weights=self._complexity_weights, k=1
        )[0]
        lo, hi = FRAUD_COMPLEXITY[level]["confidence_range"]
        confidence = round(random.uniform(lo, hi), 2)
        return level, confidence

    def generate_fraud_transaction(self, cardholder: CardHolder) -> Dict:
        """
        Generate a fraudulent transaction.

        1. Start with a normal transaction as the base
        2. Pick a fraud type
        3. Modify the transaction to match the fraud pattern
        4. Set the fraud labels

        The modifications use the cardholder's internal history to ensure
        the fraud is REALISTIC — e.g., a geographic anomaly actually places
        the transaction far from the last one, not just randomly.
        """
        # Start with a normal transaction as base
        txn = self.generate_normal_transaction(cardholder)

        # Pick fraud type and complexity
        fraud_type = self._pick_fraud_type()
        complexity, confidence = self._pick_complexity()

        # Apply fraud-specific modifications
        if fraud_type == "card_not_present":
            txn = self._apply_cnp_fraud(txn, cardholder, complexity)

        elif fraud_type == "account_takeover":
            txn = self._apply_account_takeover(txn, cardholder, complexity)

        elif fraud_type == "geographic_anomaly":
            txn = self._apply_geographic_anomaly(txn, cardholder, complexity)

        elif fraud_type == "velocity_abuse":
            txn = self._apply_velocity_abuse(txn, cardholder, complexity)

        elif fraud_type == "friendly_fraud":
            # Friendly fraud looks normal — minimal modifications
            txn = self._apply_friendly_fraud(txn, cardholder, complexity)

        # Set fraud labels
        txn["is_fraud"] = True
        txn["fraud_type"] = fraud_type
        txn["fraud_confidence"] = confidence

        return txn

    def _apply_cnp_fraud(self, txn: Dict, ch: CardHolder, complexity: str) -> Dict:
        """
        Card-Not-Present fraud: stolen card used online.

        Easy:   huge amount (10-25x average) + online + new merchant
        Medium: moderate amount (5-10x) + online
        Hard:   slightly elevated (2-5x) + online (looks almost normal)
        """
        txn["is_online"] = True
        txn["channel"] = "web"
        txn["device_type"] = random.choice(["desktop", "mobile"])

        # Pick a category the cardholder doesn't usually use
        unusual_categories = [
            c for c in MERCHANT_CATEGORIES if c not in ch.preferred_categories
        ]
        if unusual_categories:
            category = random.choice(unusual_categories)
            txn["merchant_category"] = category
            txn["merchant_name"] = random.choice(MERCHANT_CATEGORIES[category]["merchants"])

        if complexity == "easy":
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(0.8, 2.0), 2)
        elif complexity == "medium":
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(0.4, 0.8), 2)
        else:  # hard
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(0.15, 0.4), 2)

        return txn

    def _apply_account_takeover(self, txn: Dict, ch: CardHolder, complexity: str) -> Dict:
        """
        Account takeover: fraudster controls the account.

        Easy:   massive amount + new device concept (device stays same ID but
                pattern is amount-based since Spark computes device novelty)
        Medium: large amount at unusual merchant category
        Hard:   moderately unusual spending, subtle shift
        """
        # Always at an unusual category
        unusual_categories = [
            c for c in MERCHANT_CATEGORIES if c not in ch.preferred_categories
        ]
        if unusual_categories:
            category = random.choice(unusual_categories)
            txn["merchant_category"] = category
            txn["merchant_name"] = random.choice(MERCHANT_CATEGORIES[category]["merchants"])

        if complexity == "easy":
            # Massive: close to card limit
            txn["amount"] = round(ch.card_limit * random.uniform(0.6, 0.9), 2)
        elif complexity == "medium":
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(3.0, 8.0), 2)
        else:  # hard
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(1.5, 3.0), 2)

        return txn

    def _apply_geographic_anomaly(self, txn: Dict, ch: CardHolder, complexity: str) -> Dict:
        """
        Geographic anomaly: impossible location jump.

        Picks a city FAR from the cardholder's last transaction (or home city).
        The timestamp is close to the last transaction, making the travel
        physically impossible. Spark will compute distance + time gap and flag it.
        """
        # Find last known location
        if ch.recent_transactions:
            last_city = ch.recent_transactions[-1]["city"]
        else:
            last_city = ch.home_city

        # Pick a city that's far away (>500km ideally)
        last_data = INDIAN_CITIES.get(last_city, INDIAN_CITIES[ch.home_city])
        far_cities = []
        for city_name, city_data in INDIAN_CITIES.items():
            if city_name == last_city:
                continue
            dist = self._haversine(
                last_data["lat"], last_data["lon"],
                city_data["lat"], city_data["lon"],
            )
            if dist > 500:
                far_cities.append(city_name)

        if far_cities:
            new_city = random.choice(far_cities)
        else:
            # Fallback: just pick any different city
            other_cities = [c for c in self._city_names if c != last_city]
            new_city = random.choice(other_cities)

        city_data = INDIAN_CITIES[new_city]
        txn["city"] = new_city
        txn["location_lat"] = round(city_data["lat"] + random.uniform(-0.05, 0.05), 4)
        txn["location_lon"] = round(city_data["lon"] + random.uniform(-0.05, 0.05), 4)

        return txn

    def _apply_velocity_abuse(self, txn: Dict, ch: CardHolder, complexity: str) -> Dict:
        """
        Velocity abuse: rapid-fire testing of a stolen card.

        The single transaction itself looks small and innocuous.
        The fraud signal comes from Spark detecting MANY transactions
        from this card in a short window. The generator ensures this
        cardholder gets picked frequently during velocity fraud.

        Easy:   very small amounts (testing amounts ₹1-50)
        Medium: small amounts (₹50-500) at varied merchants
        Hard:   normal-looking small amounts
        """
        if complexity == "easy":
            txn["amount"] = round(random.uniform(1, 50), 2)
        elif complexity == "medium":
            txn["amount"] = round(random.uniform(50, 500), 2)
        else:
            txn["amount"] = round(random.uniform(100, 2000), 2)

        # Different merchant each time (card testing behavior)
        category = random.choice(list(MERCHANT_CATEGORIES.keys()))
        txn["merchant_category"] = category
        txn["merchant_name"] = random.choice(MERCHANT_CATEGORIES[category]["merchants"])

        return txn

    def _apply_friendly_fraud(self, txn: Dict, ch: CardHolder, complexity: str) -> Dict:
        """
        Friendly fraud: looks completely normal, will be disputed later.

        Minimal modifications — the fraud is in the LABEL, not the data.
        Spark has to learn that even normal-looking transactions can be fraud.
        """
        # Keep everything normal, maybe slight amount bump for medium/easy
        if complexity == "easy":
            # Slightly higher than usual but within reason
            txn["amount"] = round(ch.avg_monthly_spend * random.uniform(0.3, 0.6), 2)
        # medium and hard: no modifications at all — truly looks normal

        return txn

    # -------------------------------------------------------------------------
    # Main Generation Method
    # -------------------------------------------------------------------------

    def generate_one(self) -> Dict:
        """
        Generate a single transaction (normal or fraud).

        This is the method called by the main loop on every cycle.
        """
        # Pick a random cardholder
        cardholder = random.choice(self.cardholders)

        # Roll the dice: fraud or normal?
        if random.random() < FRAUD_RATE:
            txn = self.generate_fraud_transaction(cardholder)
            self.fraud_count += 1
        else:
            txn = self.generate_normal_transaction(cardholder)

        # Record in cardholder's internal history (NOT in output)
        cardholder.record_transaction(txn)

        self.transaction_count += 1
        return txn


# =============================================================================
# PUBLISHERS — Where do generated transactions go?
# =============================================================================

class LocalPublisher:
    """Prints transactions to console as JSON. For testing."""

    def publish(self, txn: Dict):
        print(json.dumps(txn, indent=2))

    def flush(self):
        pass


class CsvPublisher:
    """Writes transactions to a CSV file. For testing with files."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._file = open(path, "w")
        self._header_written = False

    def publish(self, txn: Dict):
        if not self._header_written:
            self._file.write(",".join(txn.keys()) + "\n")
            self._header_written = True
        values = []
        for v in txn.values():
            if v is None:
                values.append("")
            elif isinstance(v, bool):
                values.append(str(v).lower())
            else:
                values.append(str(v))
        self._file.write(",".join(values) + "\n")

    def flush(self):
        self._file.flush()

    def __del__(self):
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()


class PubSubPublisher:
    """
    Publishes transactions to Google Cloud Pub/Sub.
    Batches messages for efficiency.

    Requires: google-cloud-pubsub package
    """

    def __init__(self, project_id: str, topic_id: str, batch_size: int):
        # Import here so local/csv modes don't need the GCP SDK installed
        from google.cloud import pubsub_v1

        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(project_id, topic_id)
        self.batch_size = batch_size
        self._batch: List[Dict] = []
        logger.info(f"PubSub publisher ready. Topic: {self.topic_path}")

    def publish(self, txn: Dict):
        self._batch.append(txn)
        if len(self._batch) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self._batch:
            return
        for txn in self._batch:
            data = json.dumps(txn).encode("utf-8")
            self.publisher.publish(self.topic_path, data=data)
        logger.debug(f"Published batch of {len(self._batch)} messages to Pub/Sub.")
        self._batch.clear()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Transaction Data Generator")
    parser.add_argument(
        "--mode", choices=["local", "csv", "pubsub"], default="local",
        help="Output mode: local (console), csv (file), pubsub (GCP)",
    )
    parser.add_argument(
        "--count", type=int, default=0,
        help="Generate exactly N transactions then stop. 0 = run forever.",
    )
    args = parser.parse_args()

    # Create publisher based on mode
    if args.mode == "local":
        publisher = LocalPublisher()
    elif args.mode == "csv":
        publisher = CsvPublisher(CSV_OUTPUT_PATH)
    elif args.mode == "pubsub":
        publisher = PubSubPublisher(GCP_PROJECT_ID, PUBSUB_TOPIC, PUBSUB_BATCH_SIZE)

    # Create the generator (initializes 25,000 cardholders)
    generator = TransactionGenerator()

    logger.info(f"Starting generator in '{args.mode}' mode.")
    if args.count > 0:
        logger.info(f"Will generate exactly {args.count} transactions.")
    else:
        logger.info("Running continuously. Press Ctrl+C to stop.")

    start_time = time.time()

    try:
        i = 0
        while True:
            # Generate one transaction
            txn = generator.generate_one()

            # Publish it
            publisher.publish(txn)

            # Log progress
            if generator.transaction_count % LOG_EVERY_N == 0:
                elapsed = time.time() - start_time
                rate = generator.transaction_count / max(elapsed, 1)
                fraud_pct = (
                    generator.fraud_count / max(generator.transaction_count, 1) * 100
                )
                logger.info(
                    f"Transactions: {generator.transaction_count:,} | "
                    f"Fraud: {generator.fraud_count:,} ({fraud_pct:.1f}%) | "
                    f"Rate: {rate:.1f} txn/sec"
                )

            i += 1
            # Check if we've hit the count limit
            if args.count > 0 and i >= args.count:
                break

            # Sleep based on traffic pattern (only in continuous mode)
            if args.count == 0:
                sleep_time = generator.get_sleep_time()
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\nStopping generator (Ctrl+C received).")

    # Final stats
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Generator stopped.")
    logger.info(f"  Total transactions: {generator.transaction_count:,}")
    logger.info(f"  Total fraud: {generator.fraud_count:,}")
    logger.info(
        f"  Fraud rate: "
        f"{generator.fraud_count / max(generator.transaction_count, 1) * 100:.2f}%"
    )
    logger.info(f"  Duration: {elapsed:.1f} seconds")
    logger.info(f"  Avg rate: {generator.transaction_count / max(elapsed, 1):.1f} txn/sec")
    logger.info("=" * 60)

    # Flush remaining batch
    if hasattr(publisher, "flush"):
        publisher.flush()


if __name__ == "__main__":
    main()
