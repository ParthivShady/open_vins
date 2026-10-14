#!/usr/bin/env python3
"""Audit-batch summary (13 Oct 2026): beta at sigma 2, P7b (new held-out path euroc_V1_01_easy), P8 (tuned fixed).
Predictions, written in the Notion roadmap before the batch ran:
  beta at sigma 2: if the extra error scales with sigma, the curve has the same shape as at sigma 1: beta 2.0 worse than
    1.5 and the best value between 1.3 and 1.75. If 2.0 beats 1.5, the error grows faster than sigma.
  P7b: on euroc_V1_01_easy (beta frozen at 1.5, f 0.5, 250 pts) per-feature beats pooled in position, gap largest at
    sigma_bad 2.5.
  P8, tuned fixed (sigma0 1.5): (a) within ~5% of per-feature and not significant in every 250-pt grid cell;
    (b) per-feature better by > 5%, p < 0.05, at 60 pts with f 0.5; (c) on the uniform sweep tuned fixed diverges at
    sigma 3.0 and at least partly at 2.5, per-feature never; (d) held-out cells (zupt, tum, euroc): as (a).
Stats: paired by seed; runs with ATE > 10 m (diverged) or no ATE (failed) are counted and left out of paired stats;
relative differences with 95% t intervals; Wilcoxon signed-rank p; 'overall' = per-seed mean of per-cell relative
differences. Negative = first method better.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4_audit_summary.py | tee ~/navcore_ws/results/t4_audit_summary.txt"""
import os, glob, gzip, csv, subprocess, math
import numpy as np
from scipy import stats

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'
PY = os.environ.get('NAVCORE_PY', HOME + '/navcore_ws/.venv/bin/python')
ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
SEEDS = range(1, 31); DIV = 10.0
EU = 'euroc_V1_01_easy'; HELD = ['udel_gore_zupt', 'tum_corridor1_512_16_okvis', EU]; SB = (1.25, 1.5, 2.5)

def cond(sig, f, b, n=''): return 'sig%.3f_f%.3f_bad%.3f' % (sig, f, b) + ('_n' + n if n else '')

def find_cond(root, traj, prefix):
    c = sorted(os.path.basename(p) for p in glob.glob(f'{root}/{traj}/{prefix}*') if '_n' not in os.path.basename(p))
    return c[0] if c else None

A = {}
def _parse(out):
    for line in out.strip().splitlines():
        p = line.split('\t')
        try: A[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))
        except (ValueError, IndexError): pass

def get(root, traj, c):
    """-> (ok {seed: (pos, ori)}, diverged, failed, missing)"""
    dirs = [os.path.normpath(f'{root}/{traj}/{c}/seed{s}') for s in SEEDS]
    todo = [d for d in dirs if d not in A and os.path.isfile(d + '/state_estimate.txt')]
    if todo:
        r = subprocess.run([PY, ATE] + todo, capture_output=True, text=True); _parse(r.stdout)
        for d in todo:
            if d not in A: _parse(subprocess.run([PY, ATE, d], capture_output=True, text=True).stdout)
    ok, div, fail, miss = {}, 0, 0, 0
    for s, d in zip(SEEDS, dirs):
        if not os.path.isfile(d + '/state_estimate.txt'): miss += 1; continue
        v = A.get(d)
        if v is None or not math.isfinite(v[0]): fail += 1
        elif v[0] > DIV: div += 1
        else: ok[s] = v
    return ok, div, fail, miss

def mean(ok, k): return f'{np.mean([v[k] for v in ok.values()]):.4f}' if ok else 'n/a'
def counts(D): return ', '.join(f'{m} {len(v[0])} ok/{v[1]} div/{v[2]} fail/{v[3]} miss' for m, v in D.items())

def _stat(v, base):
    ci = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v))
    p = stats.wilcoxon(v).pvalue if np.any(v != 0) else 1.0
    return dict(rel=100 * v.mean() / base, ci=100 * ci / base, p=p, wins=int((v < 0).sum()), n=len(v))

def paired(a, b, k):
    s = sorted(set(a) & set(b))
    if len(s) < 5: return None
    x = np.array([a[i][k] for i in s]); y = np.array([b[i][k] for i in s])
    return _stat(x - y, y.mean())

