#!/usr/bin/env python3
"""T.3 ATE evaluator: position/orientation RMSE from saved state files (not from run.log).

run.log result lines can be corrupted by the ROS2 shutdown segfault interleaving its message,
so ATE is computed directly from state_estimate.txt vs state_groundtruth.txt.
Format (both files): col 0 timestamp, cols 1-4 quaternion, cols 5-7 position.
Rows matched by exact timestamp. No alignment: the simulator initialises the filter at truth,
matching OpenVINS's own simulation evaluator.
Usage: t3_ate.py <run_dir> [<run_dir> ...]   -> prints: run_dir  ate_pos_m  ate_rot_deg  n_matched
"""
import sys, numpy as np

def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            v = line.split()
            rows[round(float(v[0]) * 1e4)] = np.array(v[1:8], dtype=float)  # q(4), p(3)
    return rows

def ate(run_dir):
    est = load(f"{run_dir}/state_estimate.txt")
    gt = load(f"{run_dir}/state_groundtruth.txt")
    keys = sorted(set(est) & set(gt))
    if not keys:
        return float("nan"), float("nan"), 0
    E = np.array([est[k] for k in keys]); G = np.array([gt[k] for k in keys])
    dp = E[:, 4:7] - G[:, 4:7]
    pos = float(np.sqrt(np.mean(np.sum(dp**2, axis=1))))
    qe = E[:, 0:4] / np.linalg.norm(E[:, 0:4], axis=1, keepdims=True)
    qg = G[:, 0:4] / np.linalg.norm(G[:, 0:4], axis=1, keepdims=True)
    ang = 2.0 * np.degrees(np.arccos(np.clip(np.abs(np.sum(qe * qg, axis=1)), 0.0, 1.0)))
    rot = float(np.sqrt(np.mean(ang**2)))
    return pos, rot, len(keys)

if __name__ == "__main__":
    for d in sys.argv[1:]:
        p, r, n = ate(d.rstrip("/"))
        print(f"{d}\t{p:.4f}\t{r:.4f}\t{n}")
