#!/usr/bin/env python3
"""NavCore T.4e summary: the key simulation comparisons rerun with independent noise in the two cameras.
Usage:  ~/navcore_ws/.venv/bin/python scripts/t4e_summary.py      writes results/t4e_summary.txt
Predictions, fixed 18 Oct before any T.4e run (udel_gore, seeds 1-30, 250 points):
  P24 with independent camera noise the stereo estimate is unbiased on clean data: the mean of
      (sigma_used / (beta sigma_true))^2 over G1's clean MSCKF rows lies between 0.95 and 1.05 (shared noise: reported).
  P25 the fixed filters still break down: stock loses track (ATE > 0.5 m) in at least 15 of 30 runs at 1.75 px, tuned
      fixed in at least 15 of 30 at 2.5 px; G1c loses track in none of its 60 runs at 2.5 and 3.0 px.
  P26 the exact per-feature oracle is clearly better than per-frame at bad 2.5 (f 0.5) and not clearly worse than tuned
      fixed at bad 1.25, 1.5 or 2.5.
  P27 G1c is not clearly worse than tuned fixed at bad 1.25, 1.5 or 2.5, is within 2% of it on clean data, and is clearly
      better than per-frame at bad 2.5.
'Clearly' = paired Wilcoxon p < 0.05 over the 30 seeds; position decides; orientation is reported alongside."""
import csv, gzip, math, os, subprocess, sys, time
import numpy as np
from scipy.stats import wilcoxon

RES = os.path.expanduser(os.environ.get('T4D_RES', '~/navcore_ws/results'))
ATE_SCRIPT = os.environ.get('T4D_ATE_SCRIPT', os.path.expanduser('~/navcore_ws/src/open_vins/scripts/t3_ate.py'))
SEEDS = list(range(1, 31))
BETA = 1.5
GORE, HELD = 'udel_gore', ['udel_gore_zupt', 'tum_corridor1_512_16_okvis', 'euroc_V1_01_easy']
SHORT = {'udel_gore': 'gore', 'udel_gore_zupt': 'zupt', 'tum_corridor1_512_16_okvis': 'TUM', 'euroc_V1_01_easy': 'EuRoC'}
BADS = [1.25, 1.5, 2.5]
UNI = [1.5, 2.0, 2.5, 3.0]
SVALS = ['0.10', '0.20', '0.40']


def cond(sig, f, bad, n=''):
    return f'sig{sig:.3f}_f{f:.3f}_bad{bad:.3f}' + (f'_n{n}' if n else '')


def root(method, traj):
    held = traj != GORE
    return {'epi': 't4d_epi_nu5', 'epi20': 't4d_epi_nu20',
            'oracle': 't4val_perfeat_b1.50' if held else 't4cal_perfeat_b1.50',
            'pooled': 't4val_pooled_b1.50' if held else 't4cal_pooled_b1.50',
            'tuned': 't4tf_val' if held else 't4tf_t3bgrid',
            'stock': 't4val_fixed' if held else 't3b'}.get(method, method)


def rundir(rt, traj, c, s):
    return os.path.join(RES, rt, traj, c, f'seed{s}')


# ---------------- ATE ----------------
ATE = {}


def load_cache(path):
    if not os.path.isfile(path):
        return
    for row in csv.reader(open(path)):
        if len(row) >= 3:
            try:
                ATE[row[0].rstrip('/')] = (float(row[1]), float(row[2]))
            except ValueError:
                pass


