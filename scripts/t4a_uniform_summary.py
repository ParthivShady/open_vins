#!/usr/bin/env python3
"""T.4a uniform summary: oracle (filter given the true sigma) vs T.3a fixed R on the homogeneous sweep. Tests P2.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4a_uniform_summary.py
Writes ~/navcore_ws/results/t4a_uniform_summary.csv."""
import os, sys, subprocess, csv
import numpy as np
try:
    from scipy import stats
except ImportError:
    stats = None

HOME = os.path.expanduser('~')
RES = os.path.join(HOME, 'navcore_ws/results')
T3A = os.path.join(RES, 't3a')
T4U = os.path.join(RES, 't4a_uniform')
ATE = os.path.join(HOME, 'navcore_ws/src/open_vins/scripts/t3_ate.py')
TRAJS = ['udel_gore', 'udel_gore_zupt', 'tum_corridor1_512_16_okvis']
SIGMAS = [1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
SEEDS = list(range(1, 31))
DIVERGED_M = 10.0

def cdir(root, traj, sig, seed):
    f = '%.3f' % sig
    return os.path.join(root, traj, 'sig%s_f0.000_bad%s' % (f, f), 'seed%d' % seed)

def ate_many(dirs):
    """t3_ate.py on many run folders -> {dir: (pos_m, ori_deg, n_poses)}; unreadable runs are absent."""
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, 'state_estimate.txt'))]
    out = subprocess.run([sys.executable, ATE] + dirs, capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        p = line.split('\t')
        if len(p) >= 4:
            try:
                res[os.path.normpath(p[0])] = (float(p[1]), float(p[2]), int(float(p[3])))
            except ValueError:
                pass
    return res

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
                if a >= 0 and b >= 0:  # -1 = update ended before this stage; not a count
                    tri += a; passed += b
    return 100 * passed / tri if tri else float('nan')

def gate_kinds(dirs):
    """Per-feature logs -> {kind: [n, accepted, sum chi2/dof]}; kind 0 MSCKF, 1 SLAM upd, 2 SLAM init."""
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
                    v = acc.setdefault(kind, [0, 0, 0.0])
                    v[0] += 1; v[1] += int(a)
                    if kind != '2':
                        v[2] += float(chi2) / int(dof)
    return acc

def kpct(acc, k):
    v = acc.get(k)
    return '%.1f%%' % (100 * v[1] / v[0]) if v and v[0] else 'n/a'

def kchi(acc, k):
    v = acc.get(k)
    return '%.2f' % (v[2] / v[0]) if v and v[0] else 'n/a'

rows = []
print('T.4a uniform: oracle vs T.3a fixed R | 30 seeds | diverged = ATE > %.0f m | truncated = < 90%% of baseline poses' % DIVERGED_M)
for traj in TRAJS:
    base_dirs = [os.path.normpath(cdir(T3A, traj, 1.0, s)) for s in SEEDS]
    base = ate_many(base_dirs)
    bpos = np.array([base[d][0] for d in base_dirs if d in base])
    bn = np.median([base[d][2] for d in base_dirs if d in base])
    print('\n================ %s ================' % traj)
    print('  sigma 1.00 baseline (fixed = oracle): median pos ATE %.4f m, mean %.4f+-%.4f, median poses %d' % (np.median(bpos), bpos.mean(), bpos.std(ddof=1), bn))
    for sig in SIGMAS:
        fx_dirs = [os.path.normpath(cdir(T3A, traj, sig, s)) for s in SEEDS]
        or_dirs = [os.path.normpath(cdir(T4U, traj, sig, s)) for s in SEEDS]
        fx, orc = ate_many(fx_dirs), ate_many(or_dirs)
        def summ(res, dirs):
            v = [res[d] for d in dirs if d in res]
            pos = np.array([x[0] for x in v]); n = np.array([x[2] for x in v])
            div = int((pos > DIVERGED_M).sum()); trunc = int((n < 0.9 * bn).sum())
            ok = pos[pos <= DIVERGED_M]
            return len(v), div, trunc, (np.median(pos) if len(pos) else np.nan), ok
        nf, df, tf, mf, okf = summ(fx, fx_dirs)
        no, do, to, mo, oko = summ(orc, or_dirs)
        pw = float('nan')
        both = [(fx[a][0], orc[b][0]) for a, b in zip(fx_dirs, or_dirs)
                if a in fx and b in orc and fx[a][0] <= DIVERGED_M and orc[b][0] <= DIVERGED_M]
        if df == 0 and len(both) >= 10 and stats:
            A = np.array(both)
            pw = stats.wilcoxon(A[:, 1], A[:, 0]).pvalue
        g = gate_kinds(or_dirs)
        print('  sigma %.2f | FIXED diverged %2d/%d, truncated %2d, median ATE %9.4f m | ORACLE diverged %2d/%d, truncated %2d, median ATE %.4f m (mean %.4f+-%.4f), x%.2f of baseline%s'
              % (sig, df, nf, tf, mf, do, no, to, mo, oko.mean() if len(oko) else np.nan, oko.std(ddof=1) if len(oko) > 1 else np.nan,
                 mo / np.median(bpos), (' | paired p_w=%.1e' % pw) if pw == pw else ''))
        print('             gate MSCKF fixed %.1f%% -> oracle %.1f%% | oracle chi2/dof MSCKF %s, SLAM upd %s | oracle acc SLAM upd %s, SLAM init %s'
              % (gate_overall(fx_dirs), gate_overall(or_dirs), kchi(g, '0'), kchi(g, '1'), kpct(g, '1'), kpct(g, '2')))
        rows.append(dict(traj=traj, sigma=sig, fixed_runs=nf, fixed_diverged=df, fixed_truncated=tf, fixed_median_ate=mf,
                         oracle_runs=no, oracle_diverged=do, oracle_truncated=to, oracle_median_ate=mo,
                         oracle_mean_ate=oko.mean() if len(oko) else np.nan, oracle_std_ate=oko.std(ddof=1) if len(oko) > 1 else np.nan,
                         baseline_median_ate=np.median(bpos), oracle_ratio_to_baseline=mo / np.median(bpos), paired_p_wilcoxon=pw,
                         gate_msckf_fixed=gate_overall(fx_dirs), gate_msckf_oracle=gate_overall(or_dirs)))

out = os.path.join(RES, 't4a_uniform_summary.csv')
with open(out, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('\nwrote', out)
