import json, random
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────── 1) UNIQUE ACCOUNTS (10) ──────────────────────────
ACCOUNTS = [
    "GreenValley Health System",
    "NorthStar Hospitals",
    "PrimeCare Clinics",
    "Metro Health Network",
    "WellPath Pharmacy Group",
    "Sunrise IDN",
    "Crescent Health Plan",
    "BlueRiver Medical Center",
    "HarborPoint Pharmacy Alliance",
    "SummitCare Insurance"
]

# ─────────────────────────── static pharma vocab ────────────────────────────
ACCOUNT_INDUSTRIES = [
    "Integrated Delivery Network", "Hospital", "Clinic Network",
    "Retail Pharmacy Chain", "Health Insurance / Payer"
]
ACCOUNT_SIZES = ["Small", "Mid‑market", "Enterprise"]
CONTACT_TITLES = [
    "Director of Pharmacy", "Chief Medical Officer",
    "Infectious‑Disease Specialist", "Payer Contract Manager",
    "Vaccines Coordinator"
]

BRANDS = [
    {"drug": "Shingrix", "therapy_area": "Vaccines"},
    {"drug": "Trelegy",  "therapy_area": "Respiratory"},
    {"drug": "Nucala",   "therapy_area": "Respiratory"},
    {"drug": "Jemperli", "therapy_area": "Oncology"},
    {"drug": "Arexvy",   "therapy_area": "Vaccines"}
]

REP_FEATURES = [
    "Call Planning", "Sample Management", "Vaccination Campaign Tracker",
    "Payer Formulary Insights", "HCP Segmentation", "Rep Performance Dashboard",
    "Field Force Analytics"
]

MEETING_TYPES = [
    "Payer Formulary Review", "Clinical Data Update",
    "Quarterly Business Review", "Advisory Board – Vaccines"
]

DEAL_STAGES    = ["Prospect", "Onboarding", "Growth", "Expansion", "Mature"]
ACCOUNT_HEALTH = ["Excellent", "Good", "Fair", "Poor"]

SALES_REPS = [
    ("Linda Green",   "Vaccines Account Executive"),
    ("John Smith",    "Respiratory Sales Specialist"),
    ("Sarah Lee",     "Oncology Key Account Manager"),
    ("Emily White",   "Regional Field Director"),
    ("Michael Brown", "Senior Territory Representative"),
    ("Rachel Adams",  "Strategic Payer Lead")
]

# ─────────────────────────── helper functions ──────────────────────────────
def _phone():
    return f"(555) {random.randint(100,999)}-{random.randint(1000,9999)}"

def _pct_change():
    delta = random.randint(-15, 20)
    return f"{delta:+d}% from last month"

def _date_offset(days):
    return (datetime.today() - timedelta(days=random.randint(1, days))
            ).strftime("%Y-%m-%d")

def _meeting():
    return {
        "date": _date_offset(90),
        "type": random.choice(MEETING_TYPES),
        "summary": "Reviewed formulary status and upcoming data‑drop schedule.",
        "action_items": [
            "Provide updated clinical evidence deck",
            "Schedule peer‑to‑peer session",
            "Confirm next quarter’s sample allocation"
        ]
    }

def _product_usage():
    most  = random.sample(REP_FEATURES, 3)
    least = random.sample([f for f in REP_FEATURES if f not in most], 2)
    return {
        "active_users": random.randint(20, 2000),
        "active_users_change": _pct_change(),
        "most_used_features": most,
        "least_used_features": least,
        "potential_opportunity": f"Promote uptake of {least[0]}"
    }

def _drug_insights():
    insights = []
    for brand in random.sample(BRANDS, random.randint(1, 3)):
        insights.append({
            "drug":               brand["drug"],
            "therapy_area":       brand["therapy_area"],
            "scripts_30d":        random.randint(500, 25000),
            "market_share_pct":   round(random.uniform(2, 25), 1),
            "formulary_status":   random.choice(["Preferred", "Standard", "Non‑formulary"]),
            "growth_pct_vs_prev": round(random.uniform(-5, 18), 1)
        })
    return insights

def _support_ticket():
    return {
        "id": f"TK-{random.randint(1000,9999)}",
        "status": random.choice(["Open", "Closed"]),
        "issue": random.choice([
            "Sample shipment delay",
            "Formulary feed mismatch",
            "Vaccination tracker bug"
        ]),
        "priority": random.choice(["Low", "Medium", "High"])
    }

# ─────────────────────────── 2) RECORD BUILDER ─────────────────────────────
def build_record(idx: int) -> dict:
    random.seed(idx)  # reproducible

    account_name = ACCOUNTS[idx]          # unique & fixed
    industry     = ACCOUNT_INDUSTRIES[idx % len(ACCOUNT_INDUSTRIES)]
    size         = random.choice(ACCOUNT_SIZES)

    first, last = random.choice(
        ["Alex", "Jordan", "Taylor", "Riley", "Casey", "Morgan", "Jamie"]
    ), random.choice(["Smith", "Johnson", "Lee", "Patel", "Garcia", "Brown", "Ahmed"])
    contact_title = random.choice(CONTACT_TITLES)

    customer_since = _date_offset(1800)
    last_contact   = _date_offset(60)
    next_renewal   = (datetime.strptime(customer_since, "%Y-%m-%d")
                      + timedelta(days=365 * random.randint(1, 5))
                     ).strftime("%Y-%m-%d")

    rep_name, rep_title = SALES_REPS[idx % len(SALES_REPS)]

    return {
        "account": {
            "name":     account_name,
            "industry": industry,
            "size":     size,
            "main_contact": {
                "name":  f"{first} {last}",
                "title": contact_title,
                "email": f"{first.lower()}.{last.lower()}@"
                         f"{account_name.split()[0].lower()}.com"
            },
            "relationship": {
                "customer_since":   customer_since,
                "deal_stage":       random.choice(DEAL_STAGES),
                "account_health":   random.choice(ACCOUNT_HEALTH),
                "last_contact_date": last_contact,
                "next_renewal":     next_renewal
            }
        },

        "recent_activity": {
            "meetings":        [_meeting()],
            "product_usage":   _product_usage(),
            "support_tickets": [_support_ticket()]
        },

        "drug_insights": _drug_insights(),

        "sales_rep": {
            "name":      rep_name,
            "title":     rep_title,
            "signature": f"{rep_name}\n{rep_title}\nGSK\n{_phone()}"
        }
    }

# ─────────────────────────── 3) GENERATE 10 RECORDS ────────────────────────
OUT_PATH = Path("gsk_10_accounts.jsonl")
with OUT_PATH.open("w") as f:
    for i in range(10):                     # exactly 10 records
        f.write(json.dumps(build_record(i)) + "\n")

print(f"✅ 10 unique‑account records written to {OUT_PATH}")
