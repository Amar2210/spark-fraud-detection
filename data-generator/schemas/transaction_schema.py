"""
Transaction Schema — Data definitions for the fraud detection data generator.

This module contains all the "DNA" of the generator:
- Merchant categories with real Indian brand names
- Indian cities with GPS coordinates and population-based weights
- Fraud taxonomy (5 types) with weights and descriptions
- Cardholder profiles (4 segments) with income/spending ranges
- Hourly traffic pattern multipliers
- Amount ranges per merchant category

Design Philosophy (from Google's Simula paper):
  Don't generate random data — design a taxonomy of what you're simulating.
  Control diversity, complexity, and quality independently.
  Better data > more data.
"""

# =============================================================================
# MERCHANT CATEGORIES
# =============================================================================
# Each category has:
#   - merchants: list of real Indian brand names
#   - amount_range: (min, max) in INR — typical transaction range
#   - online_probability: how likely a purchase in this category is online
#
# Why real brands? Because when you look at the Grafana dashboard and see
# "Flipkart" or "Swiggy", it immediately feels real. Random names like
# "Merchant_042" tell you nothing.

MERCHANT_CATEGORIES = {
    "groceries": {
        "merchants": ["BigBasket", "DMart", "More Supermarket", "Reliance Fresh",
                       "Star Bazaar", "Nature's Basket", "Spencer's"],
        "amount_range": (150, 8000),
        "online_probability": 0.35,
    },
    "online_retail": {
        "merchants": ["Amazon", "Flipkart", "Myntra", "Meesho", "Ajio",
                       "Tata Cliq", "Nykaa"],
        "amount_range": (200, 50000),
        "online_probability": 0.95,
    },
    "electronics": {
        "merchants": ["Croma", "Reliance Digital", "Vijay Sales",
                       "Samsung Store", "Apple Store"],
        "amount_range": (1000, 150000),
        "online_probability": 0.45,
    },
    "fuel": {
        "merchants": ["IndianOil", "HP Fuel", "Bharat Petroleum",
                       "Shell", "Nayara Energy"],
        "amount_range": (200, 5000),
        "online_probability": 0.0,  # Fuel is always in-person
    },
    "dining": {
        "merchants": ["Swiggy", "Zomato", "Barbeque Nation", "Haldiram's",
                       "Domino's", "McDonald's", "Starbucks", "Chai Point"],
        "amount_range": (100, 5000),
        "online_probability": 0.65,
    },
    "travel": {
        "merchants": ["MakeMyTrip", "Cleartrip", "IRCTC", "IndiGo",
                       "Air India", "RedBus", "Ola", "Uber"],
        "amount_range": (100, 80000),
        "online_probability": 0.85,
    },
    "entertainment": {
        "merchants": ["BookMyShow", "Netflix", "Spotify", "Hotstar",
                       "Amazon Prime", "Jio Cinema"],
        "amount_range": (99, 2000),
        "online_probability": 0.90,
    },
    "healthcare": {
        "merchants": ["Apollo Pharmacy", "Practo", "1mg", "PharmEasy",
                       "Netmeds", "MedPlus"],
        "amount_range": (100, 25000),
        "online_probability": 0.50,
    },
    "utilities": {
        "merchants": ["BESCOM", "Tata Power", "Jio", "Airtel", "Vi",
                       "Mahanagar Gas", "BSNL"],
        "amount_range": (200, 5000),
        "online_probability": 0.80,
    },
    "fashion": {
        "merchants": ["Zara", "H&M", "Shoppers Stop", "Lifestyle",
                       "Pantaloons", "Max Fashion", "FabIndia"],
        "amount_range": (500, 30000),
        "online_probability": 0.55,
    },
}

# =============================================================================
# INDIAN CITIES
# =============================================================================
# Each city has:
#   - lat, lon: GPS coordinates (center of city)
#   - weight: probability of a transaction originating here
#
# Weights are roughly proportional to metro economic activity.
# Bangalore/Mumbai/Delhi dominate because they have the most
# digital transactions in India (UPI + card payments).

