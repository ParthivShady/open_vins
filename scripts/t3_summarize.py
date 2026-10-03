#!/usr/bin/env python3
"""T.3 summariser: one CSV row per run folder.
Walks <root>/<traj>/sig*_f*_bad*[_nN]/seed*/ and writes settings, ATE (from state files,
same method as t3_ate.py), gate statistics (gate.csv), time-to-divergence and sanity flags.
Usage: t3_summarize.py <results_root> <out_csv>
"""
import sys, re, csv, pathlib, numpy as np

COND = re.compile(r"sig([\d.]+)_f([\d.]+)_bad([\d.]+)(?:_n(\d+))?$")
DIVERGE_M = 1.0  # time-to-divergence threshold on position error (m)

def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            v = line.split()
            rows[round(float(v[0]) * 1e4)] = (float(v[0]), np.array(v[1:8], dtype=float))
    return rows

def ate_and_ttd(run):
    try:
        est, gt = load(run / "state_estimate.txt"), load(run / "state_groundtruth.txt")
    except FileNotFoundError:
        return [float("nan")] * 4 + [0]
    keys = sorted(set(est) & set(gt))
    if not keys:
        return [float("nan")] * 4 + [0]
    t = np.array([est[k][0] for k in keys])
    E = np.array([est[k][1] for k in keys]); G = np.array([gt[k][1] for k in keys])
    err = np.linalg.norm(E[:, 4:7] - G[:, 4:7], axis=1)
    pos = float(np.sqrt(np.mean(err**2)))
    qe = E[:, :4] / np.linalg.norm(E[:, :4], axis=1, keepdims=True)
    qg = G[:, :4] / np.linalg.norm(G[:, :4], axis=1, keepdims=True)
    ang = 2 * np.degrees(np.arccos(np.clip(np.abs(np.sum(qe * qg, axis=1)), 0, 1)))
    rot = float(np.sqrt(np.mean(ang**2)))
    bad = np.nonzero(err > DIVERGE_M)[0]
    ttd = float(t[bad[0]] - t[0]) if len(bad) else float("nan")
    duration = float(t[-1] - t[0])
    return [pos, rot, ttd, duration, len(keys)]

def gate_stats(run):
    att = passed = starved = nogate = updates = 0
    try:
        with open(run / "gate.csv") as f:
            for r in csv.DictReader(f):
                ec, ntri = int(r["exit_code"]), int(r["n_after_tri"])
                if ntri > 0:
                    att += ntri; passed += int(r["n_gate_passed"])
                starved += ec == 1; nogate += ec == 4; updates += 1
    except FileNotFoundError:
        pass
    rej = (att - passed) / att if att else float("nan")
    return [att, passed, rej, starved, nogate, updates]

def log_flags(run, sig, f, bad):
    try:
        txt = (run / "run.log").read_text(errors="replace")
    except FileNotFoundError:
        return [0, 0, float("nan")]
    ok = f"sim_sigma_pix={sig} sim_bad_fraction={f} sim_sigma_bad={bad}" in txt
    m = re.search(r"^elapsed_s=(\d+)", txt, re.M)
    el = float(m.group(1)) if m else float("nan")
    timed_out = 1 if (m and el >= 900) else 0
    return [int(ok), timed_out, el]

def ttd_at(run, thr):
    """Seconds from start until position error first exceeds thr metres (nan if never)."""
    try:
        est, gt = load(run / "state_estimate.txt"), load(run / "state_groundtruth.txt")
    except FileNotFoundError:
        return float("nan")
    keys = sorted(set(est) & set(gt))
    if not keys:
        return float("nan")
    t = np.array([est[k][0] for k in keys])
    err = np.linalg.norm(np.array([est[k][1][4:7] - gt[k][1][4:7] for k in keys]), axis=1)
    bad = np.nonzero(err > thr)[0]
    return float(t[bad[0]] - t[0]) if len(bad) else float("nan")

def main(root, out):
    root = pathlib.Path(root).expanduser()
    hdr = ["traj", "sigma", "f", "sigma_bad", "num_pts", "seed", "ate_pos_m", "ate_rot_deg",
           "ttd1_s", "duration_s", "n_matched", "gate_attempted", "gate_passed", "rejection",
           "starved_updates", "nogate_updates", "updates", "noise_confirmed", "timed_out", "elapsed_s", "ttd10_s"]
    n = 0
    with open(out, "w", newline="") as fo:
        w = csv.writer(fo); w.writerow(hdr)
        for run in sorted(root.glob("*/sig*/seed*")):
            m = COND.match(run.parent.name)
            if not m:
                continue
            sig, f, bad, npts = m.group(1), m.group(2), m.group(3), m.group(4) or "250"
            seed = run.name.replace("seed", "")
            w.writerow([run.parent.parent.name, sig, f, bad, npts, seed]
                       + ate_and_ttd(run) + gate_stats(run) + log_flags(run, sig, f, bad) + [ttd_at(run, 10.0)])
            n += 1
    print(f"wrote {n} runs -> {out}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