def ensure_ate(dirs):
    # a G1 run counts only once the batch has verified it, so a run still being written is never cached
    done = lambda d: os.path.isfile(os.path.join(d, 'navcore_verified.txt' if ('/t4d_' in d or '/t4e_' in d) else 'state_estimate.txt'))
    todo = sorted({d for d in dirs if d not in ATE and done(d)})
    if not todo:
        return
    print(f'computing ATE for {len(todo)} runs (cached afterwards) ...', flush=True)
    cache = os.path.join(RES, 'figures', 'ate_cache_t4d.csv')
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    for k in range(0, len(todo), 100):
        chunk = todo[k:k + 100]
        out = subprocess.run([sys.executable, ATE_SCRIPT] + chunk, capture_output=True, text=True).stdout
        with open(cache, 'a') as fh:
            for line in out.splitlines():
                p = line.split('\t')
                if len(p) >= 3 and p[0].rstrip('/') in chunk:
                    try:
                        v = (float(p[1]), float(p[2]))
                    except ValueError:
                        v = (math.nan, math.nan)
                    ATE[p[0].rstrip('/')] = v
                    fh.write(f'{p[0].rstrip("/")},{v[0]},{v[1]}\n')


def vec(rt, traj, c, k=0):
    return np.array([ATE.get(rundir(rt, traj, c, s), (math.nan, math.nan))[k] for s in SEEDS])


# ---------------- statistics ----------------
def compare(a, b):
    m = np.isfinite(a) & np.isfinite(b) & (a < 10) & (b < 10)
    n = int(m.sum())
    if n < 5:
        return dict(n=n, rel=math.nan, p=math.nan, wins=0, ma=math.nan, mb=math.nan)
    d = a[m] - b[m]
    p = float(wilcoxon(d).pvalue) if np.any(d != 0) else 1.0
    return dict(n=n, rel=a[m].mean() / b[m].mean() - 1, p=p, wins=int((d < 0).sum()), ma=a[m].mean(), mb=b[m].mean())


def seedmean(vs):
    A = np.vstack(vs)
    ok = np.all(np.isfinite(A) & (A < 10), axis=0)
    return np.where(ok, A.mean(0) if ok.any() else math.nan, math.nan)


def overall(cells, ma, mb, k=0):
    """cells: list of (traj, c); ma, mb: method names"""
    return compare(seedmean([vec(root(ma, t), t, c, k) for t, c in cells]), seedmean([vec(root(mb, t), t, c, k) for t, c in cells]))


def boot(a, b, nb=4000):
    m = np.isfinite(a) & np.isfinite(b) & (a < 10) & (b < 10)
    a, b = a[m], b[m]
    if len(a) < 5:
        return (math.nan, math.nan)
    idx = np.random.default_rng(0).integers(0, len(a), (nb, len(a)))
    return tuple(np.percentile(a[idx].mean(1) / b[idx].mean(1) - 1, [2.5, 97.5]))


def fmt(r):
    if not np.isfinite(r['rel']):
        return f'n/a (n={r["n"]})'
    star = '*' if r['p'] < 0.05 else ' '
    return f'{100 * r["rel"]:+6.1f}%{star} (p {r["p"]:.2g}, lower in {r["wins"]}/{r["n"]})'


def clear_neg(r):
    return np.isfinite(r['rel']) and r['rel'] < 0 and r['p'] < 0.05


def clear_pos(r):
    return np.isfinite(r['rel']) and r['rel'] > 0 and r['p'] < 0.05


# ---------------- gate logs (estimator quality, seeds 1-5) ----------------
def gate_rows(d):
    for fn in ('gate_feat.csv', 'gate_feat.csv.gz'):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            fh = gzip.open(p, 'rt') if fn.endswith('.gz') else open(p)
            rows = [r for r in csv.reader(fh)][1:]
            a = np.array([[float(r[1]), float(r[3]), float(r[4]), float(r[5]), float(r[6])] for r in rows if len(r) >= 9],
                         dtype=float)
            return a[a[:, 0] == 0] if len(a) else a   # MSCKF rows: sigma_true, sigma_used, dof, chi2 in cols 1-4
    return None


