#!/usr/bin/env python3
"""T.3 annotated plot — presentation-ready, mixed-audience.

Two panels tell a two-sentence story:
  Left:  "When camera tracking gets noisier, the drone's position error
          stays small — until suddenly it doesn't."
  Right: "And when the drone is most lost, it's also most confident
          that it isn't."
"""
import csv
from pathlib import Path
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CSV_PATH = Path.home() / "navcore_ws/results/t3_sweep_results.csv"
OUT_PNG  = Path.home() / "navcore_ws/results/t3_annotated_plot.png"

by_sigma = defaultdict(lambda: {"ate": [], "nees_pos": []})
with CSV_PATH.open() as f:
    for row in csv.DictReader(f):
        s = float(row["sigma"])
        by_sigma[s]["ate"].append(float(row["pos_rmse_m"]))
        by_sigma[s]["nees_pos"].append(float(row["pos_nees_avg"]))

sigmas = sorted(by_sigma.keys())
ate_med = np.array([np.median(by_sigma[s]["ate"]) for s in sigmas])
ate_lo  = np.array([min(by_sigma[s]["ate"])       for s in sigmas])
ate_hi  = np.array([max(by_sigma[s]["ate"])       for s in sigmas])
pos_med = np.array([np.median(by_sigma[s]["nees_pos"]) for s in sigmas])
pos_lo  = np.array([min(by_sigma[s]["nees_pos"])       for s in sigmas])
pos_hi  = np.array([max(by_sigma[s]["nees_pos"])       for s in sigmas])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
plt.rcParams.update({'font.size': 11})

# ============ LEFT PANEL — how lost the drone is ============
ax1.errorbar(sigmas, ate_med,
             yerr=[ate_med - ate_lo, ate_hi - ate_med],
             fmt='o-', color='#1f4e79', capsize=5, linewidth=2.5, markersize=9)
ax1.axvspan(1.5, 1.75, alpha=0.18, color='red')
ax1.set_yscale('log')

# Region labels
ax1.text(1.2, 0.012, 'DRONE STAYS ON TRACK',
         fontsize=11, ha='center', color='#1a5f1a', fontweight='bold',
         bbox=dict(boxstyle='round,pad=0.4', facecolor='#e8f5e8', edgecolor='#1a5f1a'))
ax1.text(2.4, 40000, 'DRONE COMPLETELY LOST',
         fontsize=11, ha='center', color='#8b0000', fontweight='bold',
         bbox=dict(boxstyle='round,pad=0.4', facecolor='#fde8e8', edgecolor='#8b0000'))

# The cliff arrow — annotate the jump from σ=1.5 to σ=1.75
ax1.annotate('',
             xy=(1.72, ate_med[3] * 0.6), xytext=(1.53, ate_med[2] * 1.6),
             arrowprops=dict(arrowstyle='->', color='red', lw=2.5))
ax1.text(1.625, 15, 'Sudden\nfailure',
         fontsize=11, ha='center', color='red', fontweight='bold')

# Reference: trajectory length
ax1.axhline(225, color='gray', linestyle=':', linewidth=1.5, alpha=0.7)
ax1.text(3.02, 225, 'Full trajectory\nlength (225 m)',
         fontsize=9, va='center', ha='left', color='gray', style='italic')

# Callout for the good region
ax1.annotate('At clean tracking:\n5 cm error over 225 m',
             xy=(1.0, 0.05), xytext=(1.15, 0.0018),
             fontsize=10, ha='center', color='#1a5f1a',
             arrowprops=dict(arrowstyle='->', color='#1a5f1a', lw=1.2))

ax1.set_xlabel('Camera tracking noise level (pixels)', fontsize=12)
ax1.set_ylabel("Drone's position error (metres, log scale)", fontsize=12)
ax1.set_title('How far the drone drifts from its true position',
              fontsize=13, fontweight='bold', pad=12)
ax1.grid(True, which='major', alpha=0.3)
ax1.set_xlim(0.9, 3.25)
ax1.set_ylim(0.001, 300000)

# ============ RIGHT PANEL — how confident the filter is ============
# Convert NEES to "confidence error" narrative:
# NEES = 3 means honest self-assessment. NEES > 3 means falsely over-confident.
# Present as ratio: NEES / 3, log scale.
overconfidence = pos_med / 3.0
ovc_lo = pos_lo / 3.0
ovc_hi = pos_hi / 3.0

ax2.errorbar(sigmas, overconfidence,
             yerr=[overconfidence - ovc_lo, ovc_hi - overconfidence],
             fmt='o-', color='#7a1f7a', capsize=5, linewidth=2.5, markersize=9)
ax2.axvspan(1.5, 1.75, alpha=0.18, color='red')
ax2.axhline(1.0, color='green', linestyle='--', linewidth=2, alpha=0.8)
ax2.set_yscale('log')

# Honest zone label
ax2.text(1.05, 1.0, 'Honest self-assessment',
         fontsize=9, va='center', ha='left', color='#1a5f1a',
         bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#1a5f1a', alpha=0.9))

# Overconfident zone label
ax2.text(2.4, 200, 'FILTER THINKS IT KNOWS\nWHERE IT IS —\nBUT IT DOESN\'T',
         fontsize=11, ha='center', color='#8b0000', fontweight='bold',
         bbox=dict(boxstyle='round,pad=0.4', facecolor='#fde8e8', edgecolor='#8b0000'))

# Cliff arrow on this panel too
ax2.annotate('',
             xy=(1.72, overconfidence[3] * 0.6), xytext=(1.53, overconfidence[2] * 1.6),
             arrowprops=dict(arrowstyle='->', color='red', lw=2.5))
ax2.text(1.625, 2.5, 'Same\ncliff',
         fontsize=11, ha='center', color='red', fontweight='bold')

ax2.set_xlabel('Camera tracking noise level (pixels)', fontsize=12)
ax2.set_ylabel("How overconfident the filter is\n(1 = honest, higher = falsely confident, log scale)",
               fontsize=12)
ax2.set_title("Does the drone realise it's lost?",
              fontsize=13, fontweight='bold', pad=12)
ax2.grid(True, which='major', alpha=0.3)
ax2.set_xlim(0.9, 3.25)
ax2.set_ylim(0.1, 500)

# ============ Overall framing ============
fig.suptitle(
    "Stereo camera-based drone navigation: a hidden failure mode\n"
    "When the vision system's assumed noise doesn't match reality, the filter fails suddenly and silently",
    fontsize=13.5, y=1.01, fontweight='bold'
)

# Footer with methodology in one line
fig.text(0.5, -0.02,
         "Simulated warehouse trajectory (225 m, stereo cameras). "
         "Filter assumes clean 1-pixel tracking; camera noise swept from 1 to 3 pixels. "
         "3 random seeds per noise level; bars show min–max spread.",
         ha='center', fontsize=9, style='italic', color='#555555')

fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150, bbox_inches='tight')
print(f"wrote {OUT_PNG}")
