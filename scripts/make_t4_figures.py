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
TNAME = {'udel_gore': 'outdoor path', 'udel_gore_zupt': 'outdoor path with stops', 'tum_corridor1_512_16_okvis': 'indoor corridor',
         'euroc_V1_01_easy': 'EuRoC room'}
SB = (1.25, 1.5, 2.5)
# Paper-style look, matched to the Beamer slides (Computer Modern Sans body text, typeset maths).
C = {'stock': '#474747', 'tuned': '#FF9500', 'pooled': '#0C5DA5', 'perfeat': '#FF2C00', 'gt': '#000000'}
MK = {'stock': 's', 'tuned': '^', 'pooled': 'D', 'perfeat': 'o'}
LBL = {'stock': 'stock fixed', 'tuned': 'tuned fixed', 'pooled': 'per-image', 'perfeat': 'per-feature'}
LBL_TRUE = r'per-feature (true $\sigma$)'
plt.rcParams.update({
    'font.family': 'sans-serif', 'font.sans-serif': ['cmss10', 'DejaVu Sans'],
    'mathtext.fontset': 'custom', 'mathtext.rm': 'cmss10', 'mathtext.sf': 'cmss10', 'mathtext.it': 'cmmi10',
    'mathtext.bf': 'cmb10', 'mathtext.fallback': 'cm', 'axes.unicode_minus': False, 'axes.formatter.use_mathtext': False,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10, 'legend.fontsize': 9,
    'xtick.labelsize': 9, 'ytick.labelsize': 9,
    'axes.linewidth': 0.8, 'axes.spines.top': True, 'axes.spines.right': True, 'axes.grid': False,
    'xtick.direction': 'in', 'ytick.direction': 'in', 'xtick.top': True, 'ytick.right': True,
    'xtick.minor.visible': True, 'ytick.minor.visible': True,
    'xtick.major.size': 3.5, 'ytick.major.size': 3.5, 'xtick.minor.size': 2, 'ytick.minor.size': 2,
    'lines.linewidth': 1.2, 'lines.markersize': 4.5, 'errorbar.capsize': 2,
    'legend.frameon': False, 'legend.handlelength': 1.8,
    'savefig.bbox': 'tight', 'savefig.pad_inches': 0.03, 'pdf.fonttype': 42})
def plabel(ax, text):   # panel label above the axes, left-aligned
    ax.set_title(text, loc='left', pad=4)
def no_minor_x(ax): ax.tick_params(axis='x', which='minor', bottom=False, top=False)
def _fbox(fig, axes):
    r = fig.canvas.get_renderer(); inv = fig.transFigure.inverted()
    b = [a.get_tightbbox(r).transformed(inv) for a in axes]
    return min(x.x0 for x in b), max(x.x1 for x in b), min(x.y0 for x in b), max(x.y1 for x in b)
def top_legend(fig, axes, handles, labels, ncol):
    x0, x1, y0, y1 = _fbox(fig, axes)
    fig.legend(handles, labels, loc='lower center', bbox_to_anchor=((x0 + x1) / 2, y1 + 0.005), ncol=ncol)
