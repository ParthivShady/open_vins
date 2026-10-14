#!/usr/bin/env python3
"""NavCore T.3/T.4 figures for the November review and the report (14 Oct 2026).

Reads the raw result folders (read-only), computes ATE with t3_ate.py (cached in figures/ate_cache.csv so reruns are
fast), and writes every figure as PDF (vector, for LaTeX) and PNG (200 dpi, for slides) to
~/navcore_ws/results/figures/, plus captions.md with a draft caption and the numbers behind each figure.

Figures
  fig1_divergence_cliff    divergence rate vs true pixel noise (stock fixed, tuned fixed, per-feature) and vs sigma/sigma0
  fig2_gate_theory         chi-square gate acceptance vs noise ratio r = sigma_true/sigma_used: measured vs predicted
  fig3_gate_mechanism      gate acceptance of clean and noisy features vs sigma_bad, per method (held-out cells)
  fig4_regime_map_pos/ori  paired relative ATE difference, per-feature minus each baseline, every cell, significance marked
  fig5_heldout_bars_pos    ATE (mean, 95% CI) on the held-out paths, four methods
  fig6_grid_bars_pos       ATE (mean, 95% CI) on the T.3b grid, four methods
  fig7_beta_curves         ATE vs inflation factor beta at sigma 1 and 2 px (paired ratio to beta = 1.5)
  fig8_uniform_accuracy    ATE of runs that did not diverge vs sigma, per trajectory
  fig9_trajectory_example  top view of one udel_gore run at sigma 2.5: ground truth and the three filters

Usage: ~/navcore_ws/.venv/bin/python scripts/make_t4_figures.py [--only fig1,fig4] [--gate-seeds 10]
"""
import os, re, csv, glob, gzip, math, argparse, subprocess, traceback
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HOME = os.path.expanduser('~'); RES = HOME + '/navcore_ws/results'; OUT = RES + '/figures'
PY = os.environ.get('NAVCORE_PY', HOME + '/navcore_ws/.venv/bin/python')
ATE = HOME + '/navcore_ws/src/open_vins/scripts/t3_ate.py'
SEEDS = list(range(1, 31)); DIV = 10.0
TRAJ3 = ['udel_gore', 'udel_gore_zupt', 'tum_corridor1_512_16_okvis']
HELD = ['udel_gore_zupt', 'tum_corridor1_512_16_okvis', 'euroc_V1_01_easy']
TNAME = {'udel_gore': 'udel_gore', 'udel_gore_zupt': 'udel_gore_zupt', 'tum_corridor1_512_16_okvis': 'TUM corridor',
         'euroc_V1_01_easy': 'EuRoC V1_01'}
SB = (1.25, 1.5, 2.5)
C = {'stock': '#555555', 'tuned': '#E69F00', 'pooled': '#56B4E9', 'perfeat': '#009E73', 'gt': '#000000'}
LBL = {'stock': 'fixed R, σ0 = 1 px (stock)', 'tuned': 'fixed R, σ0 = 1.5 px (tuned)',
       'pooled': 'per-frame pooled, β = 1.5', 'perfeat': 'per-feature, β = 1.5'}
