#!/usr/bin/env python3
"""Read-only integrity audit of the NavCore result folders (11 Oct 2026).
1. Run counts per batch against the planned counts.
2. Completeness: lines in each run's state_estimate.txt against the full count for its trajectory and point count;
   other lengths are listed with ATE (diverged > 10 m is expected for fixed R past the cliff; any other must be explained).
3. Noise actually used at the MSCKF and SLAM sites, cell f = 0.5, sigma_bad = 2.5, seeds 1-3, with chi2/dof vs theory.
4. The three simulated trajectories.
Usage: ~/navcore_ws/.venv/bin/python scripts/audit_t4_integrity.py | tee ~/navcore_ws/results/audit_11oct.txt"""
import os, re, glob, gzip, csv, subprocess
from collections import defaultdict, Counter
import numpy as np

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'
PY = HOME + '/navcore_ws/.venv/bin/python'; ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
SIM = HOME + '/navcore_ws/src/open_vins/ov_data/sim'
PLANNED = {'t3a': 630, 't3b': 420, 't4a_t3bgrid': 360, 't4a_uniform': 540, 't4b_t3bgrid': 360,
           't4c_uniform_beta1.25': 60, 't4c_uniform_beta1.50': 60, 't4c_uniform_beta2.00': 60,
           't4c_uniform_sig2_beta1.15': 30, 't4c_uniform_sig2_beta1.30': 30, 't4c_uniform_sig2_beta1.50': 30,
           't4cal_perfeat_b1.50': 360, 't4cal_pooled_b1.50': 360,
           't4val_fixed': 180, 't4val_pooled_b1.50': 180, 't4val_perfeat_b1.50': 180}

def opentext(p):
    if os.path.isfile(p): return open(p, newline='')
    if os.path.isfile(p + '.gz'): return gzip.open(p + '.gz', 'rt', newline='')
    return None

runs, count, nofile = defaultdict(list), Counter(), Counter()
for d in sorted(glob.glob(RES + '/*/*/*/seed*')):
    batch, traj, cond, _ = os.path.relpath(d, RES).split(os.sep)
    if not re.match(r'^sig[0-9.]+_f', cond): continue
    count[batch] += 1
    f = d + '/state_estimate.txt'
    if not os.path.isfile(f): nofile[batch] += 1; continue
    with open(f, 'rb') as fh: n = sum(1 for _ in fh)
    m = re.search(r'_n(\d+)$', cond)
    runs[(traj, m.group(1) if m else '250')].append((batch, d, n))

print('================ 1. Run counts per batch ================')
for b in sorted(set(count) | set(PLANNED)):
    exp = PLANNED.get(b)
    flag = '' if exp is None else ('OK' if count[b] == exp and not nofile[b] else 'CHECK')
    print(f'  {b:30s} found {count[b]:4d} | planned {exp if exp else "-":>4} | no state file {nofile[b]:3d} {flag}')

print('\n================ 2. Completeness (lines in state_estimate.txt) ================')
short = []
for key in sorted(runs):
    L = runs[key]
    full = Counter(n for _, _, n in L).most_common(1)[0][0]
    s = [(b, d, n, full) for b, d, n in L if n != full]
    short += s
    print(f'  {key[0]:28s} {key[1]:>3s} pts: {len(L):5d} runs, full = {full} lines, other lengths: {len(s)}')
ate, paths = {}, [d for _, d, _, _ in short]
for k in range(0, len(paths), 200):
    out = subprocess.run([PY, ATE] + paths[k:k + 200], capture_output=True, text=True).stdout
    for line in out.strip().splitlines():
        p = line.split('\t')
        try: ate[os.path.normpath(p[0])] = float(p[1])
        except (ValueError, IndexError): pass
by = defaultdict(lambda: [0, []])
for b, d, n, full in short:
    a = ate.get(os.path.normpath(d), float('nan'))
    if a > 10: by[b][0] += 1
    else: by[b][1].append(f'{os.path.relpath(d, RES)}: {n}/{full} lines, ATE {a:.3f} m')
print('  other lengths per batch: diverged (> 10 m, expected for fixed R past the cliff) | not diverged (explain each)')
for b in sorted(by):
    print(f'  {b:30s} diverged {by[b][0]:4d} | not diverged {len(by[b][1]):3d}')
    for line in by[b][1][:25]: print('      ' + line)
