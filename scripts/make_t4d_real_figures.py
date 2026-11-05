#!/usr/bin/env python3
"""NavCore real-data figures (EuRoC, deterministic serial runs with IMU dither), in the thesis paper style.
Usage:  ~/navcore_ws/.venv/bin/python scripts/make_t4d_real_figures.py [results_dir] [out_dir]
        defaults: ~/navcore_ws/results/t4d_euroc_dither  and  ~/navcore_ws/results/figures
Writes (PDF for LaTeX, PNG for a quick look):
  fig_real_sequences   median position error per held-out sequence for the OpenVINS default, tuned fixed noise, the
                       one-value-per-image version and the proposed per-feature method,
                       bars = middle half of the seeds; runs that lost track are drawn as triangles at the top
  fig_mh05_gate        MH_05, logged run of each setting: (a) share of MSCKF features the gate accepted and
                       (b) number accepted, per 10 s window
  fig_mh01_sweep       MH_01: position error against the noise setting, fixed noise and G1c floors
Settings are read from calibration_MH_01_easy.txt in the results folder (fixed, g1c and pfr lines)."""
import glob, gzip, os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator

RES = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/navcore_ws/results/t4d_euroc_dither')
OUT = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else '~/navcore_ws/results/figures')
LOST = 2.0          # m: above this a run counts as lost for the figures (all lost runs here are 100 m or more)
# Plain-language labels used in every figure (no internal names). Edit here to change wording everywhere.
LABEL = {'stock': 'OpenVINS default (1.0 px)', 'fixed': 'fixed noise, tuned on MH 01 ({} px)',
         'pfr': 'adaptive, one value per image', 'g1c': 'adaptive, per feature (proposed)', 'lost': 'lost track (median error)',
         'sweep_fixed': 'fixed noise', 'sweep_g1c': 'proposed (setting = lower limit)',
         'sweep_x': 'pixel-noise setting (px)'}
SEQS = ['MH_02_easy', 'MH_03_medium', 'MH_04_difficult', 'MH_05_difficult', 'V1_01_easy', 'V1_02_medium',
        'V1_03_difficult', 'V2_01_easy', 'V2_02_medium', 'V2_03_difficult']


def paper_style():
    """Computer Modern Sans to match Beamer, sans maths, full box with inward ticks, no grid, small legends."""
    plt.rcParams.update({
        'font.family': 'sans-serif', 'font.sans-serif': ['cmss10', 'CMU Sans Serif', 'DejaVu Sans'],
        'mathtext.fontset': 'custom', 'mathtext.rm': 'cmss10', 'mathtext.it': 'cmss10', 'mathtext.bf': 'cmss10',
        'mathtext.fallback': 'cm',
        'axes.unicode_minus': False, 'axes.formatter.use_mathtext': True,
        'font.size': 9, 'axes.labelsize': 9, 'legend.fontsize': 8, 'xtick.labelsize': 8, 'ytick.labelsize': 8,
        'axes.linewidth': 0.6, 'axes.grid': False, 'axes.spines.top': True, 'axes.spines.right': True,
        'xtick.direction': 'in', 'ytick.direction': 'in', 'xtick.top': True, 'ytick.right': True,
        'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'xtick.minor.width': 0.4, 'ytick.minor.width': 0.4,
        'xtick.major.size': 3, 'ytick.major.size': 3, 'xtick.minor.size': 1.5, 'ytick.minor.size': 1.5,
        'legend.frameon': False, 'legend.handlelength': 1.4, 'lines.linewidth': 1.0, 'lines.markersize': 4,
        'savefig.bbox': 'tight', 'savefig.pad_inches': 0.02, 'pdf.fonttype': 42,
    })


def log_ticks(axis, ticks):
    """plain decimal labels on a log axis (no 10^k), no minor labels"""
    axis.set_major_locator(FixedLocator(ticks))
    axis.set_ticklabels([f'{t:g}' for t in ticks])
    axis.set_minor_locator(NullLocator())
    axis.set_minor_formatter(NullFormatter())


def panel(ax, letter):
    ax.text(-0.02, 1.02, f'({letter})', transform=ax.transAxes, ha='right', va='bottom', fontsize=9)