plt.rcParams.update({'font.size': 9, 'axes.titlesize': 9, 'axes.labelsize': 9, 'legend.fontsize': 8,
                     'xtick.labelsize': 8, 'ytick.labelsize': 8, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.alpha': 0.25, 'savefig.bbox': 'tight', 'pdf.fonttype': 42})
CAPS = []

def cond(sig, f, b, n=''): return 'sig%.3f_f%.3f_bad%.3f' % (sig, f, b) + ('_n' + n if n else '')
def rdir(root, traj, c, s): return os.path.normpath(f'{RES}/{root}/{traj}/{c}/seed{s}')

# ---------------------------------------------------------------- ATE with a persistent cache
CACHE_F = OUT + '/ate_cache.csv'; A = {}
def _load_cache():
    if os.path.isfile(CACHE_F):
        with open(CACHE_F) as fh:
            for r in csv.reader(fh):
                if len(r) == 3: A[r[0]] = (float(r[1]), float(r[2]))
def _parse(out, sink):
    for line in out.strip().splitlines():
        p = line.split('\t')
        try: sink[os.path.normpath(p[0])] = (float(p[1]), float(p[2]))
        except (ValueError, IndexError): pass
def ensure_ate(dirs):
    todo = [d for d in dict.fromkeys(dirs) if d not in A and os.path.isfile(d + '/state_estimate.txt')]
    new = {}
    for k in range(0, len(todo), 200):
        chunk = todo[k:k + 200]
        _parse(subprocess.run([PY, ATE] + chunk, capture_output=True, text=True).stdout, new)
        for d in chunk:
            if d not in new: _parse(subprocess.run([PY, ATE, d], capture_output=True, text=True).stdout, new)
            new.setdefault(d, (float('nan'), float('nan')))
        print(f'  ATE {min(k + 200, len(todo))}/{len(todo)}', flush=True)
    if new:
        A.update(new)
        with open(CACHE_F, 'a', newline='') as fh:
            w = csv.writer(fh)
            for d, (p, o) in new.items(): w.writerow([d, p, o])

def collect(root, traj, c, seeds=SEEDS):
    """-> ok {seed: (pos, ori)}, n_div (incl. failed ATE), n_present"""
    dirs = [rdir(root, traj, c, s) for s in seeds]
    ensure_ate(dirs)
    ok, div, n = {}, 0, 0
    for s, d in zip(seeds, dirs):
        if not os.path.isfile(d + '/state_estimate.txt'): continue
        n += 1; v = A.get(d, (float('nan'),) * 2)
        if not (v[0] < DIV): div += 1
        else: ok[s] = v
    return ok, div, n

# ---------------------------------------------------------------- statistics
def tci(x):
    x = np.asarray(x, float)
    return (np.mean(x), stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else (np.nan, np.nan)
def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; m = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0, m - h), min(1, m + h)
def paired(a, b, k):
    s = sorted(set(a) & set(b))
    if len(s) < 5: return None
    x = np.array([a[i][k] for i in s]); y = np.array([b[i][k] for i in s]); d = x - y
    p = stats.wilcoxon(x, y).pvalue if np.any(d != 0) else 1.0
    return 100 * d.mean() / y.mean(), p, len(s)

# ---------------------------------------------------------------- gate logs
def opentext(p):
    if os.path.isfile(p): return open(p, newline='')
    if os.path.isfile(p + '.gz'): return gzip.open(p + '.gz', 'rt', newline='')
    return None
def gate_rows(d, early=None):
    """MSCKF gate rows of one run: arrays t, sigma_true, sigma_used, dof, chi2, thr, acc. early = keep first fraction of time."""
    fh = opentext(d + '/gate_feat.csv')
    if fh is None: return None
    rows = []
    with fh:
        rd = csv.reader(fh); next(rd, None)
        for r in rd:
            try: rows.append((float(r[0]), float(r[3]), float(r[4]), int(r[5]), float(r[6]), float(r[7]), int(r[8])))
            except (ValueError, IndexError): pass
    if not rows: return None
    a = np.array(rows)
    if early:
        t0, t1 = a[:, 0].min(), a[:, 0].max(); a = a[a[:, 0] <= t0 + early * (t1 - t0)]
    return a

def save(fig, name, caption, numbers=''):
    for ext, kw in (('pdf', {}), ('png', {'dpi': 200})): fig.savefig(f'{OUT}/{name}.{ext}', **kw)
    plt.close(fig); CAPS.append((name, caption, numbers)); print(f'  wrote {name}.pdf/.png')
    with open(f'{OUT}/{name}.caption.md', 'w') as fh: fh.write(f'## {name}\n\n{caption}\n\nNumbers:\n\n```\n{numbers}\n```\n\n')

def uniform_conds(root, traj):
    out = {}
    for p in glob.glob(f'{RES}/{root}/{traj}/sig*_f0.000_*'):
        c = os.path.basename(p)
        if '_n' in c: continue
        out[float(c[3:8])] = c
    return dict(sorted(out.items()))

# ================================================================ figures
LOST = 0.5   # m; every run of every method outside the fixed-R breakdown cells is below this (checked 14 Oct)
def _fail_counts(root, tr, c):
    dirs = [rdir(root, tr, c, s) for s in SEEDS]; ensure_ate(dirs)
    v = [A.get(d, (float('nan'),))[0] for d in dirs if os.path.isfile(d + '/state_estimate.txt')]
    return sum(1 for x in v if not x < LOST), sum(1 for x in v if not x < DIV), len(v)
def fig1(args):
    meth = [('stock', 't3a', 1.0), ('tuned', 't4tf_uniform', 1.5), ('perfeat', 't4a_uniform', None)]
    res = {}
    for m, root, s0 in meth:
        agg = {}
        for tr in TRAJ3:
            for sig, c in uniform_conds(root, tr).items():
                lost, div, n = _fail_counts(root, tr, c); a = agg.setdefault(sig, [0, 0, 0])
                a[0] += lost; a[1] += div; a[2] += n
        res[m] = (s0, agg)
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.8)); fig.subplots_adjust(wspace=0.32)
    nums = []
    for m, (s0, agg) in res.items():
        if not agg: continue
        sig = np.array(list(agg)); lab = LBL[m] if m != 'perfeat' else 'per-feature (true σ), β = 1'
        for col, ls in ((0, '-'), (1, '--')):
            w = np.array([wilson(agg[s][col], agg[s][2]) for s in sig])
            err = [100 * np.clip(w[:, 0] - w[:, 1], 0, None), 100 * np.clip(w[:, 2] - w[:, 0], 0, None)]
            ax[0].errorbar(sig, 100 * w[:, 0], yerr=err, marker='o' if col == 0 else None, ms=4, capsize=2, color=C[m],
                           ls=ls, lw=1.4 if col == 0 else 0.9, label=lab if col == 0 else None)
            if col == 0 and s0: ax[1].errorbar(sig / s0, 100 * w[:, 0], yerr=err, marker='o', ms=4, capsize=2, color=C[m], label=lab)
        nums.append(f'{lab}: ' + ', '.join(f'σ {s:g}: lost {agg[s][0]}/{agg[s][2]} (diverged {agg[s][1]})' for s in sig))
    ax[0].plot([], [], color='0.4', ls='-', lw=1.4, label=f'lost track (ATE > {LOST:g} m)')
    ax[0].plot([], [], color='0.4', ls='--', lw=0.9, label=f'diverged (ATE > {DIV:g} m)')
    ax[0].set_xlabel('true pixel noise σ (px)'); ax[0].set_ylabel('runs (%)'); ax[0].set_ylim(-3, 103)
    h, l = ax[0].get_legend_handles_labels()
    fig.legend(h, l, loc='upper center', bbox_to_anchor=(0.5, -0.06), ncol=3, frameon=False, fontsize=7)
    ax[0].set_title('(a) failures vs noise')
    ax[1].set_xlabel('noise ratio σ / σ0 (true / assumed)'); ax[1].set_ylabel('runs lost track (%)'); ax[1].set_ylim(-3, 103)
    ax[1].set_title('(b) fixed R fails at the same ratio'); ax[1].axvspan(1.33, 1.75, color='0.85', alpha=0.6, lw=0)
    save(fig, 'fig1_divergence_cliff',
         f'Failures over 3 trajectories × 30 seeds per point, Wilson 95% intervals. Solid: lost track (position ATE > {LOST:g} m; '
         'a working filter is below 0.3 m on these paths, and no run of any method outside the fixed-R breakdown cells lies '
         f'between {LOST:g} and {DIV:g} m). Dashed: diverged (ATE > {DIV:g} m). (a) Fixed R breaks down sharply; tuning σ0 from 1 '
         'to 1.5 px only moves the breakdown. The per-feature filter given the true σ never fails. (b) Against the ratio of '
         'true to assumed noise, both fixed filters fail between about 1.3× and 1.75×.', '\n'.join(nums))

