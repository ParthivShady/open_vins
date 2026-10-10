#!/usr/bin/env python3
"""T.4c: best inflation beta at true sigma 2.0 (uniform noise), per-feature oracle, udel_gore, 250 pts. Paired vs beta = 1.
Pre-registered: multiplicative unmodelled error -> best beta ~1.5; additive floor (c ~ 1.25 px^2) -> best beta ~1.15."""
import os, sys, subprocess
import numpy as np
from scipy import stats
H = os.path.expanduser('~'); RES = H + '/navcore_ws/results'; ATE = H + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
ROOTS = {1.0: RES + '/t4a_uniform', 1.15: RES + '/t4c_uniform_sig2_beta1.15', 1.3: RES + '/t4c_uniform_sig2_beta1.30', 1.5: RES + '/t4c_uniform_sig2_beta1.50'}
COND = 'sig2.000_f0.000_bad2.000'
def d(root, s): return os.path.normpath('%s/udel_gore/%s/seed%d' % (root, COND, s))
def ate_many(ds):
    ds = [x for x in ds if os.path.exists(x + '/state_estimate.txt')]
    out = subprocess.run([sys.executable, ATE] + ds, capture_output=True, text=True).stdout
    return {os.path.normpath(l.split('\t')[0]): (float(l.split('\t')[1]), float(l.split('\t')[2])) for l in out.splitlines() if l.count('\t') >= 2}
res = {b: ate_many([d(r, s) for s in range(1, 31)]) for b, r in ROOTS.items()}
print('true sigma 2.0, uniform noise, udel_gore 250 pts')
for b, r in ROOTS.items():
    A = np.array([res[1.0][d(ROOTS[1.0], s)] + res[b][d(r, s)] for s in range(1, 31) if d(ROOTS[1.0], s) in res[1.0] and d(r, s) in res[b]])
    line = '  beta %.2f: n=%d  pos %.4f+-%.4f m  ori %.4f+-%.4f deg' % (b, len(A), A[:, 2].mean(), A[:, 2].std(ddof=1), A[:, 3].mean(), A[:, 3].std(ddof=1))
    if b != 1.0:
        line += '  | vs beta 1: pos %+.1f%% (p_w=%.1e, better %d/%d), ori %+.1f%% (p_w=%.1e, better %d/%d)' % (
            100 * (A[:, 2].mean() / A[:, 0].mean() - 1), stats.wilcoxon(A[:, 2], A[:, 0]).pvalue, int((A[:, 2] < A[:, 0]).sum()), len(A),
            100 * (A[:, 3].mean() / A[:, 1].mean() - 1), stats.wilcoxon(A[:, 3], A[:, 1]).pvalue, int((A[:, 3] < A[:, 1]).sum()), len(A))
    print(line)