def shared_xlabel(fig, axes, text):
    x0 = min(a.get_position().x0 for a in axes); x1 = max(a.get_position().x1 for a in axes)
    _, _, y0, _ = _fbox(fig, axes)
    fig.text((x0 + x1) / 2, y0 - 0.01, text, ha='center', va='top', fontsize=plt.rcParams['axes.labelsize'])
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
    for ext, kw in (('pdf', {}), ('png', {'dpi': 300})): fig.savefig(f'{OUT}/{name}.{ext}', **kw)
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
    fig, ax = plt.subplots(1, 2, figsize=(6.0, 2.6))
    nums = []
    for m, (s0, agg) in res.items():
        if not agg: continue
        sig = np.array(list(agg)); lab = LBL[m] if m != 'perfeat' else LBL_TRUE
        w = np.array([wilson(agg[s][0], agg[s][2]) for s in sig])
        err = [100 * np.clip(w[:, 0] - w[:, 1], 0, None), 100 * np.clip(w[:, 2] - w[:, 0], 0, None)]
        kw = dict(marker=MK[m], mfc='white', mew=1.0, elinewidth=0.8, color=C[m], label=lab)
        ax[0].errorbar(sig, 100 * w[:, 0], yerr=err, **kw)
        if s0: ax[1].errorbar(sig / s0, 100 * w[:, 0], yerr=err, **kw)
        nums.append(f'{lab}: ' + ', '.join(f'σ {s:g}: lost {agg[s][0]}/{agg[s][2]} (diverged {agg[s][1]})' for s in sig))
    ax[0].set_xlabel(r'true pixel noise $\sigma$ (px)'); ax[0].set_ylabel('runs lost (%)')
    ax[1].set_xlabel(r'true $\sigma$ / assumed $\sigma_0$')
    ax[1].axvspan(1.33, 1.75, color='0.9', lw=0, zorder=0)
    for a_ in ax: a_.set_ylim(-4, 104)
    plabel(ax[0], '(a)'); plabel(ax[1], '(b)')
    fig.tight_layout(w_pad=2.0)
    h, l = ax[0].get_legend_handles_labels(); top_legend(fig, ax, h, l, 3)
    save(fig, 'fig1_divergence_cliff',
         f'Runs that lost track (position error > {LOST:g} m) over 3 trajectories × 30 seeds per point, Wilson 95% intervals. '
         'A working filter is below 0.3 m on these paths, and no run of any method outside the fixed-R breakdown cells lies '
         f'between {LOST:g} and {DIV:g} m; the numbers below also give the runs that diverged (> {DIV:g} m). (a) Fixed R breaks '
         'down sharply; tuning σ0 from 1 to 1.5 px only moves the breakdown. The per-feature filter given the true σ (β = 1) '
         'never fails. (b) Against the ratio of true to assumed noise, both fixed filters fail between about 1.3× and 1.75× (shaded).',
         '\n'.join(nums))

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
    fig, ax = plt.subplots(figsize=(4.2, 2.8))
    ax.plot(rg, 100 * np.array(theo), color='0.2', lw=1.2, label='prediction, all features', zorder=2)
    nums = []
    for m in ('stock', 'tuned', 'perfeat'):
        pts = sorted((rv, v) for (mm, rv), v in emp.items() if mm == m and v[1] > 200)
        if not pts: continue
        ax.plot([p[0] for p in pts], [100 * p[1][0] / p[1][1] for p in pts], MK[m], ls='none', mfc='white', mew=1.1, ms=5.5,
                color=C[m], label={'stock': 'stock fixed', 'tuned': 'tuned fixed', 'perfeat': LBL_TRUE}[m], zorder=3)
        ax.plot([p[0] for p in pts], [100 * p[1][2] / p[1][1] for p in pts], 'x', ms=4, mew=0.9, color='k', zorder=4,
                label='prediction for those features' if m == 'stock' else None)
        nums += [f'{m} r={rv:.3f}: accepted {100 * v[0] / v[1]:.1f}% (predicted {100 * v[2] / v[1]:.1f}%, {v[1]} rows)' for rv, v in pts]
    ax.set_xlabel(r'true $\sigma$ / $\sigma$ used by the filter'); ax.set_ylabel('features passing the check (%)')
    ax.set_ylim(-4, 104); ax.legend(loc='upper right')
    save(fig, 'fig2_gate_theory',
         'Chi-square gate acceptance of MSCKF features against the ratio of true to assumed noise. Markers: measured in the first '
         f'quarter of each run (seeds 1–{args.gate_seeds}, before any divergence), grouped by the exact ratio; line: probability '
         'predicted from a scaled χ² with the logged degrees of freedom and thresholds (ignores HPH^T). Crosses: the same '
         'prediction for the features of each point. Acceptance falls from 95% at r = 1 to almost zero by r ≈ 1.75, which is the mechanism behind Fig. 1.',
         '\n'.join(nums))

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
    fig, ax = plt.subplots(1, 2, figsize=(6.0, 2.6), sharey=True)
    nums = []
    for m, _ in meth:
        y = [[100 * acc[(m, b)][0] / max(acc[(m, b)][1], 1), 100 * acc[(m, b)][2] / max(acc[(m, b)][3], 1)] for b in SB]
        if not any(acc[(m, b)][1] for b in SB): continue
        for j in (0, 1):
            ax[j].plot(SB, [v[j] for v in y], marker=MK[m], mfc='white', mew=1.0, color=C[m], label=LBL[m],
                       ls='--' if m == 'pooled' else '-', ms=7 if m == 'pooled' else 4.5, zorder=4 if m == 'perfeat' else 3)
        nums.append(f'{m}: ' + '; '.join(f'σ_bad {b}: clean {v[0]:.1f}%, noisy {v[1]:.1f}%' for b, v in zip(SB, y)))
    plabel(ax[0], '(a) clean features'); plabel(ax[1], '(b) noisy features')
    for a_ in ax:
        a_.set_xlabel('noise of the noisy features (px)'); a_.set_xticks(SB); a_.set_xticklabels([f'{b:g}' for b in SB])
        a_.set_xlim(1.1, 2.65); no_minor_x(a_)
    ax[0].set_ylabel('features passing the check (%)'); ax[0].set_ylim(-4, 104)
    ax[0].legend(loc='lower left')
    fig.tight_layout(w_pad=1.5)
    save(fig, 'fig3_gate_mechanism',
         f'Gate acceptance on the held-out cells (half the features noisy, 250 points, 3 trajectories, seeds 1–{args.gate_seeds}). '
         'A fixed R can only accept a noisy feature at the clean features\' weight or reject it. Stock fixed R (σ0 = 1 px) '
         'rejects most noisy features already at σ_bad 1.25, losing their information; tuned fixed R (σ0 = 1.5 px) accepts '
         'nearly all of them at σ_bad 1.25–1.5 and over-weights them, then rejects them at 2.5. Per-image and per-feature '
         '(both β = 1.5) accept nearly everything and weight it instead (per-image dashed; it overlaps per-feature at 100%).',
         '\n'.join(nums))