INDIAN_CITIES = {
    "Bangalore":  {"lat": 12.9716, "lon": 77.5946, "weight": 0.20},
    "Mumbai":     {"lat": 19.0760, "lon": 72.8777, "weight": 0.18},
    "Delhi":      {"lat": 28.7041, "lon": 77.1025, "weight": 0.15},
    "Hyderabad":  {"lat": 17.3850, "lon": 78.4867, "weight": 0.10},
    "Chennai":    {"lat": 13.0827, "lon": 80.2707, "weight": 0.08},
    "Pune":       {"lat": 18.5204, "lon": 73.8567, "weight": 0.07},
    "Kolkata":    {"lat": 22.5726, "lon": 88.3639, "weight": 0.06},
    "Ahmedabad":  {"lat": 23.0225, "lon": 72.5714, "weight": 0.05},
    "Jaipur":     {"lat": 26.9124, "lon": 75.7873, "weight": 0.04},
    "Lucknow":    {"lat": 26.8467, "lon": 80.9462, "weight": 0.03},
    "Chandigarh": {"lat": 30.7333, "lon": 76.7794, "weight": 0.02},
    "Kochi":      {"lat": 9.9312,  "lon": 76.2673, "weight": 0.02},
}

# =============================================================================
# FRAUD TAXONOMY
# =============================================================================
# 5 fraud types, each with:
#   - weight: probability of this type (among all fraud transactions)
#   - description: what this fraud looks like in the real world
#
# The generator uses these weights to pick WHICH type of fraud to generate.
# Then it uses internal cardholder history to CRAFT a realistic instance.
#
# Complexity levels (applied per fraud instance):
#   - easy   (confidence 0.7-0.95): obvious red flags, Spark catches easily
#   - medium (confidence 0.4-0.7):  needs multiple signals combined
#   - hard   (confidence 0.15-0.4): subtle, looks almost legitimate

FRAUD_TAXONOMY = {
    "card_not_present": {
        "weight": 0.30,
        "description": "Stolen card details used for online purchases",
        # Pattern: small test transaction (₹50-200) followed by a big one (₹20K+)
        # Generator creates both transactions on the same card, minutes apart
    },
    "account_takeover": {
        "weight": 0.25,
        "description": "Fraudster gains access to legitimate account",
        # Pattern: sudden spending spike — amount >> avg_monthly_spend
        # Generator picks a cardholder and creates a transaction 10-25x their average
        # Often at a new merchant in a category they don't usually shop in
    },
    "geographic_anomaly": {
        "weight": 0.20,
        "description": "Physically impossible transaction locations",
        # Pattern: two transactions 500+ km apart within 30 minutes
        # Generator checks last transaction city, picks a distant city
    },
    "velocity_abuse": {
        "weight": 0.15,
        "description": "Rapid-fire transactions testing a stolen card",
        # Pattern: 5+ transactions in under an hour at different merchants
        # Generator creates a burst of transactions with short time gaps
    },
    "friendly_fraud": {
        "weight": 0.10,
        "description": "Legitimate-looking transaction that will be disputed",
        # Pattern: normal amount, normal merchant, normal time
        # Hard to detect because it LOOKS normal — low confidence score
        # These exist to test Spark's ability to handle ambiguous cases
    },
}

# Complexity distribution: what percentage of fraud falls into each difficulty
FRAUD_COMPLEXITY = {
    "easy":   {"weight": 0.30, "confidence_range": (0.70, 0.95)},
    "medium": {"weight": 0.45, "confidence_range": (0.40, 0.70)},
    "hard":   {"weight": 0.25, "confidence_range": (0.15, 0.40)},
}

# =============================================================================
# CARDHOLDER PROFILES
# =============================================================================
# 4 segments with different financial characteristics.
# When the generator creates 25,000 cardholders, it assigns each one a profile
# based on the weights below. The profile determines income, card limit,
# spending habits, and which merchant categories they frequent.

