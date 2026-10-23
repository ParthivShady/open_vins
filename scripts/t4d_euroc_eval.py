#!/usr/bin/env python3
"""NavCore T.4d real data: trajectory error of OpenVINS runs on EuRoC, and the summary across runs.
Usage:  t4d_euroc_eval.py run <run_dir> <groundtruth.csv>     one run: writes <run_dir>/ate.txt
        t4d_euroc_eval.py summary [seq ...]                   all runs under results/t4d_euroc (default: every sequence)
        t4d_euroc_eval.py pick <seq> <fixed|g1c|pfr>               the calibration choice (rule below), printed as a config name
        t4d_euroc_eval.py selftest
Run 0 of every configuration is a logged check run and is left out of all statistics (logging can slow real-time runs).
Calibration rule (fixed 18 Oct before any calibration run): the configuration with the lowest median position error
over runs 1-N wins; if others are within 2% of it, prefer for fixed noise the value closest to 1.0 px (the OpenVINS
default) and for G1c the smallest multiplier (the smallest change from fixed noise).
Error: absolute trajectory error after the standard 4-DOF alignment for VIO (yaw and translation), position RMSE in m
and orientation RMSE in degrees. Estimate: OpenVINS state file (t, JPL q_GtoI x y z w, p_IinG; the JPL q_GtoI numbers
read as a Hamilton quaternion give R_ItoG). Ground truth: EuRoC csv (ns, p, q w x y z; body = IMU).
Summary: per configuration the median and spread over repeated runs (real-data runs vary from run to run), a
Mann-Whitney test of G1c against stock and against fixed 1.5 px, and the share of G1c feature rows that were raised
above the configured 1 px."""
import csv, glob, gzip, math, os, sys
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.stats import mannwhitneyu, wilcoxon

RES = os.environ.get('T4D_EUROC_RES') or os.path.expanduser(os.environ.get('T4D_RES', '~/navcore_ws/results')) + '/t4d_euroc'


def load_est(p):
    a = np.loadtxt(p, comments='#', ndmin=2)
    return a[:, 0], a[:, 5:8], Rotation.from_quat(a[:, 1:5])          # R_ItoG


def load_gt(p):
    rows = [l.split(',') for l in open(p) if l.strip() and not l.lstrip().startswith('#')]
    a = np.array([[float(x) for x in r[:8]] for r in rows])
    t = a[:, 0] * (1e-9 if a[0, 0] > 1e12 else 1.0)
    return t, a[:, 1:4], Rotation.from_quat(a[:, [5, 6, 7, 4]])      # csv has w x y z


def ate(te, pe, Re, tg, pg, Rg, tol=0.005):
    i = np.clip(np.searchsorted(tg, te), 1, len(tg) - 1)
    j = np.where(np.abs(tg[i - 1] - te) < np.abs(tg[i] - te), i - 1, i)
    ok = np.abs(tg[j] - te) <= tol
    if ok.sum() < 50:
        raise ValueError(f'only {ok.sum()} estimates matched ground truth in time')
    pe, Re, pg, Rg = pe[ok], Re[ok], pg[j[ok]], Rg[j[ok]]
    me, mg = pe.mean(0), pg.mean(0)
    A, B = pe - me, pg - mg
    th = math.atan2(np.sum(A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]), np.sum(A[:, 0] * B[:, 0] + A[:, 1] * B[:, 1]))
    Rz = Rotation.from_euler('z', th)
    t = mg - Rz.apply(me)
    pos = math.sqrt(np.mean(np.sum((pg - (Rz.apply(pe) + t)) ** 2, 1)))
    ang = (Rg.inv() * (Rz * Re)).magnitude()
    ori = math.degrees(math.sqrt(np.mean(ang ** 2)))
    return pos, ori, int(ok.sum())


def run(d, gt):
    te, pe, Re = load_est(os.path.join(d, 'state_estimate.txt'))
    pos, ori, n = ate(te, pe, Re, *load_gt(gt))
    note = '' if ori < 30 else '  (orientation error implausibly large: check quaternion conventions; position is unaffected)'
    open(os.path.join(d, 'ate.txt'), 'w').write(f'{pos:.6f} {ori:.6f} {n} {te[-1] - te[0]:.1f}\n')
    print(f'{d}: position {pos:.4f} m, orientation {ori:.3f} deg, {n} poses over {te[-1] - te[0]:.0f} s{note}')


def read(p):
    if os.path.isfile(p):
        return open(p, errors='replace').read()
    if os.path.isfile(p + '.gz'):
        return gzip.open(p + '.gz', 'rt', errors='replace').read()
    return None


def raised_share(d):
    txt = read(os.path.join(d, 'gate_feat.csv'))
    if not txt:
        return math.nan
    rows = [r.split(',') for r in txt.splitlines()[1:] if r.count(',') >= 8]
    su = np.array([float(r[4]) for r in rows])
    return float(np.mean(su > su.min() * (1 + 1e-6))) if len(su) else math.nan


def runs(seq, cfg):
    vals = []
    for d in sorted(glob.glob(f'{RES}/{seq}/{cfg}/run*')):
        if os.path.basename(d) == 'run0':
            continue
        t = read(os.path.join(d, 'ate.txt'))
        if t:
            vals.append([float(x) for x in t.split()[:2]])
    return np.array(vals).reshape(-1, 2)


def runs_by(seq, cfg):
    """{run number: position error} for runs 1..N (Monte Carlo runs are paired across settings by run number = seed)"""
    out = {}
    for d in glob.glob(f'{RES}/{seq}/{cfg}/run*'):
        r = os.path.basename(d)[3:]
        t = read(os.path.join(d, 'ate.txt'))
        if r.isdigit() and int(r) > 0 and t:
            out[int(r)] = float(t.split()[0])
    return out


