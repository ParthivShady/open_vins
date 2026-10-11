#!/usr/bin/env python3
"""T.4a summary: oracle per-feature noise (T.4a) vs fixed R (T.3b), paired by seed, udel_gore.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4a_summary.py
Writes ~/navcore_ws/results/t4a_summary.csv."""
import os, sys, subprocess, csv, math
import numpy as np
import gzip
def opentext(p):
    """Open a text file, or its .gz copy if only that exists."""
    return gzip.open(p + '.gz', 'rt') if not os.path.exists(p) and os.path.exists(p + '.gz') else open(p)
try:
    from scipy import stats
except ImportError:
    stats = None

HOME = os.path.expanduser('~')
RES = os.path.join(HOME, 'navcore_ws/results')
T3B = os.path.join(RES, 't3b/udel_gore')
T4A = os.path.join(RES, 't4a_t3bgrid/udel_gore')
ATE = os.path.join(HOME, 'navcore_ws/src/open_vins/scripts/t3_ate.py')
SEEDS = list(range(1, 31))
CELLS = [(0.25, 1.25), (0.25, 1.5), (0.25, 2.5), (0.5, 1.25), (0.5, 1.5), (0.5, 2.5)]
NPTS = ['', '60']
DIVERGED_M = 10.0

def cond(f, b, npts):
    return 'sig1.000_f%.3f_bad%.3f' % (f, b) + ('_n' + npts if npts else '')

def run_dirs(root, c):
    return [os.path.join(root, c, 'seed%d' % s) for s in SEEDS]

def ate_many(dirs):
    """t3_ate.py on many run folders -> {dir: (pos_m, ori_deg)}; missing runs are skipped."""
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, 'state_estimate.txt'))]
    out = subprocess.run([sys.executable, ATE] + dirs, capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        p = line.split('\t')
        if len(p) >= 3:
            try:
                res[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))
            except ValueError:
                pass
    return res

def tcrit(n):
    return stats.t.ppf(0.975, n - 1) if stats else (2.045 if n == 30 else 1.96)

def paired(a, b):
    """Mean of (b - a), 95% CI half-width, t-test p, Wilcoxon p."""
    d = b - a; n = len(d)
    ci = tcrit(n) * d.std(ddof=1) / math.sqrt(n)
    pt = stats.ttest_rel(b, a).pvalue if stats else float('nan')
    pw = stats.wilcoxon(b, a).pvalue if stats else float('nan')
    return d.mean(), ci, pt, pw

def gate_overall(dirs):
    """Aggregate MSCKF acceptance from gate.csv (n_gate_passed / n_after_tri)."""
    tri = passed = 0
    for d in dirs:
        p = os.path.join(d, 'gate.csv')
        if not (os.path.exists(p) or os.path.exists(p + '.gz')):
            continue
        with opentext(p) as fh:
            next(fh)
            for line in fh:
                r = line.split(',')
                try:
                    a, b = float(r[3]), float(r[4])
                except (ValueError, IndexError):
                    continue
                if a >= 0 and b >= 0:  # -1 = update ended before this stage; not a count
                    tri += a; passed += b
    return 100 * passed / tri if tri else float('nan')

def gate_groups(dirs):
    """Per-feature logs -> {(kind, noisy): [n, accepted, sum chi2/dof]}; kind 0 MSCKF, 1 SLAM upd, 2 SLAM init."""
    acc = {}
    for d in dirs:
        for fn in ('gate_feat.csv', 'gate_slam.csv'):
            p = os.path.join(d, fn)
            if not (os.path.exists(p) or os.path.exists(p + '.gz')):
                continue
            with opentext(p) as fh:
                next(fh)
                for line in fh:
                    t, kind, fid, st, su, dof, chi2, thr, a = line.rstrip('\n').split(',')
                    v = acc.setdefault((kind, st != '1'), [0, 0, 0.0])
                    v[0] += 1; v[1] += int(a)
                    if kind != '2':
                        v[2] += float(chi2) / int(dof)
    return acc