def _regime_columns():
    cols = []
    for n, nl in (('', '250'), ('60', '60')):
        for f in (0.25, 0.5):
            for b in SB: cols.append((f'{nl} features\n{f*100:g}% noisy', b, 'udel_gore', cond(1.0, f, b, n), 'grid'))
    for tr in HELD:
        for b in SB: cols.append(({'udel_gore_zupt': 'outdoor\nwith stops', 'tum_corridor1_512_16_okvis': 'indoor\ncorridor',
                                    'euroc_V1_01_easy': 'EuRoC\nroom'}[tr], b, tr, cond(1.0, 0.5, b), 'held'))
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
        fig, ax = plt.subplots(figsize=(7.2, 2.4))
        lim = max(10, np.nanmax(np.abs(M))) if np.isfinite(M).any() else 40
        im = ax.imshow(M, cmap='RdBu_r', vmin=-lim, vmax=lim, aspect='auto')
        for i in range(3):
            for j in range(len(cols)):
                if np.isfinite(M[i, j]):
                    sig = P[i, j] < 0.05
                    ax.text(j, i, f'{int(round(M[i, j]))}' + ('*' if sig else ''), ha='center', va='center', fontsize=7.5,
                            fontweight='bold' if sig else 'normal', color='white' if abs(M[i, j]) > 0.6 * lim else 'black')
        ax.tick_params(which='both', top=False, right=False, length=0); ax.minorticks_off()
        ax.set_yticks(range(3)); ax.set_yticklabels(['vs per-image', 'vs tuned fixed', 'vs stock fixed'])
        ax.set_xticks(range(len(cols))); ax.set_xticklabels([f'{b:g}' for _, b, *_ in cols], fontsize=8)
        ax.set_xlabel('noise of the noisy features (px)')
        groups = []
        for j, (g, *_ ) in enumerate(cols):
            if not groups or groups[-1][0] != g: groups.append([g, j, j])
            else: groups[-1][2] = j
        for g, j0, j1 in groups:
            ax.text((j0 + j1) / 2, -0.62, g, ha='center', va='bottom', fontsize=8, linespacing=1.05)
            if j0 > 0: ax.axvline(j0 - 0.5, color='white', lw=2.5)
        cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01); cb.set_label(r'$\Delta$ error (%)')
        cb.ax.minorticks_off(); cb.ax.tick_params(direction='out', right=True, left=False)
        nsig_b = int(np.nansum((M < 0) & (P < 0.05))); nsig_w = int(np.nansum((M > 0) & (P < 0.05))); ntot = int(np.isfinite(M).sum())
        save(fig, f'fig4_regime_map_{kn}',
             f'Paired relative difference in {"position" if k == 0 else "orientation"} ATE, per-feature minus baseline, as % of the '
             'baseline (blue = per-feature better), 30 seeds per cell; * and bold = Wilcoxon p < 0.05. Grid cells: udel_gore; '
             'held-out cells: f = 0.5, 250 points. Per-image and per-feature at β = 1.5; tuned fixed at σ0 = 1.5 px; stock at 1 px.',
             f'{ntot} comparisons: per-feature significantly better in {nsig_b}, significantly worse in {nsig_w}.')