def fig2(args):
    srcs = [('stock', 't4val_fixed', HELD, [cond(1.0, 0.5, b) for b in SB]),
            ('tuned', 't4tf_val', HELD, [cond(1.0, 0.5, b) for b in SB]),
            ('tuned', 't4tf_uniform', TRAJ3, None), ('perfeat', 't4a_uniform', TRAJ3, None)]
    emp = {}; dt = []
    for m, root, trajs, conds in srcs:
        for tr in trajs:
            cl = conds if conds else list(uniform_conds(root, tr).values())
            for c in cl:
                for s in SEEDS[:args.gate_seeds]:
                    a = gate_rows(rdir(root, tr, c, s), early=0.25)
                    if a is None: continue
                    r = np.round(a[:, 1] / a[:, 2], 3)
                    for rv in np.unique(r):
                        sel = a[r == rv]; e = emp.setdefault((m, rv), [0, 0, 0.0])
                        e[0] += sel[:, 6].sum(); e[1] += len(sel)
                        e[2] += stats.chi2.cdf(sel[:, 5] / rv ** 2, sel[:, 3]).sum()
                    if len(dt) < 200000: dt.extend(zip(a[:, 3], a[:, 5]))
    if not emp: print('  fig2: no gate logs found, skipped'); return
    dt = np.array(dt); rg = np.linspace(0.5, 2.6, 120)
    theo = [stats.chi2.cdf(dt[:, 1] / r ** 2, dt[:, 0]).mean() for r in rg]
    fig, ax = plt.subplots(figsize=(3.6, 2.7))
    ax.plot(rg, 100 * np.array(theo), color='0.3', lw=1.2, label='predicted (χ² with logged dof)')
    nums = []
    for m in ('stock', 'tuned', 'perfeat'):
        pts = sorted((rv, v) for (mm, rv), v in emp.items() if mm == m and v[1] > 200)
        if not pts: continue
        ax.plot([p[0] for p in pts], [100 * p[1][0] / p[1][1] for p in pts], {'stock': 's', 'tuned': 'o', 'perfeat': 'D'}[m], ms=4.5, color=C[m],
                label={'stock': 'measured, fixed σ0 = 1', 'tuned': 'measured, fixed σ0 = 1.5', 'perfeat': 'measured, per-feature'}[m])
        ax.plot([p[0] for p in pts], [100 * p[1][2] / p[1][1] for p in pts], 'x', ms=5, mew=0.9, color='k', zorder=5,
                label='predicted for that point' if m == 'stock' else None)
        nums += [f'{m} r={rv:.3f}: accepted {100 * v[0] / v[1]:.1f}% (predicted {100 * v[2] / v[1]:.1f}%, {v[1]} rows)' for rv, v in pts]
    ax.set_xlabel('noise ratio r = σ_true / σ_used'); ax.set_ylabel('gate acceptance (%)'); ax.set_ylim(-3, 103)
    ax.legend(frameon=False, loc='upper left', bbox_to_anchor=(1.02, 1.0), fontsize=7)
    save(fig, 'fig2_gate_theory',
         'Chi-square gate acceptance of MSCKF features against the ratio of true to assumed noise. Points: measured in the first '
         f'quarter of each run (seeds 1–{args.gate_seeds}, before any divergence), grouped by the exact ratio; line: probability '
         'predicted from a scaled χ² with the logged degrees of freedom and thresholds (ignores HPH^T); crosses: prediction for each measured point from its own rows, line: prediction for the pooled rows. Acceptance falls '
         'from 95% at r = 1 to almost zero by r ≈ 1.75, which is the mechanism behind the divergence in Fig. 1.', '\n'.join(nums))

