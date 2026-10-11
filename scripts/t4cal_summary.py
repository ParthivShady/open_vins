#!/usr/bin/env python3
"""T.4 equal calibration: per-feature vs per-frame pooled, both at beta 1.5 (calibrated on uniform noise), paired by seed.
Also per-feature@1.5 vs pooled@1.0 and vs stock fixed R. udel_gore, T.3b uneven-noise grid.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4cal_summary.py   -> writes results/t4cal_summary.csv"""
import os, sys, subprocess, csv, math
import numpy as np
import gzip
def opentext(p):
    """Open a text file, or its .gz copy if only that exists."""
    return gzip.open(p + '.gz', 'rt') if not os.path.exists(p) and os.path.exists(p + '.gz') else open(p)
from scipy import stats

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'
ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
M = {'fixed': RES + '/t3b/udel_gore', 'pooled@1.0': RES + '/t4b_t3bgrid/udel_gore', 'perfeat@1.0': RES + '/t4a_t3bgrid/udel_gore',
     'pooled@1.5': RES + '/t4cal_pooled_b1.50/udel_gore', 'perfeat@1.5': RES + '/t4cal_perfeat_b1.50/udel_gore'}
UNI = {'uniform@1.0': RES + '/t3b/udel_gore', 'uniform@1.5': RES + '/t4c_uniform_beta1.50/udel_gore'}
COMPARE = [('perfeat@1.5', 'pooled@1.5', '[P5 equal calibration]'),
           ('perfeat@1.5', 'pooled@1.0', '[vs pooled@1.0]      '),
           ('perfeat@1.5', 'fixed',      '[vs stock fixed]     ')]
SEEDS = list(range(1, 31))
CELLS = [(0.25, 1.25), (0.25, 1.5), (0.25, 2.5), (0.5, 1.25), (0.5, 1.5), (0.5, 2.5)]
NPTS = ['', '60']
DIVERGED_M = 10.0

def cond(f, b, npts):
    return 'sig1.000_f%.3f_bad%.3f' % (f, b) + ('_n' + npts if npts else '')

def dirs(root, c):
    return [os.path.normpath('%s/%s/seed%d' % (root, c, s)) for s in SEEDS]

def ate_many(ds):
    ds = [d for d in ds if os.path.exists(d + '/state_estimate.txt')]
    out = subprocess.run([sys.executable, ATE] + ds, capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        p = line.split('\t')
        if len(p) >= 3:
            res[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))
    return res

def paired(base, new):
    d = new - base; n = len(d)
    ci = stats.t.ppf(0.975, n - 1) * d.std(ddof=1) / math.sqrt(n)
    return d.mean(), ci, stats.wilcoxon(new, base).pvalue

def gate_groups(ds):
    acc = {}
    for d in ds:
        for fn in ('gate_feat.csv', 'gate_slam.csv'):
            p = d + '/' + fn
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

def g(acc, kind, noisy, what):
    v = acc.get((kind, noisy))
    if not v or not v[0]:
        return 'n/a'
    return '%.1f%%' % (100 * v[1] / v[0]) if what == 'acc' else '%.2f' % (v[2] / v[0])

rows = []
rel = {}
print('T.4 equal calibration | udel_gore | paired by seed | diverged = ATE > %.0f m excluded' % DIVERGED_M)
for npts in NPTS:
    label = npts or '250'
    print('\n================ num_pts %s ================' % label)
    for uname, uroot in UNI.items():
        u = ate_many(dirs(uroot, cond(0.0, 1.0, npts)))
        v = np.array(list(u.values()))
        print('  reference %s (all features clean): pos %.4f m, ori %.4f deg' % (uname, v[:, 0].mean(), v[:, 1].mean()))
    for f, b in CELLS:
        c = cond(f, b, npts)
        D = {m: dirs(r, c) for m, r in M.items()}
        R = {m: ate_many(D[m]) for m in M}
        keep, div = [], {m: 0 for m in M}
        for i, s in enumerate(SEEDS):
            if any(D[m][i] not in R[m] for m in M):
                continue
            vals = {m: R[m][D[m][i]] for m in M}
            for m in M:
                div[m] += vals[m][0] > DIVERGED_M
            if any(vals[m][0] > DIVERGED_M for m in M):
                continue
            keep.append((s, vals))
        n = len(keep)
        print('\n-- f=%.2f sigma_bad=%.2f | seeds used %d/30 | diverged: %s' % (f, b, n, ', '.join('%s %d' % (m, div[m]) for m in M)))
        if n < 3:
            continue
        S = [k[0] for k in keep]
        for k, name, unit in ((0, 'pos', 'm'), (1, 'ori', 'deg')):
            A = {m: np.array([kv[1][m][k] for kv in keep]) for m in M}
            print('   %s (%s): ' % (name, unit) + ' | '.join('%s %.4f' % (m, A[m].mean()) for m in M))
            for a, bb, lab in COMPARE:
                dm, ci, pw = paired(A[bb], A[a])
                wins = int((A[a] < A[bb]).sum())
                print('        %s %s - %s = %+.4f [+-%.4f] p_w=%.1e, per-feature wins %d/%d' % (lab, a, bb, dm, ci, pw, wins, n))
                r = (A[a] - A[bb]) / A[bb]
                for grp in (['all cells'] + (['f=0.50 cells'] if f == 0.5 else [])):
                    dct = rel.setdefault((lab, grp, name), {})
                    for s, x in zip(S, r):
                        dct.setdefault(s, []).append(x)
                rows.append(dict(npts=label, f=f, sigma_bad=b, metric=name, comparison=lab.strip(), a=a, b=bb, n=n,
                                 mean_a=A[a].mean(), mean_b=A[bb].mean(), diff=dm, ci95=ci, p_wilcoxon=pw, wins_a=wins))
        gp, gf = gate_groups(D['pooled@1.5']), gate_groups(D['perfeat@1.5'])
        print('   gates @1.5, MSCKF clean/noisy: pooled %s / %s (chi2/dof %s / %s) | per-feature %s / %s (chi2/dof %s / %s)'
              % (g(gp, '0', False, 'acc'), g(gp, '0', True, 'acc'), g(gp, '0', False, 'chi'), g(gp, '0', True, 'chi'),
                 g(gf, '0', False, 'acc'), g(gf, '0', True, 'acc'), g(gf, '0', False, 'chi'), g(gf, '0', True, 'chi')))

print('\n================ OVERALL (relative difference averaged over cells within each seed -> one value per seed) ================')
for (lab, grp, name), dct in sorted(rel.items()):
    v = np.array([np.mean(x) for x in dct.values()])
    ci = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v))
    print('  %s %-13s %s: per-feature %+.1f%% [+-%.1f%%] over %d seeds, p_w=%.1e, per-feature better in %d/%d seeds'
          % (lab, grp, name, 100 * v.mean(), 100 * ci, len(v), stats.wilcoxon(v).pvalue, int((v < 0).sum()), len(v)))

with open(RES + '/t4cal_summary.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('\nwrote', RES + '/t4cal_summary.csv')
