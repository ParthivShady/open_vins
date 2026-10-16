#!/usr/bin/env python3
"""NavCore T.4d G1 summary: verdicts for P9-P13 (frozen 16 Oct) and the bar for G2.
Usage:  ~/navcore_ws/.venv/bin/python scripts/t4d_g1_summary.py
Writes results/t4d_g1_summary.txt and results/t4d_g1_summary.csv. The ATE of new runs is cached in
results/figures/ate_cache_t4d.csv (computed with t3_ate.py); baselines come from results/figures/ate_cache.csv.

Verdict cells and rules, fixed 16 Oct before any G1 result was seen:
  P9  uniform noise 1.5, 2.0, 2.5, 3.0 px, udel_gore, 250 points: no epipolar run loses track (ATE > 0.5 m).
  P10 clean 1.0 px, udel_gore, 250 and 60 points: |position difference| <= 8% against tuned fixed, represented by
      the per-feature filter at beta 1.5 on clean data (identical to tuned fixed to four decimals, P8 check).
  P11 against per-frame (beta 1.5), cells with half the features noisier: udel_gore grid at 250 and 60 points,
      udel_gore_zupt, TUM corridor, EuRoC V1_01 path. At bad 2.5 the overall difference is clearly negative and no
      cell is clearly worse; at bad 1.25 and 1.5 the overall difference is within +-5%.
  P12 against tuned fixed, all uneven cells (grid f 0.25 and 0.5 at 250 and 60 points, and the three held-out
      paths): at bad 1.25 and at bad 1.5 the overall difference is clearly negative; at bad 2.5 it is within +-5%.
  P13 noisy oracle (udel_gore, f 0.5, 250 points, bad 1.25/1.5/2.5): for each s the overall position penalty against
      the exact oracle lies between half and twice exp(2 s^2) - 1; at s = 0.4 it is not clearly better than per-frame.
  G2 bar: the log-spread s at which the noisy oracle keeps half of the exact oracle's gain over per-frame
      (linear interpolation between s = 0, 0.1, 0.2, 0.4 on those three cells).
'Overall' = for each seed, the mean ATE over the cells concerned; then the relative difference of the seed means,
a Wilcoxon signed-rank test over the paired seeds, and the number of seeds where the method under test is lower.
'Clearly' = p < 0.05. Runs above 10 m are left out of accuracy averages (none are expected in these cells).
Position decides every verdict; orientation is reported alongside."""
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
    done = lambda d: os.path.isfile(os.path.join(d, 'navcore_verified.txt' if '/t4d_' in d else 'state_estimate.txt'))
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