def overall(cells, k):  # cells: list of (a_ok, b_ok)
    per = {}
    for a, b in cells:
        for s in set(a) & set(b): per.setdefault(s, []).append((a[s][k] - b[s][k]) / b[s][k])
    v = np.array([np.mean(x) for x in per.values()])
    return _stat(v, 1.0) if len(v) >= 5 else None

def fmtp(r): return 'n/a' if r is None else f"{r['rel']:+.1f}% [+-{r['ci']:.1f}%] p={r['p']:.1e}, first better {r['wins']}/{r['n']}"

def opentext(p):
    if os.path.isfile(p): return open(p, newline='')
    if os.path.isfile(p + '.gz'): return gzip.open(p + '.gz', 'rt', newline='')
    return None

def gates(dirs):
    acc = {'clean': [0, 0, 0.0, 0], 'noisy': [0, 0, 0.0, 0]}
    for d in dirs:
        fh = opentext(d + '/gate_feat.csv')
        if fh is None: continue
        with fh:
            rd = csv.reader(fh); next(rd, None)
            for r in rd:
                try:
                    a = acc['clean' if float(r[3]) < 1.01 else 'noisy']
                    a[0] += 1; a[1] += int(r[8]); a[2] += float(r[6]); a[3] += int(r[5])
                except (ValueError, IndexError): pass
    return ' | '.join(f'{k} {100 * v[1] / v[0]:.1f}% accepted, chi2/dof {v[2] / v[3]:.2f}' for k, v in acc.items() if v[0] and v[3])

def compare(D, pairs, indent='    '):
    for k, lab in ((0, 'pos (m)'), (1, 'ori (deg)')):
        print(f'{indent}{lab}: ' + ' | '.join(f'{m} {mean(D[m][0], k)}' for m in D))
        for a, b in pairs: print(f'{indent}  [{a} vs {b}] ' + fmtp(paired(D[a][0], D[b][0], k)))

print('T.4 audit-batch summary | paired by seed | ATE > 10 m = diverged, excluded | negative = first method better')

# ---------------- A. beta at uniform sigma ----------------
print('\n================ A. beta at uniform sigma (udel_gore, 250 pts, per-feature oracle) ================')
CURVES = {1.0: [(1.0, 't3b'), (1.25, 't4c_uniform_beta1.25'), (1.5, 't4c_uniform_beta1.50'), (2.0, 't4c_uniform_beta2.00')],
          2.0: [(1.0, 't4a_uniform'), (1.15, 't4c_uniform_sig2_beta1.15'), (1.3, 't4c_uniform_sig2_beta1.30'),
                (1.5, 't4c_uniform_sig2_beta1.50'), (1.75, 't4c_uniform_sig2_beta1.75'), (2.0, 't4c_uniform_sig2_beta2.00')]}
beta_verdict = None
for sig, rows in CURVES.items():
    data = {}
    for beta, b in rows:
        c = find_cond(f'{RES}/{b}', 'udel_gore', 'sig%.3f_f0.000' % sig)
        if c is None: print(f'  sigma {sig:g}, beta {beta}: no uniform folder under {b}'); continue
        data[beta] = get(f'{RES}/{b}', 'udel_gore', c)
    print(f'\n  sigma = {sig:g} px')
    ref = data.get(1.5)
    for beta in sorted(data):
        ok, dv, fl, ms = data[beta]
        line = f'    beta {beta:4.2f}: pos {mean(ok, 0)} m, ori {mean(ok, 1)} deg ({len(ok)} ok, {dv} div, {fl} fail, {ms} miss)'
        if ref is not None and beta != 1.5:
            line += f'\n               vs 1.5: pos {fmtp(paired(ok, ref[0], 0))} | ori {fmtp(paired(ok, ref[0], 1))}'
        print(line)
    m = {be: np.mean([v[0] for v in d[0].values()]) for be, d in data.items() if d[0]}
    mo = {be: np.mean([v[1] for v in d[0].values()]) for be, d in data.items() if d[0]}
    if m:
        print(f'    best beta by mean position ATE: {min(m, key=m.get):.2f} | by mean orientation ATE: {min(mo, key=mo.get):.2f}')
    if sig == 2.0 and 2.0 in m and 1.5 in m:
        bp = min(m, key=m.get)
        if m[2.0] > m[1.5] and bp in (1.3, 1.5, 1.75): beta_verdict = f'HOLDS (scales with sigma): best {bp:.2f}, 2.0 worse than 1.5'
        elif m[2.0] < m[1.5]: beta_verdict = f'FAILS: beta 2.0 beats 1.5 (best {bp:.2f}) -> extra error grows faster than sigma'
        else: beta_verdict = f'FAILS on the range: best {bp:.2f}'

