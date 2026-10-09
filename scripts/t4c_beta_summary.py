#!/usr/bin/env python3
"""T.4c-pre: ATE vs R inflation beta under uniform noise (every feature at its true sigma 1.0), udel_gore.
Each beta is paired by seed with beta = 1 (the T.3b uniform cell, identical to stock)."""
import os, sys, subprocess
import numpy as np
from scipy import stats

H = os.path.expanduser('~')
RES = H + '/navcore_ws/results'
ATE = H + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
ROOTS = {1.0: RES + '/t3b', 1.25: RES + '/t4c_uniform_beta1.25', 1.5: RES + '/t4c_uniform_beta1.50', 2.0: RES + '/t4c_uniform_beta2.00'}
SEEDS = range(1, 31)

def run_dir(root, cond, seed):
    return os.path.normpath('%s/udel_gore/%s/seed%d' % (root, cond, seed))

def ate_many(dirs):
    dirs = [d for d in dirs if os.path.exists(d + '/state_estimate.txt')]
    out = subprocess.run([sys.executable, ATE] + dirs, capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        p = line.split('\t')
        if len(p) >= 3:
            res[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))
    return res

for npts in ('', '60'):
    cond = 'sig1.000_f0.000_bad1.000' + ('_n' + npts if npts else '')
    res = {b: ate_many([run_dir(r, cond, s) for s in SEEDS]) for b, r in ROOTS.items()}
    print('\nnum_pts %s (uniform noise, true sigma 1.0)' % (npts or '250'))
    for b, root in ROOTS.items():
        pairs = []
        for s in SEEDS:
            d1, db = run_dir(ROOTS[1.0], cond, s), run_dir(root, cond, s)
            if d1 in res[1.0] and db in res[b]:
                pairs.append(res[1.0][d1] + res[b][db])   # (pos1, ori1, posb, orib)
        A = np.array(pairs)
        line = '  beta %.2f: n=%d  pos %.4f+-%.4f m  ori %.4f+-%.4f deg' % (b, len(A), A[:, 2].mean(), A[:, 2].std(ddof=1), A[:, 3].mean(), A[:, 3].std(ddof=1))
        if b != 1.0:
            line += '  | vs beta 1: pos %+.1f%% (p_w=%.1e, better in %d/%d), ori %+.1f%% (p_w=%.1e, better in %d/%d)' % (
                100 * (A[:, 2].mean() / A[:, 0].mean() - 1), stats.wilcoxon(A[:, 2], A[:, 0]).pvalue, int((A[:, 2] < A[:, 0]).sum()), len(A),
                100 * (A[:, 3].mean() / A[:, 1].mean() - 1), stats.wilcoxon(A[:, 3], A[:, 1]).pvalue, int((A[:, 3] < A[:, 1]).sum()), len(A))
        print(line)