def _bars(ax, groups, data, keys, ylabel):
    w = 0.8 / len(keys)
    for i, m in enumerate(keys):
        mu = [tci([v[0] for v in data[g][m].values()])[0] if data[g][m] else np.nan for g in groups]
        ci = [tci([v[0] for v in data[g][m].values()])[1] if len(data[g][m]) > 1 else 0 for g in groups]
        ax.bar(np.arange(len(groups)) + (i - (len(keys) - 1) / 2) * w, mu, w * 0.92, yerr=ci, color=C[m], label=LBL[m],
               edgecolor='none', error_kw={'elinewidth': 0.7, 'capsize': 1.5, 'ecolor': 'black'})
    ax.set_xticks(range(len(groups))); ax.set_xticklabels([f'{g:g}' for g in groups]); no_minor_x(ax)
    ax.tick_params(axis='x', which='major', top=False)
    ax.set_xlim(-0.5, len(groups) - 0.5)
    if ylabel: ax.set_ylabel(ylabel)
def _bar_legend(fig, axes):
    h, l = axes[0].get_legend_handles_labels(); top_legend(fig, axes, h, l, 4)
def fig5(args):
    roots = {'stock': 't4val_fixed', 'tuned': 't4tf_val', 'pooled': 't4val_pooled_b1.50', 'perfeat': 't4val_perfeat_b1.50'}
    keys = list(roots)
    fig, ax = plt.subplots(1, 3, figsize=(6.4, 2.5)); nums = []
    for j, tr in enumerate(HELD):
        data = {b: {m: collect(roots[m], tr, cond(1.0, 0.5, b))[0] for m in keys} for b in SB}
        _bars(ax[j], SB, data, keys, 'position error (m)' if j == 0 else ''); plabel(ax[j], f'({"abc"[j]}) {TNAME[tr]}')
        nums += [f'{TNAME[tr]} σ_bad {b}: ' + ', '.join(f'{m} {tci([v[0] for v in data[b][m].values()])[0]:.4f}' for m in keys) for b in SB]
    fig.tight_layout(w_pad=1.2); _bar_legend(fig, ax); shared_xlabel(fig, ax, 'noise of the noisy features (px)')
    save(fig, 'fig5_heldout_bars_pos',
         'Position ATE (mean and 95% t-interval over 30 seeds) on the held-out paths, half the features noisy, 250 points; '
         'per-image and per-feature at β = 1.5, tuned fixed at σ0 = 1.5 px, stock at 1 px. The outdoor path with stops is the '
         'calibration path with stationary pauses; the corridor and the EuRoC room are new paths.', '\n'.join(nums))