def quality(rt, cells, seeds=range(1, 6)):
    q = []
    for t, c in cells:
        for s in seeds:
            a = gate_rows(rundir(rt, t, c, s))
            if a is not None and len(a):
                q.append(a)
    if not q:
        return None
    a = np.vstack(q)
    st, su, dof, chi2 = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    ok = np.isfinite(st) & (st > 0) & (dof > 0)
    st, su, dof, chi2 = st[ok], su[ok], dof[ok], chi2[ok]
    clean = st <= st.min() + 1e-9
    lr = np.log(su / (BETA * st))
    out = dict(rows=len(st), s=float(np.std(lr)), med_clean=float(np.exp(np.median(lr[clean]))),
               chi_clean=float(np.mean(chi2[clean] / dof[clean])))
    if (~clean).any():
        rs, rt_ = np.argsort(np.argsort(su)), np.argsort(np.argsort(st))
        out.update(med_noisy=float(np.exp(np.median(lr[~clean]))), chi_noisy=float(np.mean(chi2[~clean] / dof[~clean])),
                   rho=float(np.corrcoef(rs, rt_)[0, 1]))
    return out



INDEP = {'stock': 't4e_stock', 'tuned': 't4e_tuned', 'oracle': 't4e_oracle', 'pooled': 't4e_pooled', 'g1c': 't4e_g1c', 'g1': 't4e_g1'}
SHARED_F05 = {'stock': 't3b', 'tuned': 't4tf_t3bgrid', 'oracle': 't4cal_perfeat_b1.50', 'pooled': 't4cal_pooled_b1.50', 'g1c': 't4d_g1c'}


def sq_ratio(rt, c):
    vals = []
    for s in SEEDS:
        a = gate_rows(rundir(rt, GORE, c, s))
        if a is not None and len(a):
            st, su = a[:, 1], a[:, 2]
            ok = np.isfinite(st) & (st > 0)
            vals.append((su[ok] / (BETA * st[ok])) ** 2)
    v = np.concatenate(vals) if vals else np.array([])
    return (float(np.mean(v)), float(np.median(np.sqrt(v))), len(v)) if len(v) else (math.nan, math.nan, 0)