if not by: print('  none')

print('\n================ 3. Noise actually used (f = 0.5, sigma_bad = 2.5, seeds 1-3) ================')
V = 3.625   # mean sigma^2 of a frame with half clean (1 px) and half noisy (2.5 px) features
CHECK = [('t4val_fixed', 'stock', 1.0), ('t4a_t3bgrid', 'per-feature', 1.0), ('t4cal_perfeat_b1.50', 'per-feature', 1.5),
         ('t4val_perfeat_b1.50', 'per-feature', 1.5), ('t4b_t3bgrid', 'pooled', 1.0),
         ('t4cal_pooled_b1.50', 'pooled', 1.5), ('t4val_pooled_b1.50', 'pooled', 1.5)]
for batch, kind, beta in CHECK:
    dirs = sorted(glob.glob(f'{RES}/{batch}/*/sig1.000_f0.500_bad2.500/seed[123]'))
    S = defaultdict(lambda: {'clean': [[], 0.0, 0], 'noisy': [[], 0.0, 0]}); frame = defaultdict(set)
    for d in dirs:
        for fname in ('gate_feat.csv', 'gate_slam.csv'):
            fh = opentext(f'{d}/{fname}')
            if fh is None: continue
            with fh:
                rd = csv.reader(fh); next(rd, None)
                for r in rd:
                    try: t, k, st, su, dof, chi = r[0], r[1], float(r[3]), float(r[4]), int(r[5]), float(r[6])
                    except (ValueError, IndexError): continue
                    site = 'MSCKF' if fname == 'gate_feat.csv' else ('SLAM update' if k == '1' else 'SLAM init')
                    g = S[site]['clean' if st < 1.01 else 'noisy']
                    g[0].append(su)
                    if dof > 0 and chi >= 0: g[1] += chi; g[2] += dof
                    frame[(d, t)].add(round(su, 6))
    if kind == 'per-feature': eu, ec = (beta, 2.5 * beta), (1 / beta**2, 1 / beta**2)
    elif kind == 'pooled': eu, ec = (beta * V**0.5,) * 2, (1 / (beta**2 * V), 6.25 / (beta**2 * V))
    else: eu, ec = (1.0, 1.0), (1.0, 6.25)
    most = max((len(v) for v in frame.values()), default=0)
    print(f'\n  {batch} ({kind}, beta {beta}): {len(dirs)} runs | most distinct sigma_used in one frame: {most}'
          + (' (pooled must be 1)' if kind == 'pooled' else ''))
    for site in ('MSCKF', 'SLAM update', 'SLAM init'):
        c, z = S[site]['clean'], S[site]['noisy']
        if not c[0] and not z[0]: print(f'    {site:12s} no rows'); continue
        mu = [np.mean(g[0]) if g[0] else float('nan') for g in (c, z)]
        cd = [g[1] / g[2] if g[2] else float('nan') for g in (c, z)]
        ok = abs(mu[0] - mu[1]) < 0.1 * mu[0] if kind == 'pooled' else (abs(mu[0] - eu[0]) < 1e-3 and abs(mu[1] - eu[1]) < 1e-3)
        print(f'    {site:12s} sigma_used clean/noisy {mu[0]:.3f} / {mu[1]:.3f} (expected {eu[0]:.3f} / {eu[1]:.3f}) '
              f'{"OK" if ok else "CHECK"} | chi2/dof {cd[0]:.2f} / {cd[1]:.2f} (theory {ec[0]:.2f} / {ec[1]:.2f}) '
              f'| rows {len(c[0])} / {len(z[0])}')

print('\n================ 4. Simulated trajectories ================')
for name in ('udel_gore', 'udel_gore_zupt', 'tum_corridor1_512_16_okvis'):
    try: A = np.loadtxt(f'{SIM}/{name}.txt', comments='#')
    except Exception as e: print(f'  {name}: cannot read ({e})'); continue
    t, P = A[:, 0], A[:, 1:4]
    step = np.linalg.norm(np.diff(P, axis=0), axis=1)
    still = (step / np.maximum(np.diff(t), 1e-9) < 0.05).mean()
    print(f'  {name:28s} {t[-1] - t[0]:7.1f} s | path {step.sum():7.1f} m | stationary {100 * still:5.1f}% | start {np.round(P[0], 2)}')