def fig6(args):
    roots = {'stock': 't3b', 'tuned': 't4tf_t3bgrid', 'pooled': 't4cal_pooled_b1.50', 'perfeat': 't4cal_perfeat_b1.50'}
    keys = list(roots)
    fig, ax = plt.subplots(1, 4, figsize=(7.0, 2.6)); nums = []
    ax[1].sharey(ax[0]); ax[3].sharey(ax[2])
    for j, (n, f) in enumerate([('', 0.25), ('', 0.5), ('60', 0.25), ('60', 0.5)]):
        data = {b: {m: collect(roots[m], 'udel_gore', cond(1.0, f, b, n))[0] for m in keys} for b in SB}
        _bars(ax[j], SB, data, keys, 'position error (m)' if j == 0 else '')
        plabel(ax[j], f'({"abcd"[j]}) {n or 250} features,\n{f*100:g}% noisy')
        nums += [f'{n or 250} pts f {f} σ_bad {b}: ' + ', '.join(f'{m} {tci([v[0] for v in data[b][m].values()])[0]:.4f}' for m in keys) for b in SB]
    for j in (1, 3): ax[j].tick_params(labelleft=False)
    fig.tight_layout(w_pad=0.8); _bar_legend(fig, ax); shared_xlabel(fig, ax, 'noise of the noisy features (px)')
    save(fig, 'fig6_grid_bars_pos',
         'Position ATE (mean and 95% t-interval over 30 seeds) on the T.3b grid (udel_gore), fraction f of features noisy at '
         'σ_bad, clean features at 1 px; per-image and per-feature at β = 1.5, tuned fixed at σ0 = 1.5 px, stock at 1 px. '
         'Panels with the same number of features share the y-axis.', '\n'.join(nums))

def fig7(args):
    curves = {1.0: [(1.0, 't3b'), (1.25, 't4c_uniform_beta1.25'), (1.5, 't4c_uniform_beta1.50'), (2.0, 't4c_uniform_beta2.00')],
              2.0: [(1.0, 't4a_uniform'), (1.15, 't4c_uniform_sig2_beta1.15'), (1.3, 't4c_uniform_sig2_beta1.30'),
                    (1.5, 't4c_uniform_sig2_beta1.50'), (1.75, 't4c_uniform_sig2_beta1.75'), (2.0, 't4c_uniform_sig2_beta2.00')]}
    sty = {1.0: ('#0C5DA5', 'o', -0.012), 2.0: ('#FF2C00', 's', 0.012)}
    fig, ax = plt.subplots(1, 2, figsize=(6.0, 2.5)); nums = []
    for k in (0, 1): ax[k].axhline(1.0, color='0.6', lw=0.6, ls=(0, (4, 3)), zorder=1)
    for sig, rows in curves.items():
        data = {}
        for be, root in rows:
            c = uniform_conds(root, 'udel_gore').get(sig)
            if c: data[be] = collect(root, 'udel_gore', c)[0]
        if 1.5 not in data: continue
        col, mk, dx = sty[sig]
        for k in (0, 1):
            xs, mu, ci = [], [], []
            for be in sorted(data):
                s = sorted(set(data[be]) & set(data[1.5]))
                if len(s) < 5: continue
                m_, c_ = tci([data[be][i][k] / data[1.5][i][k] for i in s]); xs.append(be); mu.append(m_); ci.append(c_)
            ax[k].errorbar(np.array(xs) + dx, mu, yerr=ci, color=col, marker=mk, mfc='white', mew=1.0, elinewidth=0.8,
                           label=rf'$\sigma = {sig:g}$ px', zorder=3)
            nums.append(f'σ {sig:g} {"pos" if k == 0 else "ori"}: ' + ', '.join(f'β {x:g}: {m:.3f}±{c:.3f}' for x, m, c in zip(xs, mu, ci)))
    for k, t in ((0, '(a) Position'), (1, '(b) Orientation')):
        ax[k].set_xlabel(r'noise inflation factor $\beta$'); plabel(ax[k], t)
        ax[k].set_xlim(0.92, 2.08); ax[k].set_xticks([1.0, 1.25, 1.5, 1.75, 2.0]); ax[k].set_xticklabels(['1', '1.25', '1.5', '1.75', '2'])
    ax[0].set_ylabel(r'error / error at $\beta = 1.5$'); ax[1].legend(loc='upper right')
    fig.tight_layout(w_pad=1.5)
    save(fig, 'fig7_beta_curves',
         'Effect of inflating every σ by β, uniform noise, udel_gore, 250 points: per-seed ATE ratio to β = 1.5 (mean and 95% '
         't-interval, 30 paired seeds; markers offset slightly in β for legibility). Some inflation clearly helps at both noise '
         'levels; position is flat between about 1.15 and 2.0 at σ = 2 px, orientation keeps improving up to 2.0.', '\n'.join(nums))