def configs(seq):
    return sorted(os.path.basename(p) for p in glob.glob(f'{RES}/{seq}/*') if os.path.isdir(p))


def summary(seqs):
    seqs = seqs or sorted(os.path.basename(p) for p in glob.glob(RES + '/*') if os.path.isdir(p))
    for seq in seqs:
        print(f'== {seq}   (runs 1-N; run 0 is the logged check run)')
        res = {c: runs(seq, c) for c in configs(seq)}
        for c, v in res.items():
            if len(v):
                q = np.percentile(v[:, 0], [25, 50, 75])
                print(f'   {c:16s} {len(v):2d} runs | position median {q[1]:.4f} m (IQR {q[0]:.4f}-{q[2]:.4f}) | '
                      f'orientation median {np.median(v[:, 1]):.3f} deg')
        pairs = [(g, b) for g in res if g.startswith('g1c') for b in res if b.startswith('fixed') or b == 'stock']
        pairs += [(g, b) for g in res if g.startswith('g1c') for b in res if b.startswith('pfr')]
        pairs += [(g, b) for g in res if g.startswith('pfr') for b in res if b.startswith('fixed') or b == 'stock']
        for g, b in pairs:
            pg, pb = runs_by(seq, g), runs_by(seq, b)
            common = sorted(set(pg) & set(pb))
            if len(common) >= 5:
                a, c = np.array([pg[k] for k in common]), np.array([pb[k] for k in common])
                rel = np.median(a) / np.median(c) - 1
                pw = wilcoxon(a, c).pvalue if np.any(a != c) else 1.0
                print(f'   {g} against {b}: median position {100 * rel:+.1f}%{"*" if pw < 0.05 else " "} '
                      f'(paired by seed, Wilcoxon p {pw:.2g}, lower in {int((a < c).sum())}/{len(common)})')
            elif len(res[g]) >= 3 and len(res[b]) >= 3:
                rel = np.median(res[g][:, 0]) / np.median(res[b][:, 0]) - 1
                p = mannwhitneyu(res[g][:, 0], res[b][:, 0]).pvalue
                print(f'   {g} against {b}: median position {100 * rel:+.1f}% (Mann-Whitney p {p:.2g})')
            elif len(res[g]) >= 1 and len(res[b]) >= 1:
                rel = np.median(res[g][:, 0]) / np.median(res[b][:, 0]) - 1
                print(f'   {g} against {b}: position {100 * rel:+.1f}% (single deterministic runs)')
        for g in [c for c in res if c.startswith('g1c') or c.startswith('pfr')]:
            sh = [raised_share(d) for d in sorted(glob.glob(f'{RES}/{seq}/{g}/run*'))]
            sh = [x for x in sh if np.isfinite(x)]
            if sh:
                print(f'   {g}: share of MSCKF feature rows raised above its floor: {100 * np.mean(sh):.1f}% (logged runs)')


def pick(seq, kind):
    meds = {c: float(np.median(v[:, 0])) for c in configs(seq) if c.startswith(kind) for v in [runs(seq, c)] if len(v) >= 1}
    if not meds:
        sys.exit(f'no {kind} configurations with runs for {seq}')
    best = min(meds, key=meds.get)
    near = [c for c in meds if meds[c] <= 1.02 * meds[best]]
    if kind == 'fixed':
        choice = min(near, key=lambda c: (abs(float(c[5:]) - 1.0), meds[c]))
    else:
        choice = min(near, key=lambda c: (float(c.split('_b')[1].split('_')[0]), meds[c]))
    print(choice)
    print('   ' + ', '.join(f'{c} {m:.4f}' for c, m in sorted(meds.items())) + f'  -> {choice}', file=sys.stderr)


def selftest():
    rng = np.random.default_rng(3)
    n = 4000
    tg = np.arange(n) / 200.0 + 1403636580.0
    pg = np.c_[np.cumsum(rng.normal(0, 0.01, n)), np.cumsum(rng.normal(0, 0.01, n)), 1 + 0.2 * np.sin(np.arange(n) / 300)]
    Rg = Rotation.from_euler('zyx', np.c_[np.cumsum(rng.normal(0, 0.01, n)), rng.normal(0, 0.05, n), rng.normal(0, 0.05, n)])
    # estimate: every 10th pose, in a frame rotated by 40 deg yaw and shifted, with 3 cm position noise and 0.5 deg
    th, sh = math.radians(40), np.array([2.0, -1.0, 0.3])
    Rz = Rotation.from_euler('z', th)
    k = np.arange(0, n, 10)
    pe = Rz.inv().apply(pg[k] - sh) + rng.normal(0, 0.03, (len(k), 3))
    Re = Rz.inv() * Rg[k] * Rotation.from_rotvec(rng.normal(0, math.radians(0.5), (len(k), 3)))
    pos, ori, m = ate(tg[k] + 0.001, pe, Re, tg, pg, Rg)
    print(f'self-test: position {pos:.4f} m (expected about {0.03 * math.sqrt(3):.4f}), orientation {ori:.3f} deg '
          f'(expected about {0.5 * math.sqrt(3):.3f}), {m} poses matched')


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'run' and len(sys.argv) == 4:
        run(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == 'pick':
        pick(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == 'summary':
        summary(sys.argv[2:])
    elif len(sys.argv) == 2 and sys.argv[1] == 'selftest':
        selftest()
    else:
        sys.exit(__doc__)