def main():
    t0 = time.time()
    lines = []
    out = lambda s='': lines.append(s)
    load_cache(os.path.join(RES, 'figures', 'ate_cache.csv'))
    load_cache(os.path.join(RES, 'figures', 'ate_cache_t4d.csv'))
    f05 = {b: cond(1.0, 0.5, b) for b in BADS}
    clean = cond(1.0, 0.0, 1.0)
    uni = {g: cond(g, 0.0, g) for g in (1.5, 1.75, 2.0, 2.5, 3.0)}
    need = []
    for k in ('oracle', 'pooled', 'tuned', 'stock', 'g1c'):
        for c in f05.values():
            need += [rundir(INDEP[k], GORE, c, s) for s in SEEDS] + [rundir(SHARED_F05[k], GORE, c, s) for s in SEEDS]
    for k in ('g1', 'g1c', 'tuned'):
        need += [rundir(INDEP[k], GORE, clean, s) for s in SEEDS]
    need += [rundir(rt, GORE, clean, s) for rt in ('t4d_epi_nu5', 't4d_g1c', 't4c_uniform_beta1.50') for s in SEEDS]
    for k, gs in (('stock', (1.5, 1.75)), ('tuned', (2.0, 2.5)), ('g1c', (2.5, 3.0))):
        for g in gs:
            need += [rundir(INDEP[k], GORE, uni[g], s) for s in SEEDS]
    ensure_ate(need)
    n_new = sum(1 for d in set(need) if '/t4e_' in d and d in ATE)
    out(f'T.4e summary (independent camera noise), {time.strftime("%Y-%m-%d %H:%M")}. New runs with ATE: {n_new}/720' + ('   PARTIAL' if n_new < 720 else ''))
    out('Rules fixed 18 Oct before results (script header). * = p < 0.05. Negative = first method lower (better).')
    out()
    m_i, med_i, n_i = sq_ratio(INDEP['g1'], clean)
    m_s, med_s, n_s = sq_ratio('t4d_epi_nu5', clean)
    p24 = 0.95 <= m_i <= 1.05
    out(f'P24 G1 on clean data, mean (sigma_used/(beta sigma_true))^2: independent noise {m_i:.3f} (median ratio {med_i:.3f}, {n_i} rows) | '
        f'shared noise {m_s:.3f} (median {med_s:.3f})')
    out(f'P24 -> {"HELD" if p24 else "FAILED"}')
    out()
    out('P25 same noise on every feature: lost track (> 0.5 m) / diverged (> 10 m), of those found')
    lost = {}
    for k, gs in (('stock', (1.5, 1.75)), ('tuned', (2.0, 2.5)), ('g1c', (2.5, 3.0))):
        for g in gs:
            v = vec(INDEP[k], GORE, uni[g]); f = np.isfinite(v)
            lost[(k, g)] = int((v[f] > 0.5).sum())
            out(f'    {k:5s} {g:.2f} px: {lost[(k, g)]}/{int((v[f] > 10).sum())} of {int(f.sum())}')
    p25 = lost[('stock', 1.75)] >= 15 and lost[('tuned', 2.5)] >= 15 and lost[('g1c', 2.5)] + lost[('g1c', 3.0)] == 0
    out(f'P25 -> {"HELD" if p25 else "FAILED"}')
    out()

    def cmp(a, b, c, k=0):
        return compare(vec(INDEP[a], GORE, c, k), vec(INDEP[b], GORE, c, k))

    out('P26 exact oracle (half the features noisier, 250 points): position | orientation')
    ok26 = True
    for b, c in f05.items():
        rp, rt_ = cmp('oracle', 'pooled', c), cmp('oracle', 'tuned', c)
        out(f'    bad {b}: vs per-frame {fmt(rp)} | {fmt(cmp("oracle", "pooled", c, 1))}')
        out(f'             vs tuned fixed {fmt(rt_)} | {fmt(cmp("oracle", "tuned", c, 1))}')
        ok26 = ok26 and not clear_pos(rt_) and (b != 2.5 or clear_neg(rp))
    out(f'P26 -> {"HELD" if ok26 else "FAILED"}')
    out()
    out('P27 G1c: position | orientation')
    ok27 = True
    for b, c in f05.items():
        rt_, rp = cmp('g1c', 'tuned', c), cmp('g1c', 'pooled', c)
        out(f'    bad {b}: vs tuned fixed {fmt(rt_)} | {fmt(cmp("g1c", "tuned", c, 1))}')
        out(f'             vs per-frame {fmt(rp)} | {fmt(cmp("g1c", "pooled", c, 1))}')
        ok27 = ok27 and not clear_pos(rt_) and (b != 2.5 or clear_neg(rp))
    rc = cmp('g1c', 'tuned', clean)
    out(f'    clean 1.0 px: vs tuned fixed {fmt(rc)} | {fmt(cmp("g1c", "tuned", clean, 1))}')
    ok27 = ok27 and np.isfinite(rc['rel']) and abs(rc['rel']) <= 0.02
    out(f'P27 -> {"HELD" if ok27 else "FAILED"}')
    out()
    out('How much the shared camera noise flattered the simulation (no prediction): mean position ATE, independent / shared')
    for k in ('stock', 'tuned', 'oracle', 'pooled', 'g1c'):
        txt = []
        for b, c in f05.items():
            vi, vs = vec(INDEP[k], GORE, c), vec(SHARED_F05[k], GORE, c)
            fi, fs = np.isfinite(vi) & (vi < 10), np.isfinite(vs) & (vs < 10)
            txt.append(f'bad {b}: {np.mean(vi[fi]):.4f} / {np.mean(vs[fs]):.4f} m (x{np.mean(vi[fi]) / np.mean(vs[fs]):.2f})' if fi.any() and fs.any() else f'bad {b}: n/a')
        out(f'    {k:6s} ' + ' | '.join(txt))
    out()
    out(f'({time.time() - t0:.0f} s)')
    txt = '\n'.join(lines)
    print(txt)
    open(os.path.join(RES, 't4e_summary.txt'), 'w').write(txt + '\n')


if __name__ == '__main__':
    main()