def fig8(args):
    meth = [('stock', 't3a'), ('tuned', 't4tf_uniform'), ('perfeat', 't4a_uniform')]
    fig, ax = plt.subplots(1, 3, figsize=(6.4, 2.5), sharey=True); nums = []
    for j, tr in enumerate(TRAJ3):
        for m, root in meth:
            xs, med, lo, hi = [], [], [], []
            for sig, c in uniform_conds(root, tr).items():
                ok, div, n = collect(root, tr, c)
                if len(ok) < 10: continue
                v = np.array([x[0] for x in ok.values()]); xs.append(sig); med.append(np.median(v))
                lo.append(np.percentile(v, 25)); hi.append(np.percentile(v, 75))
            if xs:
                ax[j].plot(xs, med, marker=MK[m], mfc='white', mew=1.0, ms=4, color=C[m], label=LBL[m] if m != 'perfeat' else LBL_TRUE)
                ax[j].fill_between(xs, lo, hi, color=C[m], alpha=0.15, lw=0)
                nums.append(f'{TNAME[tr]} {m}: ' + ', '.join(f'σ {x:g}: {y:.3f}' for x, y in zip(xs, med)))
        plabel(ax[j], f'({"abc"[j]}) {TNAME[tr]}'); ax[j].set_yscale('log'); ax[j].set_xlim(0.85, 3.15)
        ax[j].set_xticks([1, 1.5, 2, 2.5, 3]); ax[j].set_xticklabels(['1', '1.5', '2', '2.5', '3'])
    for j in (1, 2): ax[j].tick_params(labelleft=False)
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter   # plain numbers on the log axis
    ax[0].yaxis.set_major_locator(FixedLocator([0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10]))
    ax[0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}')); ax[0].yaxis.set_minor_formatter(NullFormatter())
    ax[0].set_ylabel('position error (m)')
    fig.tight_layout(w_pad=0.8)
    h, l = ax[0].get_legend_handles_labels(); top_legend(fig, ax, h, l, 3); shared_xlabel(fig, ax, r'true pixel noise $\sigma$ (px)')
    save(fig, 'fig8_uniform_accuracy',
         'Accuracy under uniform noise: median (markers) and interquartile range (band) of position ATE over the runs that did '
         'not diverge, log scale (points shown only where at least 10 of 30 survived). The per-feature filter given the true σ '
         '(β = 1) degrades smoothly; the fixed filters stop at their breakdown.', '\n'.join(nums))

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
    fig, ax = plt.subplots(figsize=(3.8, 3.4))
    for m in ('stock', 'tuned', 'perfeat'):
        e = _xy(rdir(roots[m], tr, cs[m], seed) + '/state_estimate.txt')
        if e is not None:
            ax.plot(e[:, 0], e[:, 1], color=C[m], lw=1.0, label=(LBL[m] if m != 'perfeat' else LBL_TRUE), zorder=3 if m == 'perfeat' else 2)
    ax.plot(gt[:, 0], gt[:, 1], color=C['gt'], lw=0.9, ls=(0, (3, 2)), label='ground truth', zorder=4)
    pad = 0.15 * max(np.ptp(gt[:, 0]), np.ptp(gt[:, 1]))
    ax.set_xlim(gt[:, 0].min() - pad, gt[:, 0].max() + pad); ax.set_ylim(gt[:, 1].min() - pad, gt[:, 1].max() + pad)
    ax.set_aspect('equal'); ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=2)
    save(fig, 'fig9_trajectory_example',
         f'Top view of one run (udel_gore, uniform σ = 2.5 px, seed {seed}): both fixed-R filters lose track and leave the '
         'frame, the per-feature filter given the true σ (β = 1) follows the ground truth.', f'seed {seed}, ground-truth length {L:.1f} m')

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