def fig3(args):
    meth = [('stock', 't4val_fixed'), ('tuned', 't4tf_val'), ('pooled', 't4val_pooled_b1.50'), ('perfeat', 't4val_perfeat_b1.50')]
    acc = {}
    for m, root in meth:
        for b in SB:
            e = acc.setdefault((m, b), [0, 0, 0, 0])
            for tr in HELD:
                for s in SEEDS[:args.gate_seeds]:
                    a = gate_rows(rdir(root, tr, cond(1.0, 0.5, b), s))
                    if a is None: continue
                    cl = a[:, 1] < 1.01
                    e[0] += a[cl, 6].sum(); e[1] += cl.sum(); e[2] += a[~cl, 6].sum(); e[3] += (~cl).sum()
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    nums = []
    for m, _ in meth:
        y = [[100 * acc[(m, b)][0] / max(acc[(m, b)][1], 1), 100 * acc[(m, b)][2] / max(acc[(m, b)][3], 1)] for b in SB]
        if not any(acc[(m, b)][1] for b in SB): continue
        for j in (0, 1): ax[j].plot(SB, [v[j] for v in y], 'o--' if m == 'pooled' else 'o-', color=C[m], ms=4, label=LBL[m],
                                    zorder=4 if m == 'pooled' else 3)
        nums.append(f'{m}: ' + '; '.join(f'σ_bad {b}: clean {v[0]:.1f}%, noisy {v[1]:.1f}%' for b, v in zip(SB, y)))
    ax[0].set_title('(a) clean features (σ = 1 px)'); ax[1].set_title('(b) noisy features (σ = σ_bad)')
    for a_ in ax: a_.set_xlabel('σ_bad (px)'); a_.set_xticks(SB); a_.set_xticklabels([f'{b:g}' for b in SB])
    ax[0].set_ylabel('gate acceptance (%)'); ax[0].set_ylim(-3, 103); ax[0].legend(frameon=False, loc='lower left')
    save(fig, 'fig3_gate_mechanism',
         f'Gate acceptance on the held-out cells (half the features noisy, 250 points, 3 trajectories, seeds 1–{args.gate_seeds}). '
         'A fixed R can only accept a noisy feature at the clean features\' weight or reject it. Stock fixed R (σ0 = 1 px) '
         'rejects most noisy features already at σ_bad 1.25, losing their information; tuned fixed R (σ0 = 1.5 px) accepts '
         'nearly all of them at σ_bad 1.25–1.5 and over-weights them, then rejects them at 2.5. Per-frame pooling and '
         'per-feature R accept nearly everything and weight it instead (pooled dashed, it overlaps per-feature at 100%).', '\n'.join(nums))