def main():
    t0 = time.time()
    lines, rows = [], []
    out = lambda s='': lines.append(s)
    load_cache(os.path.join(RES, 'figures', 'ate_cache.csv'))
    load_cache(os.path.join(RES, 'figures', 'ate_cache_t4d.csv'))

    grid = [(GORE, cond(1.0, f, b, n)) for n in ('', '60') for f in (0.25, 0.5) for b in BADS]
    held = [(t, cond(1.0, 0.5, b)) for t in HELD for b in BADS]
    f05 = [(t, c) for t, c in grid + held if '_f0.500_' in c]
    noisy_cells = [(GORE, cond(1.0, 0.5, b)) for b in BADS]
    uni_c = {g: cond(g, 0.0, g) for g in UNI}
    clean_c = {'250': cond(1.0, 0.0, 1.0), '60': cond(1.0, 0.0, 1.0, '60')}

    need = []
    for t, c in grid + held:
        for m in ('epi', 'oracle', 'pooled', 'tuned', 'stock'):
            need += [rundir(root(m, t), t, c, s) for s in SEEDS]
    for t, c in noisy_cells:
        need += [rundir(f't4d_noisy_s{sv}', t, c, s) for sv in SVALS for s in SEEDS]
        need += [rundir('t4d_epi_nu20', t, c, s) for s in SEEDS]
    for g, c in uni_c.items():
        for rt in ('t4d_epi_nu5', 't4tf_uniform', 't3a', 't4a_uniform'):
            need += [rundir(rt, GORE, c, s) for s in SEEDS]
    need += [rundir('t4c_uniform_sig2_beta1.50', GORE, uni_c[2.0], s) for s in SEEDS]
    for c in clean_c.values():
        for rt in ('t4d_epi_nu5', 't4c_uniform_beta1.50'):
            need += [rundir(rt, GORE, c, s) for s in SEEDS]
    ensure_ate(need)

    n_new = sum(1 for d in need if '/t4d_' in d and d in ATE)
    n_new_plan = 810 + 270 + 90
    partial = n_new < n_new_plan
    out(f'T.4d G1 summary, {time.strftime("%Y-%m-%d %H:%M")}. New runs with ATE: {n_new}/{n_new_plan}' +
        ('   PARTIAL: verdicts are not final' if partial else ''))
    out('Rules fixed 16 Oct before results (see the script header). * = p < 0.05. Negative = epipolar lower (better).')
    out()

    # ---- P9 ----
    out('P9  uniform noise, udel_gore, 250 points: runs that lost track (> 0.5 m) / diverged (> 10 m), of those found')
    lost_epi = 0
    for g in UNI:
        c = uni_c[g]
        parts = []
        for lab, rt in (('epipolar', 't4d_epi_nu5'), ('tuned fixed', 't4tf_uniform'), ('stock', 't3a'), ('oracle b=1', 't4a_uniform')):
            v = vec(rt, GORE, c)
            f = np.isfinite(v)
            parts.append(f'{lab} {int((v[f] > 0.5).sum())}/{int((v[f] > 10).sum())} of {int(f.sum())}')
            if rt == 't4d_epi_nu5':
                lost_epi += int((v[f] > 0.5).sum())
                me = np.mean(v[f]) if f.any() else math.nan
        out(f'    {g:.1f} px: ' + ' | '.join(parts) + f' | epipolar mean ATE {me:.3f} m')
    r2 = compare(vec('t4d_epi_nu5', GORE, uni_c[2.0]), vec('t4c_uniform_sig2_beta1.50', GORE, uni_c[2.0]))
    out(f'    at 2.0 px against the exact oracle at beta 1.5: {fmt(r2)}')
    n_uni = sum(int(np.isfinite(vec('t4d_epi_nu5', GORE, uni_c[g])).sum()) for g in UNI)
    p9 = 'HELD' if lost_epi == 0 else 'FAILED'
    out(f'P9  -> {p9}{" (partial)" if n_uni < 120 else ""}: epipolar lost track in {lost_epi} of {n_uni} runs')
    out()

    # ---- P10 ----
    out('P10 clean data (1.0 px), epipolar against tuned fixed (= per-feature at beta 1.5 on clean data)')
    ok10 = True
    for lab, c in clean_c.items():
        r = compare(vec('t4d_epi_nu5', GORE, c), vec('t4c_uniform_beta1.50', GORE, c))
        ro = compare(vec('t4d_epi_nu5', GORE, c, 1), vec('t4c_uniform_beta1.50', GORE, c, 1))
        ok10 = ok10 and np.isfinite(r['rel']) and abs(r['rel']) <= 0.08
        out(f'    {lab} points: position {fmt(r)} | orientation {fmt(ro)}')
        rows.append(['P10', GORE, c, 'epi', 'tuned(clean b1.5)', 'pos', r['n'], r['ma'], r['mb'], r['rel'], r['p'], r['wins']])
    out(f'P10 -> {"HELD" if ok10 else "FAILED"}: position within 8% at both point counts')
    out()

    # ---- per-cell table helper ----
    def table(name, cells, ma, mb):
        out(f'    {name}: per cell, position | orientation')
        for t, c in cells:
            r = compare(vec(root(ma, t), t, c), vec(root(mb, t), t, c))
            ro = compare(vec(root(ma, t), t, c, 1), vec(root(mb, t), t, c, 1))
            tag = f'{SHORT[t]:5s} f{float(c.split("_f")[1][:5]):.2f} bad{float(c.split("_bad")[1][:5]):.2f}' + (' n60' if c.endswith('_n60') else '     ')
            out(f'      {tag}  {fmt(r)}  |  {fmt(ro)}')
            rows.append([name, t, c, ma, mb, 'pos', r['n'], r['ma'], r['mb'], r['rel'], r['p'], r['wins']])
            rows.append([name, t, c, ma, mb, 'ori', ro['n'], ro['ma'], ro['mb'], ro['rel'], ro['p'], ro['wins']])

    # ---- P11 ----
    out('P11 epipolar against per-frame (beta 1.5), half the features noisier (grid 250 and 60 points, zupt, TUM, EuRoC)')
    table('P11 vs per-frame', f05, 'epi', 'pooled')
    res11 = {}
    for b in BADS:
        cells = [(t, c) for t, c in f05 if f'_bad{b:.3f}' in c]
        res11[b] = overall(cells, 'epi', 'pooled')
        ro = overall(cells, 'epi', 'pooled', 1)
        worse = [f'{SHORT[t]} {c}' for t, c in cells if clear_pos(compare(vec(root('epi', t), t, c), vec(root('pooled', t), t, c)))]
        res11[b]['worse'] = worse
        out(f'    overall bad {b}: position {fmt(res11[b])} | orientation {fmt(ro)}' + (f' | clearly worse in: {worse}' if worse else ''))
    a11 = clear_neg(res11[2.5]) and not res11[2.5]['worse']
    b11 = all(np.isfinite(res11[b]['rel']) and abs(res11[b]['rel']) <= 0.05 for b in (1.25, 1.5))
    out(f'P11 -> {"HELD" if a11 and b11 else "FAILED"}: (a) clearly better at 2.5, no cell clearly worse: {a11}; '
        f'(b) within 5% at 1.25 and 1.5: {b11}')
    out()

    # ---- P12 ----
    out('P12 epipolar against tuned fixed, all uneven cells')
    table('P12 vs tuned fixed', grid + held, 'epi', 'tuned')
    res12 = {}
    for b in BADS:
        cells = [(t, c) for t, c in grid + held if f'_bad{b:.3f}' in c]
        res12[b] = overall(cells, 'epi', 'tuned')
        out(f'    overall bad {b}: position {fmt(res12[b])} | orientation {fmt(overall(cells, "epi", "tuned", 1))}')
    a12 = clear_neg(res12[1.25]) and clear_neg(res12[1.5])
    b12 = np.isfinite(res12[2.5]['rel']) and abs(res12[2.5]['rel']) <= 0.05
    out(f'P12 -> {"HELD" if a12 and b12 else "FAILED"}: (a) clearly better at 1.25 and 1.5: {a12}; (b) within 5% at 2.5: {b12}')
    out()

    # ---- context: against the exact oracle and stock ----
    out('Context (no prediction): epipolar against the exact oracle and against stock, overall per bad level, all uneven cells')
    for b in BADS:
        cells = [(t, c) for t, c in grid + held if f'_bad{b:.3f}' in c]
        out(f'    bad {b}: vs exact oracle {fmt(overall(cells, "epi", "oracle"))} | vs stock {fmt(overall(cells, "epi", "stock"))}')
    out()

    # ---- P13 and the G2 bar ----
    out('P13 noisy oracle, udel_gore f 0.5, 250 points: position penalty against the exact oracle')
    M = lambda m: seedmean([vec(m if m.startswith('t4d_') else root(m, t), t, c) for t, c in noisy_cells])
    O, P, E = M('oracle'), M('pooled'), M('t4d_epi_nu5')
    ok13, kept = True, {0.0: 1.0}
    for sv in SVALS:
        s = float(sv)
        N = M(f't4d_noisy_s{sv}')
        r = compare(N, O)
        lo, hi = boot(N, O)
        th = math.exp(2 * s * s) - 1
        inband = np.isfinite(r['rel']) and 0.5 * th <= r['rel'] <= 2 * th
        ok13 = ok13 and inband
        gap = np.nanmean(P) - np.nanmean(O)
        kept[s] = (np.nanmean(P) - np.nanmean(N)) / gap if gap > 0 else math.nan
        out(f'    s {sv}: penalty {fmt(r)}, 95% CI [{100 * lo:+.1f}, {100 * hi:+.1f}]%, theory {100 * th:.1f}% '
            f'(band {50 * th:.1f}-{200 * th:.1f}%): {"in band" if inband else "OUT of band"} | share of the oracle gain over per-frame kept: {kept[s]:.2f}')
    r4 = compare(M('t4d_noisy_s0.40'), P)
    b13 = not clear_neg(r4)
    out(f'    s 0.40 against per-frame: {fmt(r4)} -> {"not clearly better (as predicted)" if b13 else "clearly better (against the prediction)"}')
    out(f'P13 -> {"HELD" if ok13 and b13 else "FAILED"}: (a) all three penalties in band: {ok13}; (b) s 0.4 no better than per-frame: {b13}')
    ks = sorted(kept)
    bar = None
    for s1, s2 in zip(ks, ks[1:]):
        k1, k2 = kept[s1], kept[s2]
        if np.isfinite(k1) and np.isfinite(k2) and k1 >= 0.5 > k2:
            bar = s1 + (k1 - 0.5) * (s2 - s1) / (k1 - k2)
            break
    gap = np.nanmean(P) - np.nanmean(O)
    kept_epi = (np.nanmean(P) - np.nanmean(E)) / gap if gap > 0 else math.nan
    out(f'G2 bar: the noisy oracle keeps half its gain over per-frame at s = ' +
        (f'{bar:.2f}' if bar is not None else ('above 0.4' if all(np.isfinite(kept[k]) and kept[k] >= 0.5 for k in ks) else 'below 0.1 or undefined')) +
        f'. Epipolar on the same cells keeps {kept_epi:.2f} of the gain.')
    out()

    # ---- estimator quality ----
    out('Estimator quality from the gate logs (MSCKF rows, seeds 1-5): s = spread of log(sigma_used / (beta sigma_true)),')
    out('medians of sigma_used / (beta sigma_true), rank correlation with sigma_true, mean gate chi2/dof (1/beta^2 = 0.44 if exact)')
    for lab, rt, cells in (('epipolar, f 0.5 grid 250', 't4d_epi_nu5', [x for x in f05 if x[0] == GORE and not x[1].endswith('_n60')]),
                           ('epipolar, f 0.5 grid 60', 't4d_epi_nu5', [x for x in f05 if x[1].endswith('_n60')]),
                           ('epipolar, held-out', 't4d_epi_nu5', held),
                           ('epipolar, clean 1.0 px', 't4d_epi_nu5', [(GORE, clean_c['250'])]),
                           ('nu0 20, f 0.5 grid 250', 't4d_epi_nu20', noisy_cells),
                           ('exact oracle, f 0.5 grid 250', 't4cal_perfeat_b1.50', noisy_cells)):
        q = quality(rt, cells)
        if q is None:
            out(f'    {lab:30s} no gate logs found')
            continue
        txt = f'    {lab:30s} s {q["s"]:.3f} | median clean {q["med_clean"]:.2f}'
        if 'med_noisy' in q:
            txt += f', noisy {q["med_noisy"]:.2f} | rank corr {q["rho"]:.2f} | chi2/dof clean {q["chi_clean"]:.2f}, noisy {q["chi_noisy"]:.2f}'
        else:
            txt += f' | chi2/dof {q["chi_clean"]:.2f}'
        out(txt + f' | {q["rows"]} rows')
    out()

    # ---- exploratory: nu0 = 20 ----
    out('Exploratory (no prediction): nu0 = 20, udel_gore f 0.5, 250 points, overall over bad 1.25/1.5/2.5')
    for mb, lab in (('t4d_epi_nu5', 'nu0 5'), ('oracle', 'exact oracle'), ('pooled', 'per-frame'), ('tuned', 'tuned fixed')):
        r = compare(M('t4d_epi_nu20'), M(mb))
        out(f'    nu0 20 against {lab:12s}: {fmt(r)}')
    for t, c in noisy_cells:
        rows.append(['nu20', t, c, 'epi20', 'epi', 'pos', *[compare(vec('t4d_epi_nu20', t, c), vec('t4d_epi_nu5', t, c))[k] for k in ('n', 'ma', 'mb', 'rel', 'p', 'wins')]])
    out()
    out(f'({time.time() - t0:.0f} s)')

    txt = '\n'.join(lines)
    print(txt)
    open(os.path.join(RES, 't4d_g1_summary.txt'), 'w').write(txt + '\n')
    with open(os.path.join(RES, 't4d_g1_summary.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['block', 'traj', 'cond', 'method', 'baseline', 'metric', 'n', 'mean_method', 'mean_baseline', 'rel', 'p', 'lower_in'])
        w.writerows(rows)


if __name__ == '__main__':
    main()
