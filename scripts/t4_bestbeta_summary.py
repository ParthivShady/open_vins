#!/usr/bin/env python3
"""Best-beta fairness check (read-only, existing runs). T.3b grid on udel_gore, 12 cells x 30 seeds.
Equal beta (1.5) is the protocol: beta was calibrated on uniform data, where the methods coincide. This asks whether
per-feature still wins if pooled gets whichever of beta 1.0 / 1.5 suits it better on this grid.
Prediction (11 Oct, before computing): pooled is better at beta 1.0 here; per-feature@1.5 still beats pooled@1.0
overall, by less than its 8.2% margin over pooled@1.5. If they are level, the granularity result holds only under the
equal-calibration protocol and is reported that way.
Cross-check: [perfeat@1.5 vs pooled@1.5], all cells, should reproduce t4cal_summary (-8.2% pos, -5.3% ori).
Usage: ~/navcore_ws/.venv/bin/python scripts/t4_bestbeta_summary.py | tee ~/navcore_ws/results/t4_bestbeta_summary.txt"""
import os, subprocess
import numpy as np
from scipy import stats

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'
PY = HOME + '/navcore_ws/.venv/bin/python'; ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
M = {'stock@1.0': 't3b', 'perfeat@1.0': 't4a_t3bgrid', 'perfeat@1.5': 't4cal_perfeat_b1.50',
     'pooled@1.0': 't4b_t3bgrid', 'pooled@1.5': 't4cal_pooled_b1.50'}
CELLS = [(f, b) for f in (0.25, 0.5) for b in (1.25, 1.5, 2.5)]
SEEDS = range(1, 31); DIV = 10.0
GROUPS = [('250 pts', ['']), ('60 pts', ['60']), ('all cells', ['', '60'])]
PAIRS = [('pooled@1.5', 'pooled@1.0'), ('perfeat@1.5', 'perfeat@1.0'), ('perfeat@1.5', 'pooled@1.5'),
         ('perfeat@1.5', 'pooled@1.0'), ('perfeat@1.5', 'stock@1.0')]

def cond(f, b, n): return 'sig1.000_f%.3f_bad%.3f' % (f, b) + ('_n' + n if n else '')
D = {(m, n, c, s): os.path.normpath(f'{RES}/{M[m]}/udel_gore/{cond(*c, n)}/seed{s}')
     for m in M for n in ('', '60') for c in CELLS for s in SEEDS}
A, paths = {}, [d for d in D.values() if os.path.isfile(d + '/state_estimate.txt')]
for k in range(0, len(paths), 200):
    out = subprocess.run([PY, ATE] + paths[k:k + 200], capture_output=True, text=True, check=True).stdout
    for line in out.strip().splitlines():
        p = line.split('\t')
        if len(p) >= 3: A[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))

def val(m, n, c, s, k):
    v = A.get(D[(m, n, c, s)])
    return v[k] if v is not None and v[0] < DIV else None

print(f'Best-beta fairness check | T.3b grid, udel_gore | {len(A)}/{len(D)} runs with ATE | diverged (> {DIV:g} m) excluded')
for gname, ns in GROUPS:
    keys = [(n, c) for n in ns for c in CELLS]
    print(f'\n== {gname} ==')
    for m in M:
        pos = [x for x in (val(m, n, c, s, 0) for n, c in keys for s in SEEDS) if x is not None]
        ori = [x for x in (val(m, n, c, s, 1) for n, c in keys for s in SEEDS) if x is not None]
        print(f'  {m:12s} mean pos {np.mean(pos):.4f} m | ori {np.mean(ori):.4f} deg | {len(pos)} runs')
    for a, b in PAIRS:
        for k, lab in ((0, 'pos'), (1, 'ori')):
            per = []
            for s in SEEDS:
                r = [(val(a, n, c, s, k) - val(b, n, c, s, k)) / val(b, n, c, s, k) for n, c in keys
                     if val(a, n, c, s, k) is not None and val(b, n, c, s, k) is not None]
                if r: per.append(np.mean(r))
            v = np.array(per)
            print(f'  [{a} vs {b}] {lab}: {100 * v.mean():+.1f}% [+-{100 * stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v)):.1f}%] '
                  f'over {len(v)} seeds, p_w={stats.wilcoxon(v).pvalue:.1e}, first better in {(v < 0).sum()}/{len(v)}')