def _regime_columns():
    cols = []
    for n, nl in (('', '250'), ('60', '60')):
        for f in (0.25, 0.5):
            for b in SB: cols.append((f'grid, {nl} pts\nf = {f:g}', b, 'udel_gore', cond(1.0, f, b, n), 'grid'))
    for tr in HELD:
        for b in SB: cols.append(({'udel_gore_zupt': 'zupt\n(same path)', 'tum_corridor1_512_16_okvis': 'TUM\ncorridor',
                                    'euroc_V1_01_easy': 'EuRoC\nV1_01'}[tr], b, tr, cond(1.0, 0.5, b), 'held'))
    return cols
def fig4(args):
    roots = {'grid': {'perfeat': 't4cal_perfeat_b1.50', 'pooled': 't4cal_pooled_b1.50', 'tuned': 't4tf_t3bgrid', 'stock': 't3b'},
             'held': {'perfeat': 't4val_perfeat_b1.50', 'pooled': 't4val_pooled_b1.50', 'tuned': 't4tf_val', 'stock': 't4val_fixed'}}
    cols = _regime_columns(); rows = ['pooled', 'tuned', 'stock']
    for k, kn in ((0, 'pos'), (1, 'ori')):
        M = np.full((3, len(cols)), np.nan); P = np.full((3, len(cols)), np.nan)
        for j, (grp, b, tr, c, kind) in enumerate(cols):
            pf = collect(roots[kind]['perfeat'], tr, c)[0]
            for i, m in enumerate(rows):
                r = paired(pf, collect(roots[kind][m], tr, c)[0], k)
                if r: M[i, j], P[i, j] = r[0], r[1]
        fig, ax = plt.subplots(figsize=(7.2, 2.5))
        lim = max(10, np.nanmax(np.abs(M))) if np.isfinite(M).any() else 40
        im = ax.imshow(M, cmap='RdBu_r', vmin=-lim, vmax=lim, aspect='auto')
        for i in range(3):
            for j in range(len(cols)):
                if np.isfinite(M[i, j]):
                    sig = P[i, j] < 0.05
                    ax.text(j, i, f'{int(round(M[i, j]))}' + ('*' if sig else ''), ha='center', va='center', fontsize=6.5,
                            fontweight='bold' if sig else 'normal', color='white' if abs(M[i, j]) > 0.6 * lim else 'black')
        ax.set_yticks(range(3)); ax.set_yticklabels(['vs per-frame pooled', 'vs tuned fixed R', 'vs stock fixed R'])
        ax.set_xticks(range(len(cols))); ax.set_xticklabels([f'{b:g}' for _, b, *_ in cols]); ax.grid(False)
        ax.set_xlabel('σ_bad (px)')
        groups = []
        for j, (g, *_ ) in enumerate(cols):
            if not groups or groups[-1][0] != g: groups.append([g, j, j])
            else: groups[-1][2] = j
        for g, j0, j1 in groups:
            ax.text((j0 + j1) / 2, -0.6, g, ha='center', va='bottom', fontsize=6.5, linespacing=1.0)
            if j0 > 0: ax.axvline(j0 - 0.5, color='white', lw=2)
        cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01); cb.set_label('Δ ATE (%)', fontsize=7); cb.ax.tick_params(labelsize=7)
        nsig_b = int(np.nansum((M < 0) & (P < 0.05))); nsig_w = int(np.nansum((M > 0) & (P < 0.05))); ntot = int(np.isfinite(M).sum())
        save(fig, f'fig4_regime_map_{kn}',
             f'Paired relative difference in {"position" if k == 0 else "orientation"} ATE, per-feature minus baseline, as % of the '
             'baseline (blue = per-feature better), 30 seeds per cell; * and bold = Wilcoxon p < 0.05. Grid cells: udel_gore; '
             'held-out cells: f = 0.5, 250 points. Pooled and per-feature at β = 1.5; tuned fixed at σ0 = 1.5 px; stock at 1 px.',
             f'{ntot} comparisons: per-feature significantly better in {nsig_b}, significantly worse in {nsig_w}.')

