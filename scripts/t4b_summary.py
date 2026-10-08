#!/usr/bin/env python3
"""T.4b summary: fixed R (T.3b) vs per-frame pooled (T.4b) vs per-feature (T.4a), paired by seed, udel_gore. Tests P5.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4b_summary.py
Writes ~/navcore_ws/results/t4b_summary.csv."""
import os, sys, subprocess, csv, math
import numpy as np
try:
    from scipy import stats
except ImportError:
    stats = None

HOME = os.path.expanduser('~')
RES = os.path.join(HOME, 'navcore_ws/results')
T3B = os.path.join(RES, 't3b/udel_gore')
T4A = os.path.join(RES, 't4a_t3bgrid/udel_gore')
T4B = os.path.join(RES, 't4b_t3bgrid/udel_gore')
ATE = os.path.join(HOME, 'navcore_ws/src/open_vins/scripts/t3_ate.py')
SEEDS = list(range(1, 31))
CELLS = [(0.25, 1.25), (0.25, 1.5), (0.25, 2.5), (0.5, 1.25), (0.5, 1.5), (0.5, 2.5)]
NPTS = ['', '60']
DIVERGED_M = 10.0

def cond(f, b, npts):
    return 'sig1.000_f%.3f_bad%.3f' % (f, b) + ('_n' + npts if npts else '')

def run_dirs(root, c):
    return [os.path.normpath(os.path.join(root, c, 'seed%d' % s)) for s in SEEDS]

def ate_many(dirs):
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
    tri = passed = 0
    for d in dirs:
        p = os.path.join(d, 'gate.csv')
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            next(fh)
            for line in fh:
                r = line.split(',')
                try:
                    a, b = float(r[3]), float(r[4])
                except (ValueError, IndexError):
                    continue
                if a >= 0 and b >= 0:
                    tri += a; passed += b
    return 100 * passed / tri if tri else float('nan')

def gate_groups(dirs):
    acc = {}
    for d in dirs:
        for fn in ('gate_feat.csv', 'gate_slam.csv'):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            with open(p) as fh:
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
    return '%.1f%%' % (100 * v[1] / v[0]) if v and v[0] else 'n/a'

def chi(acc, kind, noisy):
    v = acc.get((kind, noisy))
    return '%.2f' % (v[2] / v[0]) if v and v[0] else 'n/a'

def fmt_rec(r):
    return 'n/a' if r != r else '%.0f%%' % (100 * r)