def pct(acc, kind, noisy):
    v = acc.get((kind, noisy))
    return '%5.1f%%' % (100 * v[1] / v[0]) if v and v[0] else '   n/a'

def chi(acc, kind, noisy):
    v = acc.get((kind, noisy))
    return '%.2f' % (v[2] / v[0]) if v and v[0] else 'n/a'

rows = []
print('T.4a oracle vs T.3b fixed R | udel_gore | paired by seed (30) | scipy: %s' % ('yes' if stats else 'no (CI uses t=2.045, no p-values)'))
for npts in NPTS:
    label = npts if npts else '250'
    uni_dirs = run_dirs(T3B, cond(0.0, 1.0, npts))
    uni = ate_many(uni_dirs)
    print('\n================ num_pts %s ================' % label)
    for f, b in CELLS:
        c = cond(f, b, npts)
        fx_dirs, or_dirs = run_dirs(T3B, c), run_dirs(T4A, c)
        fx, orc = ate_many(fx_dirs), ate_many(or_dirs)
        keep, div = [], 0
        for s, u, x, o in zip(SEEDS, uni_dirs, fx_dirs, or_dirs):
            u, x, o = os.path.normpath(u), os.path.normpath(x), os.path.normpath(o)
            if u not in uni or x not in fx or o not in orc:
                continue
            if max(uni[u][0], fx[x][0], orc[o][0]) > DIVERGED_M:
                div += 1; continue
            keep.append((uni[u], fx[x], orc[o]))
        n = len(keep)
        print('\n-- f=%.2f  sigma_bad=%.2f  | pairs used %d/30, diverged %d' % (f, b, n, div))
        if n < 3:
            continue
        for k, name, unit in ((0, 'pos', 'm'), (1, 'ori', 'deg')):
            U = np.array([r[0][k] for r in keep]); X = np.array([r[1][k] for r in keep]); O = np.array([r[2][k] for r in keep])
            dm, dci, pt, pw = paired(X, O)        # oracle - fixed
            pm, pci, _, _ = paired(U, X)          # fixed - uniform (the T.3b penalty)
            clear_penalty = pm - pci > 0
            rec = (X.mean() - O.mean()) / (X.mean() - U.mean()) if clear_penalty else float('nan')
            wins = int((O < X).sum())
            print('   %s: uniform %.4f | fixed %.4f+-%.4f | oracle %.4f+-%.4f %s' % (name, U.mean(), X.mean(), X.std(ddof=1), O.mean(), O.std(ddof=1), unit))
            print('        oracle-fixed %+.4f [+-%.4f] p_t=%.1e p_w=%.1e wins %d/%d | penalty %+.4f [+-%.4f] | recovered %s'
                  % (dm, dci, pt, pw, wins, n, pm, pci, ('%.0f%%' % (100 * rec)) if clear_penalty else 'n/a (no clear penalty)'))
            rows.append(dict(npts=label, f=f, sigma_bad=b, metric=name, n_pairs=n, diverged=div,
                             uniform_mean=U.mean(), fixed_mean=X.mean(), fixed_std=X.std(ddof=1),
                             oracle_mean=O.mean(), oracle_std=O.std(ddof=1), delta_mean=dm, delta_ci95=dci,
                             p_ttest=pt, p_wilcoxon=pw, oracle_wins=wins, penalty_mean=pm, penalty_ci95=pci,
                             recovered_frac=rec))
        g = gate_groups(or_dirs)
        print('   gates  MSCKF overall: fixed %.1f%% -> oracle %.1f%%' % (gate_overall(fx_dirs), gate_overall(or_dirs)))
        print('          oracle by group (clean / noisy): MSCKF %s / %s (chi2/dof %s / %s) | SLAM upd %s / %s | SLAM init %s / %s'
              % (pct(g, '0', False), pct(g, '0', True), chi(g, '0', False), chi(g, '0', True),
                 pct(g, '1', False), pct(g, '1', True), pct(g, '2', False), pct(g, '2', True)))

out = os.path.join(RES, 't4a_summary.csv')
with open(out, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('\nwrote', out)
