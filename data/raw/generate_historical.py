#!/usr/bin/env python3
"""Generate data/raw/historical_results.csv with 600+ international match records.

Includes hardcoded real WC results (WC2022, WC2018, WC2014) plus synthetic
qualifier/friendly matches using real team names. All scores are non-negative
and all dates are before 2026-06-11.

Usage:
    python data/raw/generate_historical.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUTPUT = Path(__file__).parent / "historical_results.csv"

# ---------------------------------------------------------------------------
# Real WC results (English names — normalization is tested via csv_loader)
# ---------------------------------------------------------------------------

WC2022 = [
    ("2022-11-20","Qatar","Ecuador",0,2,"WC2022",1),
    ("2022-11-21","England","Iran",6,2,"WC2022",1),
    ("2022-11-21","Senegal","Netherlands",0,2,"WC2022",1),
    ("2022-11-21","USA","Wales",1,1,"WC2022",1),
    ("2022-11-22","Argentina","Saudi Arabia",1,2,"WC2022",1),
    ("2022-11-22","Denmark","Tunisia",0,0,"WC2022",1),
    ("2022-11-22","Mexico","Poland",0,0,"WC2022",1),
    ("2022-11-22","France","Australia",4,1,"WC2022",1),
    ("2022-11-23","Morocco","Croatia",0,0,"WC2022",1),
    ("2022-11-23","Germany","Japan",1,2,"WC2022",1),
    ("2022-11-23","Spain","Costa Rica",7,0,"WC2022",1),
    ("2022-11-23","Belgium","Canada",1,0,"WC2022",1),
    ("2022-11-24","Switzerland","Cameroon",1,0,"WC2022",1),
    ("2022-11-24","Uruguay","South Korea",0,0,"WC2022",1),
    ("2022-11-24","Portugal","Ghana",3,2,"WC2022",1),
    ("2022-11-24","Brazil","Serbia",2,0,"WC2022",1),
    ("2022-11-25","Wales","Iran",0,2,"WC2022",1),
    ("2022-11-25","Qatar","Senegal",1,3,"WC2022",1),
    ("2022-11-25","Netherlands","Ecuador",1,1,"WC2022",1),
    ("2022-11-25","England","USA",0,0,"WC2022",1),
    ("2022-11-26","Tunisia","Australia",0,1,"WC2022",1),
    ("2022-11-26","Poland","Saudi Arabia",2,0,"WC2022",1),
    ("2022-11-26","France","Denmark",2,1,"WC2022",1),
    ("2022-11-26","Argentina","Mexico",2,0,"WC2022",1),
    ("2022-11-27","Japan","Costa Rica",0,1,"WC2022",1),
    ("2022-11-27","Belgium","Morocco",0,2,"WC2022",1),
    ("2022-11-27","Croatia","Canada",4,1,"WC2022",1),
    ("2022-11-27","Spain","Germany",1,1,"WC2022",1),
    ("2022-11-28","Cameroon","Serbia",3,3,"WC2022",1),
    ("2022-11-28","South Korea","Ghana",2,3,"WC2022",1),
    ("2022-11-28","Brazil","Switzerland",1,0,"WC2022",1),
    ("2022-11-28","Portugal","Uruguay",2,0,"WC2022",1),
    ("2022-11-29","Ecuador","Senegal",1,2,"WC2022",1),
    ("2022-11-29","Netherlands","Qatar",2,0,"WC2022",1),
    ("2022-11-29","Iran","USA",0,1,"WC2022",1),
    ("2022-11-29","Wales","England",0,3,"WC2022",1),
    ("2022-11-30","Australia","Denmark",1,0,"WC2022",1),
    ("2022-11-30","Tunisia","France",1,0,"WC2022",1),
    ("2022-11-30","Poland","Argentina",0,2,"WC2022",1),
    ("2022-11-30","Saudi Arabia","Mexico",1,2,"WC2022",1),
    ("2022-12-01","Croatia","Belgium",0,0,"WC2022",1),
    ("2022-12-01","Canada","Morocco",1,2,"WC2022",1),
    ("2022-12-01","Japan","Spain",2,1,"WC2022",1),
    ("2022-12-01","Costa Rica","Germany",2,4,"WC2022",1),
    ("2022-12-02","South Korea","Portugal",2,1,"WC2022",1),
    ("2022-12-02","Ghana","Uruguay",0,2,"WC2022",1),
    ("2022-12-02","Serbia","Switzerland",2,3,"WC2022",1),
    ("2022-12-02","Cameroon","Brazil",1,0,"WC2022",1),
    # Round of 16
    ("2022-12-03","Netherlands","USA",3,1,"WC2022",1),
    ("2022-12-03","Argentina","Australia",2,1,"WC2022",1),
    ("2022-12-04","France","Poland",3,1,"WC2022",1),
    ("2022-12-04","England","Senegal",3,0,"WC2022",1),
    ("2022-12-05","Japan","Croatia",1,1,"WC2022",1),
    ("2022-12-05","Brazil","South Korea",4,1,"WC2022",1),
    ("2022-12-06","Morocco","Spain",0,0,"WC2022",1),
    ("2022-12-06","Portugal","Switzerland",6,1,"WC2022",1),
    # Quarter-finals
    ("2022-12-09","Netherlands","Argentina",2,2,"WC2022",1),
    ("2022-12-09","Croatia","Brazil",1,1,"WC2022",1),
    ("2022-12-10","Morocco","Portugal",1,0,"WC2022",1),
    ("2022-12-10","England","France",1,2,"WC2022",1),
    # Semi-finals
    ("2022-12-13","Argentina","Croatia",3,0,"WC2022",1),
    ("2022-12-14","France","Morocco",2,0,"WC2022",1),
    # Third place
    ("2022-12-17","Croatia","Morocco",2,1,"WC2022",1),
    # Final
    ("2022-12-18","Argentina","France",3,3,"WC2022",1),
]

WC2018 = [
    ("2018-06-14","Russia","Saudi Arabia",5,0,"WC2018",1),
    ("2018-06-15","Egypt","Uruguay",0,1,"WC2018",1),
    ("2018-06-15","Morocco","Iran",0,1,"WC2018",1),
    ("2018-06-15","Portugal","Spain",3,3,"WC2018",1),
    ("2018-06-16","France","Australia",2,1,"WC2018",1),
    ("2018-06-16","Argentina","Iceland",1,1,"WC2018",1),
    ("2018-06-16","Peru","Denmark",0,1,"WC2018",1),
    ("2018-06-16","Croatia","Nigeria",2,0,"WC2018",1),
    ("2018-06-17","Costa Rica","Serbia",0,1,"WC2018",1),
    ("2018-06-17","Germany","Mexico",0,1,"WC2018",1),
    ("2018-06-17","Brazil","Switzerland",1,1,"WC2018",1),
    ("2018-06-18","Sweden","South Korea",1,0,"WC2018",1),
    ("2018-06-18","Belgium","Panama",3,0,"WC2018",1),
    ("2018-06-18","Tunisia","England",1,2,"WC2018",1),
    ("2018-06-19","Colombia","Japan",1,2,"WC2018",1),
    ("2018-06-19","Poland","Senegal",1,2,"WC2018",1),
    ("2018-06-19","Russia","Egypt",3,0,"WC2018",1),
    ("2018-06-19","Portugal","Morocco",1,0,"WC2018",1),
    ("2018-06-20","Uruguay","Saudi Arabia",1,0,"WC2018",1),
    ("2018-06-20","Iran","Spain",0,1,"WC2018",1),
    ("2018-06-20","Denmark","Australia",1,1,"WC2018",1),
    ("2018-06-20","France","Peru",1,0,"WC2018",1),
    ("2018-06-21","Argentina","Croatia",0,3,"WC2018",1),
    ("2018-06-21","Brazil","Costa Rica",2,0,"WC2018",1),
    ("2018-06-21","Nigeria","Iceland",2,0,"WC2018",1),
    ("2018-06-21","Serbia","Switzerland",1,2,"WC2018",1),
    ("2018-06-22","Belgium","Tunisia",5,2,"WC2018",1),
    ("2018-06-22","South Korea","Mexico",1,2,"WC2018",1),
    ("2018-06-22","Germany","Sweden",2,1,"WC2018",1),
    ("2018-06-23","England","Panama",6,1,"WC2018",1),
    ("2018-06-23","Japan","Senegal",2,2,"WC2018",1),
    ("2018-06-23","Poland","Colombia",0,3,"WC2018",1),
    ("2018-06-24","Uruguay","Russia",3,0,"WC2018",1),
    ("2018-06-24","Saudi Arabia","Egypt",2,1,"WC2018",1),
    ("2018-06-24","Iran","Portugal",1,1,"WC2018",1),
    ("2018-06-24","Spain","Morocco",2,2,"WC2018",1),
    ("2018-06-25","Denmark","France",0,0,"WC2018",1),
    ("2018-06-25","Australia","Peru",0,2,"WC2018",1),
    ("2018-06-25","Nigeria","Argentina",1,2,"WC2018",1),
    ("2018-06-25","Iceland","Croatia",1,2,"WC2018",1),
    ("2018-06-26","Mexico","Sweden",0,3,"WC2018",1),
    ("2018-06-26","South Korea","Germany",2,0,"WC2018",1),
    ("2018-06-26","Switzerland","Costa Rica",2,2,"WC2018",1),
    ("2018-06-26","Serbia","Brazil",0,2,"WC2018",1),
    ("2018-06-27","England","Belgium",0,1,"WC2018",1),
    ("2018-06-27","Panama","Tunisia",1,2,"WC2018",1),
    ("2018-06-27","Japan","Poland",0,1,"WC2018",1),
    ("2018-06-27","Senegal","Colombia",0,1,"WC2018",1),
    # Round of 16
    ("2018-06-30","France","Argentina",4,3,"WC2018",1),
    ("2018-06-30","Uruguay","Portugal",2,1,"WC2018",1),
    ("2018-07-01","Spain","Russia",1,1,"WC2018",1),
    ("2018-07-01","Croatia","Denmark",1,1,"WC2018",1),
    ("2018-07-02","Brazil","Mexico",2,0,"WC2018",1),
    ("2018-07-02","Belgium","Japan",3,2,"WC2018",1),
    ("2018-07-03","Sweden","Switzerland",1,0,"WC2018",1),
    ("2018-07-03","Colombia","England",1,1,"WC2018",1),
    # Quarter-finals
    ("2018-07-06","Uruguay","France",0,2,"WC2018",1),
    ("2018-07-06","Brazil","Belgium",1,2,"WC2018",1),
    ("2018-07-07","Sweden","England",0,2,"WC2018",1),
    ("2018-07-07","Russia","Croatia",2,2,"WC2018",1),
    # Semi-finals
    ("2018-07-10","France","Belgium",1,0,"WC2018",1),
    ("2018-07-11","Croatia","England",2,1,"WC2018",1),
    # Third place
    ("2018-07-14","Belgium","England",2,0,"WC2018",1),
    # Final
    ("2018-07-15","France","Croatia",4,2,"WC2018",1),
]

WC2014 = [
    ("2014-06-12","Brazil","Croatia",3,1,"WC2014",1),
    ("2014-06-12","Mexico","Cameroon",1,0,"WC2014",1),
    ("2014-06-13","Spain","Netherlands",1,5,"WC2014",1),
    ("2014-06-13","Chile","Australia",3,1,"WC2014",1),
    ("2014-06-14","Colombia","Greece",3,0,"WC2014",1),
    ("2014-06-14","Uruguay","Costa Rica",1,3,"WC2014",1),
    ("2014-06-14","England","Italy",1,2,"WC2014",1),
    ("2014-06-15","Ivory Coast","Japan",2,1,"WC2014",1),
    ("2014-06-15","Switzerland","Ecuador",2,1,"WC2014",1),
    ("2014-06-15","France","Honduras",3,0,"WC2014",1),
    ("2014-06-16","Argentina","Bosnia and Herzegovina",2,1,"WC2014",1),
    ("2014-06-16","Iran","Nigeria",0,0,"WC2014",1),
    ("2014-06-16","Germany","Portugal",4,0,"WC2014",1),
    ("2014-06-17","Ghana","USA",1,2,"WC2014",1),
    ("2014-06-17","Belgium","Algeria",2,1,"WC2014",1),
    ("2014-06-17","Brazil","Mexico",0,0,"WC2014",1),
    ("2014-06-18","Russia","South Korea",1,1,"WC2014",1),
    ("2014-06-18","Australia","Netherlands",2,3,"WC2014",1),
    ("2014-06-18","Spain","Chile",0,2,"WC2014",1),
    ("2014-06-19","Cameroon","Croatia",0,4,"WC2014",1),
    ("2014-06-19","Colombia","Ivory Coast",2,1,"WC2014",1),
    ("2014-06-19","Uruguay","England",2,1,"WC2014",1),
    ("2014-06-20","Japan","Greece",0,0,"WC2014",1),
    ("2014-06-20","Italy","Costa Rica",0,1,"WC2014",1),
    ("2014-06-20","Switzerland","France",5,2,"WC2014",1),
    ("2014-06-21","Honduras","Ecuador",1,2,"WC2014",1),
    ("2014-06-21","Argentina","Iran",1,0,"WC2014",1),
    ("2014-06-21","Germany","Ghana",2,2,"WC2014",1),
    ("2014-06-22","Nigeria","Bosnia and Herzegovina",1,0,"WC2014",1),
    ("2014-06-22","Belgium","Russia",1,0,"WC2014",1),
    ("2014-06-22","South Korea","Algeria",2,4,"WC2014",1),
    ("2014-06-22","USA","Portugal",2,2,"WC2014",1),
    ("2014-06-23","Australia","Spain",0,3,"WC2014",1),
    ("2014-06-23","Netherlands","Chile",2,0,"WC2014",1),
    ("2014-06-23","Cameroon","Brazil",1,4,"WC2014",1),
    ("2014-06-23","Croatia","Mexico",1,3,"WC2014",1),
    ("2014-06-24","Italy","Uruguay",0,1,"WC2014",1),
    ("2014-06-24","Costa Rica","England",0,0,"WC2014",1),
    ("2014-06-24","Japan","Colombia",1,4,"WC2014",1),
    ("2014-06-24","Greece","Ivory Coast",2,1,"WC2014",1),
    ("2014-06-25","Nigeria","Argentina",2,3,"WC2014",1),
    ("2014-06-25","Bosnia and Herzegovina","Iran",3,1,"WC2014",1),
    ("2014-06-25","Honduras","Switzerland",0,3,"WC2014",1),
    ("2014-06-25","Ecuador","France",0,0,"WC2014",1),
    ("2014-06-26","Algeria","Russia",1,1,"WC2014",1),
    ("2014-06-26","South Korea","Belgium",0,1,"WC2014",1),
    ("2014-06-26","USA","Germany",0,1,"WC2014",1),
    ("2014-06-26","Ghana","Portugal",1,2,"WC2014",1),
    # Round of 16
    ("2014-06-28","Brazil","Chile",1,1,"WC2014",1),
    ("2014-06-28","Colombia","Uruguay",2,0,"WC2014",1),
    ("2014-06-29","Netherlands","Mexico",2,1,"WC2014",1),
    ("2014-06-29","Costa Rica","Greece",1,1,"WC2014",1),
    ("2014-06-30","France","Nigeria",2,0,"WC2014",1),
    ("2014-06-30","Germany","Algeria",2,1,"WC2014",1),
    ("2014-07-01","Argentina","Switzerland",1,0,"WC2014",1),
    ("2014-07-01","Belgium","USA",2,1,"WC2014",1),
    # Quarter-finals
    ("2014-07-04","France","Germany",0,1,"WC2014",1),
    ("2014-07-04","Brazil","Colombia",2,1,"WC2014",1),
    ("2014-07-05","Argentina","Belgium",1,0,"WC2014",1),
    ("2014-07-05","Netherlands","Costa Rica",0,0,"WC2014",1),
    # Semi-finals
    ("2014-07-08","Brazil","Germany",1,7,"WC2014",1),
    ("2014-07-09","Netherlands","Argentina",0,0,"WC2014",1),
    # Third place
    ("2014-07-12","Brazil","Netherlands",0,3,"WC2014",1),
    # Final
    ("2014-07-13","Germany","Argentina",1,0,"WC2014",1),
]

# ---------------------------------------------------------------------------
# Teams for synthetic data (English names — matches normalization aliases)
# ---------------------------------------------------------------------------

TEAMS_EN = [
    "Argentina","Brazil","Uruguay","Colombia","Ecuador","Venezuela",
    "Mexico","United States","Canada","Panama","Jamaica","Honduras",
    "Germany","England","France","Spain","Portugal","Netherlands",
    "Switzerland","Serbia","Austria","Belgium","Denmark","Turkey",
    "Poland","Croatia","Scotland","Hungary","Slovenia","Albania",
    "Morocco","Senegal","Nigeria","Cameroon","Egypt","Ghana",
    "Ivory Coast","Mali","South Africa","Algeria","Tunisia",
    "Japan","South Korea","Australia","Iran","Saudi Arabia",
    "Jordan","Iraq","Uzbekistan","New Zealand","Qatar",
    "Italy","Russia","Sweden","Costa Rica","Iceland",
    "Bosnia and Herzegovina","Greece","Peru","Chile",
]

TOURNAMENTS_SYNTH = [
    "UEFA Nations League A","UEFA Nations League B",
    "CONMEBOL Qualifiers WC2026","UEFA Qualifiers WC2026",
    "CAF Qualifiers WC2026","AFC Qualifiers WC2026",
    "CONCACAF Qualifiers WC2026","International Friendly",
    "Copa America 2024","EURO 2024","AFCON 2024","Asian Cup 2023",
]


def _synthetic_rows(n: int, seed: int = 42) -> list[tuple]:
    rng = random.Random(seed)
    start = date(2018, 7, 16)
    end = date(2026, 6, 10)
    delta = (end - start).days
    rows = []
    while len(rows) < n:
        d = start + timedelta(days=rng.randint(0, delta))
        home, away = rng.sample(TEAMS_EN, 2)
        # Realistic score distribution
        hg = rng.choices([0,1,2,3,4,5], weights=[25,30,22,14,6,3])[0]
        ag = rng.choices([0,1,2,3,4,5], weights=[25,30,22,14,6,3])[0]
        tourn = rng.choice(TOURNAMENTS_SYNTH)
        rows.append((d.isoformat(), home, away, hg, ag, tourn, 1))
    return rows


def generate(output_path: Path = OUTPUT) -> int:
    all_rows = list(WC2022) + list(WC2018) + list(WC2014)
    # Fill to 620 rows with synthetic data
    needed = max(0, 620 - len(all_rows))
    all_rows.extend(_synthetic_rows(needed, seed=2026))
    # De-duplicate by (date, home, away)
    seen: set[tuple] = set()
    deduped = []
    for r in all_rows:
        key = (r[0], r[1], r[2])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date","home_team","away_team","home_goals","away_goals","tournament","neutral"])
        w.writerows(deduped)
    return len(deduped)


if __name__ == "__main__":
    n = generate()
    print(f"Generated {n} historical match records → {OUTPUT}")