rows = []
rel = {g: {'pos': {}, 'ori': {}} for g in ('f=0.50 cells', 'all cells')}
cellwins = {'pos': 0, 'ori': 0}; ncells = 0
print('T.4b: fixed (T.3b) vs pooled (T.4b) vs per-feature (T.4a) | udel_gore | paired by seed | scipy: %s' % ('yes' if stats else 'no'))
for npts in NPTS:
    label = npts if npts else '250'
    uni_dirs = run_dirs(T3B, cond(0.0, 1.0, npts)); uni = ate_many(uni_dirs)
    print('\n================ num_pts %s ================' % label)
    for f, b in CELLS:
        c = cond(f, b, npts)
        fx_d, pl_d, pf_d = run_dirs(T3B, c), run_dirs(T4B, c), run_dirs(T4A, c)
        fx, pl, pf = ate_many(fx_d), ate_many(pl_d), ate_many(pf_d)
        keep, div = [], [0, 0, 0]
        for s, u, x, p, q in zip(SEEDS, uni_dirs, fx_d, pl_d, pf_d):
            if u not in uni or x not in fx or p not in pl or q not in pf:
                continue
            vals = (uni[u], fx[x], pl[p], pf[q])
            bad = [v[0] > DIVERGED_M for v in vals[1:]]
            for i, flag in enumerate(bad):
                div[i] += flag
            if vals[0][0] > DIVERGED_M or any(bad):
                continue
            keep.append((s,) + vals)
        n = len(keep)
        print('\n-- f=%.2f  sigma_bad=%.2f | pairs used %d/30 | diverged fixed/pooled/per-feature %d/%d/%d' % (f, b, n, *div))
        if n < 3:
            continue
        ncells += 1
        S = [r[0] for r in keep]
        for k, name, unit in ((0, 'pos', 'm'), (1, 'ori', 'deg')):
            U, X, P, F = (np.array([r[i][k] for r in keep]) for i in (1, 2, 3, 4))
            pm, pci, _, _ = paired(U, X)
            clear = pm - pci > 0
            rp = (X.mean() - P.mean()) / (X.mean() - U.mean()) if clear else float('nan')
            rf = (X.mean() - F.mean()) / (X.mean() - U.mean()) if clear else float('nan')
            dm, dci, pt, pw = paired(P, F)   # per-feature minus pooled
            wins = int((F < P).sum())
            print('   %s: uniform %.4f | fixed %.4f | pooled %.4f+-%.4f | per-feature %.4f+-%.4f %s'
                  % (name, U.mean(), X.mean(), P.mean(), P.std(ddof=1), F.mean(), F.std(ddof=1), unit))
            print('        penalty recovered: pooled %s, per-feature %s%s'
                  % (fmt_rec(rp), fmt_rec(rf), '' if clear else '  (no clear fixed-R penalty in this cell)'))
            print('        per-feature - pooled %+.4f [+-%.4f] p_t=%.1e p_w=%.1e | per-feature wins %d/%d' % (dm, dci, pt, pw, wins, n))
            r = (F - P) / P
            for s, v in zip(S, r):
                rel['all cells'][name].setdefault(s, []).append(v)
                if f == 0.5:
                    rel['f=0.50 cells'][name].setdefault(s, []).append(v)
            if F.mean() < P.mean():
                cellwins[name] += 1
            rows.append(dict(npts=label, f=f, sigma_bad=b, metric=name, n_pairs=n, uniform_mean=U.mean(), fixed_mean=X.mean(),
                             pooled_mean=P.mean(), pooled_std=P.std(ddof=1), perfeat_mean=F.mean(), perfeat_std=F.std(ddof=1),
                             recovered_pooled=rp, recovered_perfeat=rf, perfeat_minus_pooled=dm, ci95=dci, p_ttest=pt,
                             p_wilcoxon=pw, perfeat_wins=wins))
        gp, gf = gate_groups(pl_d), gate_groups(pf_d)
        print('   gates  MSCKF overall: fixed %.1f%% | pooled %.1f%% | per-feature %.1f%%' % (gate_overall(fx_d), gate_overall(pl_d), gate_overall(pf_d)))
        print('          MSCKF clean/noisy acceptance: pooled %s / %s (chi2/dof %s / %s) | per-feature %s / %s (chi2/dof %s / %s)'
              % (pct(gp, '0', False), pct(gp, '0', True), chi(gp, '0', False), chi(gp, '0', True),
                 pct(gf, '0', False), pct(gf, '0', True), chi(gf, '0', False), chi(gf, '0', True)))
        print('          SLAM init noisy acceptance: pooled %s | per-feature %s' % (pct(gp, '2', True), pct(gf, '2', True)))

print('\n================ OVERALL: per-feature vs pooled ================')
print('(relative difference (per-feature - pooled)/pooled, averaged over cells within each seed -> one value per seed)')
for g in rel:
    for name in ('pos', 'ori'):
        v = np.array([np.mean(x) for x in rel[g][name].values()])
        if len(v) < 3:
            continue
        ci = tcrit(len(v)) * v.std(ddof=1) / math.sqrt(len(v))
        pw = stats.wilcoxon(v).pvalue if stats else float('nan')
        print('  %-13s %s: %+.1f%% [+-%.1f%%] over %d seeds, p_w=%.1e, per-feature better in %d/%d seeds'
              % (g, name, 100 * v.mean(), 100 * ci, len(v), pw, int((v < 0).sum()), len(v)))
for name in ('pos', 'ori'):
    k = cellwins[name]
    p = float('nan')
    if stats:
        try:
            p = stats.binomtest(k, ncells, 0.5).pvalue
        except AttributeError:
            p = stats.binom_test(k, ncells, 0.5)
    print('  cells where per-feature mean < pooled mean, %s: %d/%d (sign test p=%.2g)' % (name, k, ncells, p))

out = os.path.join(RES, 't4b_summary.csv')
with open(out, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('\nwrote', out)