# ---------------- B. P7b ----------------
print(f'\n================ B. P7b: new held-out path {EU} (beta frozen 1.5, f 0.5, 250 pts) ================')
MB = [('perfeat@1.5', 't4val_perfeat_b1.50'), ('pooled@1.5', 't4val_pooled_b1.50'), ('fixed@1.0', 't4val_fixed'), ('tuned@1.5', 't4tf_val')]
cellsB = {}
for b in SB:
    D = {m: get(f'{RES}/{r}', EU, cond(1.0, 0.5, b)) for m, r in MB}
    cellsB[b] = D
    print(f'\n  sigma_bad {b}: {counts(D)}')
    compare(D, [('perfeat@1.5', 'pooled@1.5'), ('perfeat@1.5', 'fixed@1.0'), ('perfeat@1.5', 'tuned@1.5')])
print('\n  overall over the three cells:')
for a, bb in (('perfeat@1.5', 'pooled@1.5'), ('perfeat@1.5', 'fixed@1.0'), ('perfeat@1.5', 'tuned@1.5')):
    for k, lab in ((0, 'pos'), (1, 'ori')):
        print(f'    [{a} vs {bb}] {lab}: ' + fmtp(overall([(cellsB[b][a][0], cellsB[b][bb][0]) for b in SB], k)))
ovB = overall([(cellsB[b]['perfeat@1.5'][0], cellsB[b]['pooled@1.5'][0]) for b in SB], 0)
relB = {b: paired(cellsB[b]['perfeat@1.5'][0], cellsB[b]['pooled@1.5'][0], 0) for b in SB}
if ovB is None or any(r is None for r in relB.values()): p7b = 'NOT ENOUGH DATA'
else:
    better = ovB['rel'] < 0 and ovB['p'] < 0.05
    largest = min(SB, key=lambda b: relB[b]['rel']) == 2.5
    p7b = ('HOLDS' if better and largest else 'FAILS') + f" (overall {ovB['rel']:+.1f}%, p={ovB['p']:.1e}; " + \
          ', '.join(f"{b}: {relB[b]['rel']:+.1f}%" for b in SB) + ')'
print('\n  udel_arl, seed 1 only (stopped after one seed for cost; descriptive, no statistics):')
for b in SB:
    print(f'    sigma_bad {b}: ' + ' | '.join(f'{m} pos {mean(get(f"{RES}/{r}", "udel_arl", cond(1.0, 0.5, b))[0], 0)} m'
                                           for m, r in MB[:3]))

# ---------------- C. P8 ----------------
print('\n================ C. P8: tuned fixed (sigma0 1.5) ================')
GRID = [(f, b) for f in (0.25, 0.5) for b in SB]
MC = [('perfeat@1.5', 't4cal_perfeat_b1.50'), ('tuned@1.5', 't4tf_t3bgrid'), ('stock@1.0', 't3b')]
a_out, cellsC = [], {}
for n in ('', '60'):
    print(f'\n  -- T.3b grid, udel_gore, {n or 250} pts')
    for f, b in GRID:
        c = cond(1.0, f, b, n)
        D = {m: get(f'{RES}/{r}', 'udel_gore', c) for m, r in MC}
        cellsC[(n, f, b)] = D
        print(f'\n   f {f}, sigma_bad {b}: {counts(D)}')
        compare(D, [('perfeat@1.5', 'tuned@1.5'), ('tuned@1.5', 'stock@1.0')], '      ')
        print('      tuned gate (MSCKF): ' + gates([f'{RES}/t4tf_t3bgrid/udel_gore/{c}/seed{s}' for s in SEEDS]))
        r = paired(D['perfeat@1.5'][0], D['tuned@1.5'][0], 0)
        if n == '' and (r is None or abs(r['rel']) > 5 or r['p'] < 0.05):
            a_out.append(f"f {f} bad {b}: " + ('n/a' if r is None else f"{r['rel']:+.1f}% p={r['p']:.1e}"))