def _bars(ax, groups, data, keys, ylabel):
    w = 0.8 / len(keys)
    for i, m in enumerate(keys):
        mu = [tci([v[0] for v in data[g][m].values()])[0] if data[g][m] else np.nan for g in groups]
        ci = [tci([v[0] for v in data[g][m].values()])[1] if len(data[g][m]) > 1 else 0 for g in groups]
        ax.bar(np.arange(len(groups)) + (i - (len(keys) - 1) / 2) * w, mu, w, yerr=ci, color=C[m], capsize=1.5,
               error_kw={'lw': 0.7}, label=LBL[m])
    ax.set_xticks(range(len(groups))); ax.set_xticklabels([f'{g:g}' for g in groups]); ax.set_xlabel('σ_bad (px)')
    ax.set_ylabel(ylabel); ax.grid(axis='x', visible=False)
def fig5(args):
    roots = {'stock': 't4val_fixed', 'tuned': 't4tf_val', 'pooled': 't4val_pooled_b1.50', 'perfeat': 't4val_perfeat_b1.50'}
    keys = list(roots)
    fig, ax = plt.subplots(1, 3, figsize=(7.2, 2.5)); nums = []
    for j, tr in enumerate(HELD):
        data = {b: {m: collect(roots[m], tr, cond(1.0, 0.5, b))[0] for m in keys} for b in SB}
        _bars(ax[j], SB, data, keys, 'position ATE (m)' if j == 0 else ''); ax[j].set_title(TNAME[tr])
        nums += [f'{TNAME[tr]} σ_bad {b}: ' + ', '.join(f'{m} {tci([v[0] for v in data[b][m].values()])[0]:.4f}' for m in keys) for b in SB]
    ax[0].legend(frameon=False, fontsize=7, loc='upper left')
    save(fig, 'fig5_heldout_bars_pos',
         'Position ATE (mean and 95% t-interval over 30 seeds) on the held-out paths, half the features noisy, 250 points. '
         'udel_gore_zupt is the calibration path with stationary pauses; TUM corridor and EuRoC V1_01 are new paths.', '\n'.join(nums))
def fig6(args):
    roots = {'stock': 't3b', 'tuned': 't4tf_t3bgrid', 'pooled': 't4cal_pooled_b1.50', 'perfeat': 't4cal_perfeat_b1.50'}
    keys = list(roots)
    fig, ax = plt.subplots(1, 4, figsize=(7.2, 2.5)); nums = []
    for j, (n, f) in enumerate([('', 0.25), ('', 0.5), ('60', 0.25), ('60', 0.5)]):
        data = {b: {m: collect(roots[m], 'udel_gore', cond(1.0, f, b, n))[0] for m in keys} for b in SB}
        _bars(ax[j], SB, data, keys, 'position ATE (m)' if j == 0 else ''); ax[j].set_title(f'{n or 250} pts, f = {f:g}')
        nums += [f'{n or 250} pts f {f} σ_bad {b}: ' + ', '.join(f'{m} {tci([v[0] for v in data[b][m].values()])[0]:.4f}' for m in keys) for b in SB]
    ax[0].legend(frameon=False, fontsize=6.5, loc='upper left')
    save(fig, 'fig6_grid_bars_pos',
         'Position ATE (mean and 95% t-interval over 30 seeds) on the T.3b grid (udel_gore), fraction f of features noisy at '
         'σ_bad, clean features at 1 px.', '\n'.join(nums))

