#!/usr/bin/env python3
"""Parse T.3 sweep run.log files into a tidy CSV.

Reads the last 'rmse =>' and 'avg nees =>' lines from each run.log
under results/t3_sweep/sigma_*_seed_*/. Emits one row per run.
"""
import re
import csv
from pathlib import Path
import sys

RESULTS_DIR = Path.home() / "navcore_ws/results/t3_sweep"
OUT_CSV     = Path.home() / "navcore_ws/results/t3_sweep_results.csv"

RMSE_RE = re.compile(r"rmse =>\s*([\d.eE+-]+),\s*([\d.eE+-]+)\s*\(deg,m\)")
NEES_RE = re.compile(r"avg nees =\s*([\d.eE+-]+),\s*([\d.eE+-]+)\s*\(ori,pos\)")
DIR_RE  = re.compile(r"sigma_([\d.]+)_seed_(\d+)")

def parse_run(log_path):
    text = log_path.read_text()
    rmse_matches = RMSE_RE.findall(text)
    nees_matches = NEES_RE.findall(text)
    if not rmse_matches or not nees_matches:
        return None
    ori_rmse, pos_rmse = rmse_matches[-1]
    ori_nees, pos_nees = nees_matches[-1]
    return {
        "ori_rmse_deg": float(ori_rmse),
        "pos_rmse_m":   float(pos_rmse),
        "ori_nees_avg": float(ori_nees),
        "pos_nees_avg": float(pos_nees),
    }

rows = []
for run_dir in sorted(RESULTS_DIR.glob("sigma_*_seed_*")):
    m = DIR_RE.search(run_dir.name)
    if not m:
        continue
    sigma = float(m.group(1))
    seed  = int(m.group(2))
    log = run_dir / "run.log"
    if not log.exists():
        print(f"MISSING: {run_dir}", file=sys.stderr)
        continue
    parsed = parse_run(log)
    if parsed is None:
        print(f"UNPARSEABLE: {run_dir}", file=sys.stderr)
        continue
    rows.append({"sigma": sigma, "seed": seed, **parsed})

rows.sort(key=lambda r: (r["sigma"], r["seed"]))
with OUT_CSV.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"wrote {len(rows)} rows to {OUT_CSV}")
