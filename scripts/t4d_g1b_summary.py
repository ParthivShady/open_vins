#!/usr/bin/env python3
"""NavCore T.4d G1b summary: verdicts for P14-P18 (frozen 16 Oct, before any G1b run).
Usage:  ~/navcore_ws/.venv/bin/python scripts/t4d_g1b_summary.py
Writes results/t4d_g1b_summary.txt and .csv; ATE of new runs cached in results/figures/ate_cache_t4d.csv.

G1b = mode 4: robust frame level (25th percentile of per-feature means); a feature gets its own value only if clearly
noisier (chi-square test, 1%). Verdict cells and rules, fixed 16 Oct before any G1b result was seen:
  P14 uniform noise 1.5, 2.0, 2.5, 3.0 px, udel_gore, 250 points: no G1b run loses track (ATE > 0.5 m).
  P15 clean 1.0 px, udel_gore: |position difference| against tuned fixed <= 3% at 250 points and <= 5% at 60 points
      (tuned fixed represented by the per-feature filter at beta 1.5 on clean data, identical to four decimals).
  P16 against tuned fixed, all uneven cells (grid f 0.25 and 0.5 at 250 and 60 points; zupt, TUM, EuRoC paths):
      the overall difference is not clearly positive at any bad level, and is clearly negative at bad 1.5.
  P17 against per-frame (beta 1.5), the cells with half the features noisier: clearly negative overall at bad 2.5;
      not clearly positive overall at bad 1.25 and 1.5.
  P18 fresh seeds 31-45 (udel_gore and TUM, f 0.5, 250 points) against tuned fixed run on the same seeds: the overall
      difference is not clearly positive at any bad level.
'Overall' = per seed, the mean ATE over the cells concerned, then the relative difference of the seed means, a
Wilcoxon signed-rank test over the paired seeds, and the number of seeds where G1b is lower. 'Clearly' = p < 0.05.
Position decides every verdict; orientation is reported alongside. Runs above 10 m are left out of averages."""
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
    return {'g1b': 't4d_g1b', 'epi': 't4d_epi_nu5', 'epi20': 't4d_epi_nu20', 'ftuned': 't4d_fresh_tuned',
            'oracle': 't4val_perfeat_b1.50' if held else 't4cal_perfeat_b1.50',
            'pooled': 't4val_pooled_b1.50' if held else 't4cal_pooled_b1.50',
            'tuned': 't4tf_val' if held else 't4tf_t3bgrid',
            'stock': 't4val_fixed' if held else 't3b'}.get(method, method)


FRESH = list(range(31, 46))


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


def vec(rt, traj, c, k=0, seeds=None):
    return np.array([ATE.get(rundir(rt, traj, c, s), (math.nan, math.nan))[k] for s in (seeds or SEEDS)])


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


def overall(cells, ma, mb, k=0, seeds=None):
    """cells: list of (traj, c); ma, mb: method names"""
    return compare(seedmean([vec(root(ma, t), t, c, k, seeds) for t, c in cells]), seedmean([vec(root(mb, t), t, c, k, seeds) for t, c in cells]))


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