def fig7(args):
    curves = {1.0: [(1.0, 't3b'), (1.25, 't4c_uniform_beta1.25'), (1.5, 't4c_uniform_beta1.50'), (2.0, 't4c_uniform_beta2.00')],
              2.0: [(1.0, 't4a_uniform'), (1.15, 't4c_uniform_sig2_beta1.15'), (1.3, 't4c_uniform_sig2_beta1.30'),
                    (1.5, 't4c_uniform_sig2_beta1.50'), (1.75, 't4c_uniform_sig2_beta1.75'), (2.0, 't4c_uniform_sig2_beta2.00')]}
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.6)); nums = []
    for sig, rows in curves.items():
        data = {}
        for be, root in rows:
            c = uniform_conds(root, 'udel_gore').get(sig)
            if c: data[be] = collect(root, 'udel_gore', c)[0]
        if 1.5 not in data: continue
        for k in (0, 1):
            xs, mu, ci = [], [], []
            for be in sorted(data):
                s = sorted(set(data[be]) & set(data[1.5]))
                if len(s) < 5: continue
                m_, c_ = tci([data[be][i][k] / data[1.5][i][k] for i in s]); xs.append(be); mu.append(m_); ci.append(c_)
            ax[k].errorbar(xs, mu, yerr=ci, marker='o', ms=4, capsize=2, label=f'true σ = {sig:g} px',
                           color='#0072B2' if sig == 1.0 else '#CC79A7')
            nums.append(f'σ {sig:g} {"pos" if k == 0 else "ori"}: ' + ', '.join(f'β {x:g}: {m:.3f}±{c:.3f}' for x, m, c in zip(xs, mu, ci)))
    for k, t in ((0, '(a) position'), (1, '(b) orientation')):
        ax[k].axhline(1, color='0.5', lw=0.8, ls='--'); ax[k].set_xlabel('noise inflation factor β'); ax[k].set_title(t)
    ax[0].set_ylabel('ATE / ATE at β = 1.5'); ax[0].legend(frameon=False)
    save(fig, 'fig7_beta_curves',
         'Effect of inflating every σ by β, uniform noise, udel_gore, 250 points: per-seed ATE ratio to β = 1.5 (mean and 95% '
         't-interval, 30 paired seeds). Some inflation clearly helps at both noise levels; position is flat between about 1.15 '
         'and 2.0 at σ = 2 px, orientation keeps improving up to 2.0.', '\n'.join(nums))

def fig8(args):
    meth = [('stock', 't3a'), ('tuned', 't4tf_uniform'), ('perfeat', 't4a_uniform')]
    fig, ax = plt.subplots(1, 3, figsize=(7.2, 2.5), sharey=True); nums = []
    for j, tr in enumerate(TRAJ3):
        for m, root in meth:
            xs, med, lo, hi = [], [], [], []
            for sig, c in uniform_conds(root, tr).items():
                ok, div, n = collect(root, tr, c)
                if len(ok) < 10: continue
                v = np.array([x[0] for x in ok.values()]); xs.append(sig); med.append(np.median(v))
                lo.append(np.percentile(v, 25)); hi.append(np.percentile(v, 75))
            if xs:
                ax[j].plot(xs, med, 'o-', ms=3.5, color=C[m], label=LBL[m] if m != 'perfeat' else 'per-feature (true σ), β = 1')
                ax[j].fill_between(xs, lo, hi, color=C[m], alpha=0.18, lw=0)
                nums.append(f'{TNAME[tr]} {m}: ' + ', '.join(f'σ {x:g}: {y:.3f}' for x, y in zip(xs, med)))
        ax[j].set_title(TNAME[tr]); ax[j].set_xlabel('true pixel noise σ (px)'); ax[j].set_yscale('log')
    ax[0].set_ylabel('position ATE (m), runs not diverged'); ax[0].legend(frameon=False, fontsize=6.5)
    save(fig, 'fig8_uniform_accuracy',
         'Accuracy under uniform noise: median and interquartile range of position ATE over the runs that did not diverge '
         '(points shown only where at least 10 of 30 survived). The per-feature filter degrades smoothly with σ; the fixed '
         'filters stop at their breakdown.', '\n'.join(nums))