def runs(seq, cfg):
    """position errors of runs 1..N (run 0 is the logged check run)"""
    v = []
    for d in glob.glob(f'{RES}/{seq}/{cfg}/run*'):
        r = os.path.basename(d)[3:]
        f = os.path.join(d, 'ate.txt')
        if r.isdigit() and int(r) > 0 and os.path.isfile(f):
            v.append(float(open(f).read().split()[0]))
    return np.array(v)


def calibration():
    cal = {}
    f = os.path.join(RES, 'calibration_MH_01_easy.txt')
    for line in open(f):
        p = line.split()
        if len(p) == 2 and p[0] in ('fixed', 'g1c', 'pfr'):
            cal[p[0]] = p[1]
    return cal


def method_list(cal):
    return [('fixed1.00', LABEL['stock'], '#9a9a9a', 'v'),
            (cal['fixed'], LABEL['fixed'].format(f"{float(cal['fixed'][5:]):g}"), '#4d4d4d', 's'),
            (cal.get('pfr'), LABEL['pfr'], '#c96f00', 'D'), (cal['g1c'], LABEL['g1c'], '#1f4e79', 'o')]


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    for ext in ('pdf', 'png'):
        fig.savefig(os.path.join(OUT, f'{name}.{ext}'), dpi=200)
    plt.close(fig)
    print(f'wrote {OUT}/{name}.pdf')


def stats(v):
    q = np.percentile(v, [25, 50, 75])
    return q[0], q[1], q[2]


def fig_sequences(cal):
    methods = [m for m in method_list(cal) if m[0]]
    seqs = [s for s in SEQS if os.path.isdir(f'{RES}/{s}/{cal["g1c"]}') and len(runs(s, cal['g1c']))]
    if not seqs:
        print('no held-out sequences with G1c results: fig_real_sequences skipped')
        return
    fig, ax = plt.subplots(figsize=(6.3, 2.6))
    w = 0.17
    top = 1.6
    for k, (cfg, label, col, mk) in enumerate(methods):
        dx = (k - (len(methods) - 1) / 2) * w
        for i, s in enumerate(seqs):
            v = runs(s, cfg)
            if not len(v):
                continue
            q1, med, q3 = stats(v)
            x = i + dx
            if med > LOST:   # lost track: triangle at the top with the median error
                ax.plot(x, top, marker='^', color=col, ms=5, clip_on=False)
                txt = f'{med / 1000:.1f} km' if med >= 1000 else f'{med:.0f} m'
                ax.text(x, top * 1.12, txt, rotation=90, ha='center', va='bottom', fontsize=6.5, color=col)
                continue
            ax.plot([x, x], [q1, min(q3, top)], color=col, lw=1.0)
            ax.plot(x, med, marker=mk, color=col, ms=4, ls='none', label=label if i == 0 else None)
    ax.set_yscale('log')
    ax.set_ylim(0.02, top)
    log_ticks(ax.yaxis, [0.02, 0.05, 0.1, 0.2, 0.5, 1])
    ax.set_xlim(-0.6, len(seqs) - 0.4)
    ax.set_xticks(range(len(seqs)))
    ax.set_xticklabels([s.replace('_', ' ', 1).rsplit('_', 1)[0] + '\n' + s.rsplit('_', 1)[1] for s in seqs])
    ax.tick_params(axis='x', which='both', top=False)
    ax.set_ylabel('position error (m)')
    for i in range(len(seqs) - 1):
        ax.axvline(i + 0.5, color='0.85', lw=0.4, zorder=0)
    handles = [plt.Line2D([], [], color=c, marker=m, ls='-', lw=1.0, ms=4) for _, _, c, m in methods]
    handles.append(plt.Line2D([], [], color='0.3', marker='^', ls='none', ms=5))
    ax.legend(handles, [l for _, l, _, _ in methods] + [LABEL['lost']], ncol=3, loc='lower center',
              bbox_to_anchor=(0.5, 1.2), columnspacing=1.2)
    save(fig, 'fig_real_sequences')


