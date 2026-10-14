#!/usr/bin/env python3
"""Read-only diagnostic (13 Oct 2026): distribution of position ATE on the held-out cells, per method, to see whether a few
large-error runs drive the P7b / P8(d) statistics. 'Large' = above LARGE m (several times the stock baseline ATE).
Exploratory, written after the pre-registered summary; it changes no pre-registered verdict.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4_heldout_dist.py | tee ~/navcore_ws/results/t4_heldout_dist.txt"""
import os, subprocess
import numpy as np

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'
PY = os.environ.get('NAVCORE_PY', HOME + '/navcore_ws/.venv/bin/python')
ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
LARGE = 0.25
M = [('perfeat@1.5', 't4val_perfeat_b1.50'), ('pooled@1.5', 't4val_pooled_b1.50'), ('fixed@1.0', 't4val_fixed'), ('tuned@1.5', 't4tf_val')]
TRAJ = ['euroc_V1_01_easy', 'udel_gore_zupt', 'tum_corridor1_512_16_okvis']
SB = (1.25, 1.5, 2.5)
def cond(b): return 'sig1.000_f0.500_bad%.3f' % b

dirs = [os.path.normpath(f'{RES}/{r}/{t}/{cond(b)}/seed{s}') for _, r in M for t in TRAJ for b in SB for s in range(1, 31)]
have = [d for d in dirs if os.path.isfile(d + '/state_estimate.txt')]
A = {}
for k in range(0, len(have), 200):
    out = subprocess.run([PY, ATE] + have[k:k + 200], capture_output=True, text=True).stdout
    for line in out.strip().splitlines():
        p = line.split('\t')
        try: A[os.path.normpath(p[0])] = float(p[1])
        except (ValueError, IndexError): pass
print(f'Held-out ATE distribution | position ATE (m) | large = > {LARGE} m | {len(A)}/{len(dirs)} runs with ATE')
for t in TRAJ:
    print(f'\n== {t}')
    for b in SB:
        print(f'  sigma_bad {b}')
        for m, r in M:
            v = {s: A.get(os.path.normpath(f'{RES}/{r}/{t}/{cond(b)}/seed{s}')) for s in range(1, 31)}
            x = np.array([a for a in v.values() if a is not None])
            if not len(x): print(f'    {m:12s} no runs'); continue
            big = sorted((s for s, a in v.items() if a is not None and a > LARGE), key=lambda s: -v[s])
            print(f'    {m:12s} n {len(x):2d} | median {np.median(x):.4f} | p90 {np.percentile(x, 90):.4f} | max {x.max():.3f} | '
                  f'large {len(big):2d}' + (' (seed:ATE ' + ', '.join(f'{s}:{v[s]:.2f}' for s in big[:6]) + ')' if big else ''))