def flag_rates(rt, cells, seeds=range(1, 6)):
    out = {'clean': [0, 0], 'noisy': [0, 0]}
    for t, c in cells:
        for s in seeds:
            d = rundir(rt, t, c, s)
            for fn in ('gate_feat.csv', 'gate_feat.csv.gz'):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    fh = gzip.open(p, 'rt') if fn.endswith('.gz') else open(p)
                    rows = [r for r in csv.reader(fh)][1:]
                    by_t = {}
                    for r in rows:
                        if len(r) >= 9 and r[1] == '0':
                            by_t.setdefault(r[0], []).append((float(r[3]), float(r[4])))
                    for grp in by_t.values():
                        if len(grp) < 2:
                            continue
                        lo = min(su for _, su in grp)
                        smin = min(st for st, _ in grp)
                        for st, su in grp:
                            k = 'clean' if st <= 1.0 + 1e-9 else 'noisy'
                            out[k][0] += su > lo * (1 + 1e-6)
                            out[k][1] += 1
                    break
    return {k: (v[0] / v[1] if v[1] else math.nan, v[1]) for k, v in out.items()}


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
    fresh = [(t, cond(1.0, 0.5, b)) for t in (GORE, 'tum_corridor1_512_16_okvis') for b in BADS]
    uni_c = {g: cond(g, 0.0, g) for g in UNI}
    clean_c = {'250': cond(1.0, 0.0, 1.0), '60': cond(1.0, 0.0, 1.0, '60')}

    need = []
    for t, c in grid + held:
        for m in ('g1b', 'epi', 'oracle', 'pooled', 'tuned', 'stock'):
            need += [rundir(root(m, t), t, c, s) for s in SEEDS]
    for t, c in fresh:
        need += [rundir('t4d_g1b', t, c, s) for s in FRESH] + [rundir('t4d_fresh_tuned', t, c, s) for s in FRESH]
    for g, c in uni_c.items():
        for rt in ('t4d_g1b', 't4d_epi_nu5', 't4tf_uniform', 't3a', 't4a_uniform'):
            need += [rundir(rt, GORE, c, s) for s in SEEDS]
    need += [rundir('t4c_uniform_sig2_beta1.50', GORE, uni_c[2.0], s) for s in SEEDS]
    for c in clean_c.values():
        for rt in ('t4d_g1b', 't4d_epi_nu5', 't4c_uniform_beta1.50'):
            need += [rundir(rt, GORE, c, s) for s in SEEDS]
    ensure_ate(need)

    newd = sorted({d for d in need if '/t4d_g1b/' in d or '/t4d_fresh_tuned/' in d})
    n_new = sum(1 for d in newd if d in ATE)
    partial = n_new < 990
    out(f'T.4d G1b summary, {time.strftime("%Y-%m-%d %H:%M")}. New runs with ATE: {n_new}/990' +
        ('   PARTIAL: verdicts are not final' if partial else ''))
    out('Rules fixed 16 Oct before results (see the script header). * = p < 0.05. Negative = G1b lower (better).')
    out()

    # ---- P14 ----
    out('P14 uniform noise, udel_gore, 250 points: lost track (> 0.5 m) / diverged (> 10 m), of those found')
    lost = 0
    for g in UNI:
        c = uni_c[g]
        parts = []
        for lab, rt in (('G1b', 't4d_g1b'), ('G1 epipolar', 't4d_epi_nu5'), ('tuned fixed', 't4tf_uniform'), ('stock', 't3a')):
            v = vec(rt, GORE, c)
            f = np.isfinite(v)
            parts.append(f'{lab} {int((v[f] > 0.5).sum())}/{int((v[f] > 10).sum())} of {int(f.sum())}')
            if rt == 't4d_g1b':
                lost += int((v[f] > 0.5).sum())
        r = compare(vec('t4d_g1b', GORE, c), vec('t4d_epi_nu5', GORE, c))
        out(f'    {g:.1f} px: ' + ' | '.join(parts) + f' | G1b vs G1 epipolar {fmt(r)}')
    out(f'    at 2.0 px against the exact oracle at beta 1.5: {fmt(compare(vec("t4d_g1b", GORE, uni_c[2.0]), vec("t4c_uniform_sig2_beta1.50", GORE, uni_c[2.0])))}')
    out(f'    at 1.5 px against tuned fixed: {fmt(compare(vec("t4d_g1b", GORE, uni_c[1.5]), vec("t4tf_uniform", GORE, uni_c[1.5])))}')
    n_uni = sum(int(np.isfinite(vec('t4d_g1b', GORE, uni_c[g])).sum()) for g in UNI)
    out(f'P14 -> {"HELD" if lost == 0 else "FAILED"}{" (partial)" if n_uni < 120 else ""}: G1b lost track in {lost} of {n_uni} runs')
    out()

    # ---- P15 ----
    out('P15 clean data (1.0 px), G1b against tuned fixed (= per-feature at beta 1.5 on clean data)')
    ok15 = True
    for lab, c in clean_c.items():
        r = compare(vec('t4d_g1b', GORE, c), vec('t4c_uniform_beta1.50', GORE, c))
        ro = compare(vec('t4d_g1b', GORE, c, 1), vec('t4c_uniform_beta1.50', GORE, c, 1))
        lim = 0.03 if lab == '250' else 0.05
        ok15 = ok15 and np.isfinite(r['rel']) and abs(r['rel']) <= lim
        out(f'    {lab} points (limit {100 * lim:.0f}%): position {fmt(r)} | orientation {fmt(ro)} | G1 epipolar was {fmt(compare(vec("t4d_epi_nu5", GORE, c), vec("t4c_uniform_beta1.50", GORE, c)))}')
    out(f'P15 -> {"HELD" if ok15 else "FAILED"}')
    out()

    def table(name, cells, ma, mb):
        out(f'    {name}: per cell, position | orientation')
        for t, c in cells:
            r = compare(vec(root(ma, t), t, c), vec(root(mb, t), t, c))
            ro = compare(vec(root(ma, t), t, c, 1), vec(root(mb, t), t, c, 1))
            tag = f'{SHORT[t]:5s} f{float(c.split("_f")[1][:5]):.2f} bad{float(c.split("_bad")[1][:5]):.2f}' + (' n60' if c.endswith('_n60') else '     ')
            out(f'      {tag}  {fmt(r)}  |  {fmt(ro)}')
            for k, rr in (('pos', r), ('ori', ro)):
                rows.append([name, t, c, ma, mb, k, rr['n'], rr['ma'], rr['mb'], rr['rel'], rr['p'], rr['wins']])

    # ---- P16 ----
    out('P16 G1b against tuned fixed, all uneven cells')
    table('P16 vs tuned fixed', grid + held, 'g1b', 'tuned')
    res = {}
    for b in BADS:
        cells = [(t, c) for t, c in grid + held if f'_bad{b:.3f}' in c]
        res[b] = overall(cells, 'g1b', 'tuned')
        out(f'    overall bad {b}: position {fmt(res[b])} | orientation {fmt(overall(cells, "g1b", "tuned", 1))} | G1 epipolar was {fmt(overall(cells, "epi", "tuned"))}')
    a16 = not any(clear_pos(res[b]) for b in BADS)
    b16 = clear_neg(res[1.5])
    out(f'P16 -> {"HELD" if a16 and b16 else "FAILED"}: (a) not clearly worse at any level: {a16}; (b) clearly better at 1.5: {b16}')
    out()

    # ---- P17 ----
    out('P17 G1b against per-frame (beta 1.5), half the features noisier')
    table('P17 vs per-frame', f05, 'g1b', 'pooled')
    res = {}
    for b in BADS:
        cells = [(t, c) for t, c in f05 if f'_bad{b:.3f}' in c]
        res[b] = overall(cells, 'g1b', 'pooled')
        out(f'    overall bad {b}: position {fmt(res[b])} | orientation {fmt(overall(cells, "g1b", "pooled", 1))}')
    a17 = clear_neg(res[2.5])
    b17 = not clear_pos(res[1.25]) and not clear_pos(res[1.5])
    out(f'P17 -> {"HELD" if a17 and b17 else "FAILED"}: (a) clearly better at 2.5: {a17}; (b) not clearly worse at 1.25 and 1.5: {b17}')
    out()

    # ---- P18 ----
    out('P18 fresh seeds 31-45, udel_gore and TUM, f 0.5, 250 points: G1b against tuned fixed run on the same seeds')
    ok18 = True
    for t, c in fresh:
        r = compare(vec('t4d_g1b', t, c, 0, FRESH), vec('t4d_fresh_tuned', t, c, 0, FRESH))
        out(f'      {SHORT[t]:5s} bad{float(c.split("_bad")[1][:5]):.2f}  {fmt(r)}')
        rows.append(['P18 fresh vs tuned', t, c, 'g1b', 'tuned', 'pos', r['n'], r['ma'], r['mb'], r['rel'], r['p'], r['wins']])
    for b in BADS:
        cells = [(t, c) for t, c in fresh if f'_bad{b:.3f}' in c]
        r = compare(seedmean([vec('t4d_g1b', t, c, 0, FRESH) for t, c in cells]), seedmean([vec('t4d_fresh_tuned', t, c, 0, FRESH) for t, c in cells]))
        ok18 = ok18 and not clear_pos(r)
        out(f'    overall bad {b}: position {fmt(r)}')
    n_fresh = sum(int(np.isfinite(vec('t4d_g1b', t, c, 0, FRESH)).sum()) for t, c in fresh)
    out(f'P18 -> {"HELD" if ok18 else "FAILED"}{" (partial)" if n_fresh < 90 else ""}: not clearly worse than tuned fixed at any level on fresh seeds')
    out()

    # ---- context ----
    out('Context (no prediction): G1b against G1 epipolar, the exact oracle and stock, overall per bad level, all uneven cells')
    for b in BADS:
        cells = [(t, c) for t, c in grid + held if f'_bad{b:.3f}' in c]
        out(f'    bad {b}: vs G1 epipolar {fmt(overall(cells, "g1b", "epi"))} | vs exact oracle {fmt(overall(cells, "g1b", "oracle"))} | vs stock {fmt(overall(cells, "g1b", "stock"))}')
    out()
    out('Diagnostics from the gate logs (MSCKF rows, seeds 1-5): share of rows where the feature was flagged as noisier,')
    out('and the estimator quality as in G1 (s, medians of sigma_used / (beta sigma_true), rank correlation, chi2/dof)')
    for lab, cells in (('f 0.25 grid 250', [x for x in grid if '_f0.250_' in x[1] and not x[1].endswith('_n60')]),
                       ('f 0.5 grid 250', [x for x in grid if '_f0.500_' in x[1] and not x[1].endswith('_n60')]),
                       ('f 0.5 grid 60', [x for x in grid if '_f0.500_' in x[1] and x[1].endswith('_n60')]),
                       ('held-out', held), ('clean 1.0 px', [(GORE, clean_c['250'])])):
        fr = flag_rates('t4d_g1b', cells)
        q = quality('t4d_g1b', cells)
        txt = f'    {lab:16s} flagged: clean {100 * fr["clean"][0]:.1f}%'
        if fr['noisy'][1]:
            txt += f', noisy {100 * fr["noisy"][0]:.1f}%'
        if q:
            txt += f' | s {q["s"]:.3f} | median clean {q["med_clean"]:.2f}' + (f', noisy {q["med_noisy"]:.2f}' if 'med_noisy' in q else '') + \
                   (f' | rank corr {q["rho"]:.2f}' if 'rho' in q else '') + f' | chi2/dof clean {q["chi_clean"]:.2f}' + (f', noisy {q["chi_noisy"]:.2f}' if 'chi_noisy' in q else '')
        out(txt)
    out()
    out(f'({time.time() - t0:.0f} s)')

    txt = '\n'.join(lines)
    print(txt)
    open(os.path.join(RES, 't4d_g1b_summary.txt'), 'w').write(txt + '\n')
    with open(os.path.join(RES, 't4d_g1b_summary.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['block', 'traj', 'cond', 'method', 'baseline', 'metric', 'n', 'mean_method', 'mean_baseline', 'rel', 'p', 'lower_in'])
        w.writerows(rows)


if __name__ == '__main__':
    main()