ovb = overall([(cellsC[('60', 0.5, b)]['perfeat@1.5'][0], cellsC[('60', 0.5, b)]['tuned@1.5'][0]) for b in SB], 0)
print('\n  -- held-out cells (f 0.5, 250 pts)')
MD = [('perfeat@1.5', 't4val_perfeat_b1.50'), ('tuned@1.5', 't4tf_val'), ('pooled@1.5', 't4val_pooled_b1.50'), ('stock@1.0', 't4val_fixed')]
d_out, cellsD = [], []
for tr in HELD:
    for b in SB:
        D = {m: get(f'{RES}/{r}', tr, cond(1.0, 0.5, b)) for m, r in MD}
        cellsD.append(D)
        print(f'\n   {tr}, sigma_bad {b}: {counts(D)}')
        compare(D, [('perfeat@1.5', 'tuned@1.5'), ('tuned@1.5', 'stock@1.0')], '      ')
        print('      tuned gate (MSCKF): ' + gates([f'{RES}/t4tf_val/{tr}/{cond(1.0, 0.5, b)}/seed{s}' for s in SEEDS]))
        r = paired(D['perfeat@1.5'][0], D['tuned@1.5'][0], 0)
        if r is None or abs(r['rel']) > 5 or r['p'] < 0.05:
            d_out.append(f"{tr} bad {b}: " + ('n/a' if r is None else f"{r['rel']:+.1f}% p={r['p']:.1e}"))
print('\n  overall, per-feature vs tuned fixed:')
for lab, cl in (('grid 250 pts', [(cellsC[('', f, b)]['perfeat@1.5'][0], cellsC[('', f, b)]['tuned@1.5'][0]) for f, b in GRID]),
                ('grid 60 pts', [(cellsC[('60', f, b)]['perfeat@1.5'][0], cellsC[('60', f, b)]['tuned@1.5'][0]) for f, b in GRID]),
                ('held-out', [(D['perfeat@1.5'][0], D['tuned@1.5'][0]) for D in cellsD])):
    print(f'    {lab:13s} pos: {fmtp(overall(cl, 0))} | ori: {fmtp(overall(cl, 1))}')
print('\n  -- uniform sweep (P8 c): divergence counts')
U = f'{RES}/t4tf_uniform'; cres = 'PENDING (part 4 not run yet)'
if os.path.isdir(U):
    tot = {}
    for p in sorted(glob.glob(U + '/*/*')):
        tr, c = os.path.basename(os.path.dirname(p)), os.path.basename(p)
        D = {m: get(f'{RES}/{r}', tr, c) for m, r in (('tuned@1.5', 't4tf_uniform'), ('perfeat@1.0', 't4a_uniform'), ('stock@1.0', 't3a'))}
        sig = float(c[3:8])
        print(f'    {tr:28s} sigma {sig:.2f}: ' + ' | '.join(f'{m} div {v[1]}, fail {v[2]}, miss {v[3]}' for m, v in D.items()))
        tt, pf = D['tuned@1.5'], D['perfeat@1.0']
        t = tot.setdefault(sig, [0, 0, 0, 0]); t[0] += tt[1] + tt[2]; t[1] += len(tt[0]) + tt[1] + tt[2]; t[2] += pf[1] + pf[2]; t[3] += len(pf[0]) + pf[1] + pf[2]
    cres = '; '.join(f'sigma {s:.2f}: tuned {t[0]}/{t[1]} diverged or failed, per-feature {t[2]}/{t[3]}' for s, t in sorted(tot.items()))

print('\n================ Verdicts (as pre-registered) ================')
print(f'  beta at sigma 2: {beta_verdict or "NOT ENOUGH DATA"}')
print(f'  P7b: {p7b}')
print('  P8 (a) 250-pt grid, within ~5% and n.s. in every cell: ' + ('HOLDS' if not a_out else 'FAILS in ' + '; '.join(a_out)))
print('  P8 (b) 60 pts, f 0.5, per-feature > 5% better, p < 0.05: ' +
      ('n/a' if ovb is None else ('HOLDS' if ovb['rel'] < -5 and ovb['p'] < 0.05 else 'FAILS') + f" ({ovb['rel']:+.1f}%, p={ovb['p']:.1e})"))
print(f'  P8 (c) uniform sweep: {cres}')
print('  P8 (d) held-out, within ~5% and n.s. in every cell: ' + ('HOLDS' if not d_out else 'FAILS in ' + '; '.join(d_out)))