def _xy(path):
    try: a = np.loadtxt(path, comments='#')
    except Exception: return None
    if a.ndim != 2 or a.shape[1] < 8: return None
    a = a[np.all(np.isfinite(a[:, 5:8]), axis=1)]
    return a[:, 5:8]
def fig9(args):
    tr = 'udel_gore'; sig = 2.5
    cs = {m: uniform_conds(root, tr).get(sig) for m, root in (('stock', 't3a'), ('tuned', 't4tf_uniform'), ('perfeat', 't4a_uniform'))}
    if not all(cs.values()): print('  fig9: σ 2.5 folders missing, skipped'); return
    roots = {'stock': 't3a', 'tuned': 't4tf_uniform', 'perfeat': 't4a_uniform'}
    oks = {m: collect(roots[m], tr, cs[m]) [0] for m in roots}
    seed = next((s for s in SEEDS if s in oks['perfeat'] and s not in oks['tuned'] and s not in oks['stock']), None)
    if seed is None: print('  fig9: no seed where only per-feature survives, skipped'); return
    gt = _xy(rdir('t4a_uniform', tr, cs['perfeat'], seed) + '/state_groundtruth.txt')
    if gt is None: print('  fig9: cannot read ground truth, skipped'); return
    L = np.linalg.norm(np.diff(gt, axis=0), axis=1).sum()
    if not 0.9 * 227.8 < L < 1.1 * 227.8:
        print(f'  fig9: ground-truth path length {L:.1f} m is not ~227.8 m; column layout differs, skipped'); return
    fig, ax = plt.subplots(figsize=(3.6, 3.2))
    for m in ('stock', 'tuned', 'perfeat'):
        e = _xy(rdir(roots[m], tr, cs[m], seed) + '/state_estimate.txt')
        if e is not None:
            ax.plot(e[:, 0], e[:, 1], color=C[m], lw=1.0, label=(LBL[m] if m != 'perfeat' else 'per-feature (true σ), β = 1'))
    ax.plot(gt[:, 0], gt[:, 1], color=C['gt'], lw=0.9, ls='--', label='ground truth')
    pad = 0.15 * max(np.ptp(gt[:, 0]), np.ptp(gt[:, 1]))
    ax.set_xlim(gt[:, 0].min() - pad, gt[:, 0].max() + pad); ax.set_ylim(gt[:, 1].min() - pad, gt[:, 1].max() + pad)
    ax.set_aspect('equal'); ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)')
    ax.legend(frameon=False, fontsize=6.5, loc='upper center', bbox_to_anchor=(0.5, -0.18), ncol=2)
    save(fig, 'fig9_trajectory_example',
         f'Top view of one run (udel_gore, uniform σ = 2.5 px, seed {seed}): both fixed-R filters lose track and leave the '
         'frame, the per-feature filter given the true σ follows the ground truth.', f'seed {seed}, ground-truth length {L:.1f} m')

FIGS = {'fig1': fig1, 'fig2': fig2, 'fig3': fig3, 'fig4': fig4, 'fig5': fig5, 'fig6': fig6, 'fig7': fig7, 'fig8': fig8, 'fig9': fig9}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--only', default=''); ap.add_argument('--gate-seeds', type=int, default=10)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True); _load_cache()
    want = [f.strip() for f in args.only.split(',') if f.strip()] or list(FIGS)
    done, failed = [], []
    for name in want:
        print(f'{name} ...', flush=True)
        try: FIGS[name](args); done.append(name)
        except Exception: failed.append(name); traceback.print_exc()
    with open(OUT + '/captions.md', 'w') as fh:   # all figures made so far, including earlier --only runs
        for f in sorted(glob.glob(OUT + '/*.caption.md')): fh.write(open(f).read())
    print(f'\ndone: {", ".join(done) or "-"} | failed: {", ".join(failed) or "-"} | output: {OUT}')

if __name__ == '__main__':
    main()
