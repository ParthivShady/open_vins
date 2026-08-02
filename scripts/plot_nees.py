#!/usr/bin/env python3
"""
Position consistency plot for T.1 (extendable to orientation/velocity/biases).

Column layout note:
  state_estimate.txt and state_groundtruth.txt use quaternion (4 storage) then
  position (3 storage) for the IMU state -- position at cols 5,6,7.

  state_deviation.txt writes tangent-space std devs. Quaternion becomes
  3 components (not 4), so position std lives at cols 4,5,6 -- offset by 1.

Reads OpenVINS state trio and writes a PNG with per-axis error±3σ and NEES.
Runs headless via matplotlib Agg backend.

Usage:
  plot_nees.py <est.txt> <std.txt> <gt.txt> <output.png>
"""
import sys
import os
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import matplotlib.pyplot as plt


# Position column ranges are DIFFERENT between est/gt and std files.
POS_COLS_EST_GT = (5, 6, 7)   # quaternion is 4 storage cols
POS_COLS_STD    = (4, 5, 6)   # quaternion is 3 tangent cols in std file


def load_cols(path, cols):
    data = np.loadtxt(path, comments='#')
    if data.ndim == 1:
        data = data.reshape(1, -1)
    t = data[:, 0]
    x = data[:, cols[0]:cols[-1] + 1]
    return t, x


def main():
    if len(sys.argv) != 5:
        print("usage: plot_nees.py <est.txt> <std.txt> <gt.txt> <output.png>",
              file=sys.stderr)
        sys.exit(1)

    est_path, std_path, gt_path, out_path = sys.argv[1:5]

    t_est, p_est = load_cols(est_path, POS_COLS_EST_GT)
    t_std, p_std = load_cols(std_path, POS_COLS_STD)
    t_gt,  p_gt  = load_cols(gt_path,  POS_COLS_EST_GT)

    n = min(len(t_est), len(t_std), len(t_gt))
    if not (len(t_est) == len(t_std) == len(t_gt)):
        print(f"warn: row counts differ ({len(t_est)}/{len(t_std)}/{len(t_gt)}), "
              f"clipping to {n}", file=sys.stderr)

    t_est = t_est[:n]; p_est = p_est[:n]
    t_std = t_std[:n]; p_std = p_std[:n]
    t_gt  = t_gt[:n];  p_gt  = p_gt[:n]

    err = p_est - p_gt
    sigma = p_std
    t_rel = t_est - t_est[0]

    sigma_safe = np.where(sigma < 1e-9, 1e-9, sigma)
    nees = np.sum((err / sigma_safe) ** 2, axis=1)
    nees_mean = np.mean(nees)

    inside_frac = np.mean(np.abs(err) <= 3 * sigma_safe, axis=0)

    fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True)
    axis_names = ['x', 'y', 'z']
    for i, ax in enumerate(axes[:3]):
        ax.plot(t_rel, err[:, i], 'b-', linewidth=0.8, label=f'err {axis_names[i]}')
        ax.fill_between(t_rel, -3 * sigma[:, i], 3 * sigma[:, i],
                        color='gray', alpha=0.25, label='±3σ')
        ax.axhline(0, color='k', linewidth=0.4)
        ax.set_ylabel(f'{axis_names[i]} err (m)')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize=8)
        ax.set_title(f'{axis_names[i]}: {100*inside_frac[i]:.1f}% inside ±3σ',
                     fontsize=9, loc='right')

    ax = axes[3]
    ax.plot(t_rel, nees, 'r-', linewidth=0.7, label='position NEES')
    ax.axhline(3, color='k', linestyle=':', linewidth=1.0, label='expected mean = 3')
    ax.axhline(nees_mean, color='b', linestyle='--', linewidth=1.0,
               label=f'measured mean = {nees_mean:.2f}')
    ax.set_xlabel('time (s)')
    ax.set_ylabel('NEES')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=8)
    ax.set_yscale('symlog', linthresh=1)

    fig.suptitle(f'T.1 position consistency — udel_gore, stereo, seed 5, '
                 f'sim_do_perturbation=false | mean NEES = {nees_mean:.2f} (target ~3)',
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_path, dpi=140, bbox_inches='tight')
    print(f"wrote {out_path}")
    print(f"  mean position NEES: {nees_mean:.3f}  (target ~3)")
    print(f"  inside ±3σ: x={100*inside_frac[0]:.1f}%  "
          f"y={100*inside_frac[1]:.1f}%  z={100*inside_frac[2]:.1f}%")


if __name__ == "__main__":
    main()