CARDHOLDER_PROFILES = {
    "high_income": {
        "weight": 0.136,  # 13.6% of cardholders
        "monthly_income_range": (150000, 500000),
        "card_limit_range": (300000, 1000000),
        "card_types": ["credit"],
        "avg_monthly_spend_factor": (0.15, 0.35),  # 15-35% of income
        "preferred_categories": [
            "online_retail", "electronics", "travel", "fashion", "dining"
        ],
        "emi_range": (0, 3),
        "default_probability": 0.02,  # rarely defaults
    },
    "mid_income": {
        "weight": 0.475,  # 47.5% — the bulk
        "monthly_income_range": (40000, 150000),
        "card_limit_range": (75000, 300000),
        "card_types": ["credit", "debit"],
        "avg_monthly_spend_factor": (0.20, 0.45),
        "preferred_categories": [
            "groceries", "online_retail", "dining", "utilities", "fuel"
        ],
        "emi_range": (0, 5),
        "default_probability": 0.08,
    },
    "low_income": {
        "weight": 0.291,  # 29.1%
        "monthly_income_range": (15000, 40000),
        "card_limit_range": (25000, 75000),
        "card_types": ["debit"],
        "avg_monthly_spend_factor": (0.30, 0.60),
        "preferred_categories": [
            "groceries", "fuel", "utilities", "healthcare"
        ],
        "emi_range": (0, 3),
        "default_probability": 0.15,
    },
    "student": {
        "weight": 0.098,  # 9.8%
        "monthly_income_range": (5000, 15000),
        "card_limit_range": (10000, 30000),
        "card_types": ["debit"],
        "avg_monthly_spend_factor": (0.40, 0.70),
        "preferred_categories": [
            "dining", "entertainment", "online_retail", "fashion"
        ],
        "emi_range": (0, 1),
        "default_probability": 0.10,
    },
}

# =============================================================================
# DEVICE & CHANNEL DEFINITIONS
# =============================================================================

DEVICE_TYPES = ["mobile", "desktop", "pos_terminal", "tablet"]

# Which channels are possible for each device type
# mobile       → app or mobile_wallet (UPI, Google Pay, etc.)
# desktop      → web (browser-based shopping)
# pos_terminal → in_store (physical card swipe/tap)
# tablet       → app or web
CHANNELS = {
    "mobile":       ["app", "mobile_wallet"],
    "desktop":      ["web"],
    "pos_terminal": ["in_store"],
    "tablet":       ["app", "web"],
}

# =============================================================================
# TRAFFIC PATTERN — Hourly rate multipliers
# =============================================================================
# These define how transaction volume changes throughout the day.
# Multiplier of 1.0 = the base rate (peak hour).
# 0.03 = 3% of peak rate (3 AM dead zone).
#
# The generator uses these to calculate sleep time between transactions.
# At peak (1.0), sleep is short → many transactions.
# At 3 AM (0.03), sleep is long → almost no transactions.
#
# On top of this, random jitter (±50%) is applied each cycle,
# plus rare burst events (3% chance per hour) for flash-sale spikes.

HOURLY_RATE_MULTIPLIERS = {
    0:  0.08,   # 12 AM — very quiet
    1:  0.05,   # 1 AM  — lowest point
    2:  0.03,   # 2 AM  — almost nothing
    3:  0.03,   # 3 AM  — almost nothing
    4:  0.05,   # 4 AM  — barely waking up
    5:  0.10,   # 5 AM  — early risers
    6:  0.25,   # 6 AM  — morning starts
    7:  0.45,   # 7 AM  — commute begins
    8:  0.65,   # 8 AM  — morning transactions
    9:  0.80,   # 9 AM  — work starts, online shopping
    10: 0.90,   # 10 AM — mid-morning peak
    11: 0.95,   # 11 AM — approaching lunch
    12: 1.00,   # 12 PM — LUNCH PEAK
    13: 0.95,   # 1 PM  — post-lunch
    14: 0.85,   # 2 PM  — afternoon
    15: 0.80,   # 3 PM  — afternoon dip
    16: 0.75,   # 4 PM  — pre-evening
    17: 0.85,   # 5 PM  — evening commute
    18: 0.95,   # 6 PM  — evening shopping
    19: 1.00,   # 7 PM  — DINNER PEAK (tied with lunch)
    20: 0.90,   # 8 PM  — post-dinner
    21: 0.70,   # 9 PM  — winding down
    22: 0.45,   # 10 PM — late night
    23: 0.20,   # 11 PM — going to sleep
}

# Burst event configuration
# A "burst" simulates a flash sale or payday spike
BURST_CONFIG = {
    "probability_per_hour": 0.03,   # 3% chance any given hour has a burst
    "rate_multiplier": (8.0, 10.0),  # During burst, rate is 3-5x normal
    "duration_minutes": (10, 30),   # Burst lasts 10-30 minutes
}