def gate_windows(seq, cfg, width=10.0):
    f = f'{RES}/{seq}/{cfg}/run0/gate_feat.csv.gz'
    if not os.path.isfile(f):
        return None
    t, acc = [], []
    with gzip.open(f, 'rt') as fh:
        next(fh)
        for line in fh:
            p = line.split(',')
            if p[1] == '0':   # MSCKF rows
                t.append(float(p[0]))
                acc.append(int(p[8]))
    t, acc = np.array(t), np.array(acc)
    b = ((t - t.min()) // width).astype(int)
    n = np.bincount(b)
    a = np.bincount(b, weights=acc)
    centre = (np.arange(len(n)) + 0.5) * width
    keep = n > 0
    return centre[keep], 100 * a[keep] / n[keep], a[keep]


def fig_gate(cal, seq='MH_05_difficult'):
    methods = method_list(cal)
    data = [(m, gate_windows(seq, m[0])) for m in methods if m[0]]
    data = [(m, d) for m, d in data if d is not None]
    if not data:
        print(f'no gate logs for {seq}: fig_mh05_gate skipped')
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 2.3))
    for (cfg, label, col, mk), (tc, share, nacc) in data:
        a1.plot(tc, share, color=col, marker=mk, ms=3, label=label)
        a2.plot(tc, np.maximum(nacc, 0.8), color=col, marker=mk, ms=3, label=label)
    a1.set_ylim(0, 100)
    a1.set_ylabel('features accepted (%)')
    a2.set_yscale('log')
    a2.set_ylim(0.8, 1500)
    log_ticks(a2.yaxis, [1, 10, 100, 1000])
    a2.set_ylabel('features accepted per 10 s')
    for a, letter in ((a1, 'a'), (a2, 'b')):
        a.set_xlabel('time from start (s)')
        panel(a, letter)
    fig.tight_layout(w_pad=2.0)
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, ncol=2, loc='lower center', bbox_to_anchor=(0.5, 1.0), columnspacing=1.5)
    save(fig, 'fig_mh05_gate')


def fig_sweep(cal, seq='MH_01_easy'):
    beta = cal['g1c'].split('_b')[1].split('_')[0]
    fixed = sorted((float(os.path.basename(d)[5:]), os.path.basename(d)) for d in glob.glob(f'{RES}/{seq}/fixed*'))
    g1c = sorted((float(os.path.basename(d).split('_f')[1]), os.path.basename(d)) for d in glob.glob(f'{RES}/{seq}/g1c_b{beta}_f*'))
    if not fixed:
        print(f'no fixed runs for {seq}: fig_mh01_sweep skipped')
        return
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    top = 0.3
    for series, label, col, mk, dx in ((fixed, LABEL['sweep_fixed'], '#4d4d4d', 's', -0.012), (g1c, LABEL['sweep_g1c'], '#1f4e79', 'o', 0.012)):
        xs, meds = [], []
        for x, cfg in series:
            v = runs(seq, cfg)
            if not len(v):
                continue
            q1, med, q3 = stats(v)
            if med > LOST:
                ax.plot(x + dx, top, marker='^', color=col, ms=5, clip_on=False)
                ax.text(x + dx + 0.05, top * 0.93, f'lost ({med / 1000:.0f} km)' if med >= 1000 else f'lost ({med:.0f} m)',
                        fontsize=6.5, color=col, va='top')
                xs.append(x + dx)
                meds.append(np.nan)   # break the line at a lost setting
                continue
            ax.plot([x + dx, x + dx], [q1, q3], color=col, lw=1.0)
            xs.append(x + dx)
            meds.append(med)
        ax.plot(xs, meds, color=col, marker=mk, ms=4, lw=0.8, label=label)
    ax.set_xscale('log')
    log_ticks(ax.xaxis, [0.4, 0.5, 0.75, 1, 1.5, 2, 3])
    ax.set_yscale('log')
    ax.set_ylim(0.04, top)
    log_ticks(ax.yaxis, [0.05, 0.1, 0.2])
    ax.set_xlabel(LABEL['sweep_x'])
    ax.set_ylabel('position error (m)')
    ax.legend(loc='lower right')
    save(fig, 'fig_mh01_sweep')


if __name__ == '__main__':
    paper_style()
    cal = calibration()
    print(f'settings from the calibration file: {cal}')
    fig_sequences(cal)
    fig_gate(cal)
    fig_sweep(cal)
