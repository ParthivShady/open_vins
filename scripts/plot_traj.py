#!/usr/bin/env python3
"""
Plot ground-truth vs estimated trajectory for T.1 (and beyond).

Reads two TUM-format trajectory files (t tx ty tz qx qy qz qw), produces
a three-panel figure written to disk:
  - XY overhead view (est vs gt)
  - Z vs time (est vs gt)
  - Position error norm vs time

Runs headless (MPLBACKEND=Agg by default). Uses only venv-side matplotlib,
so it avoids the embedded-Python namespace split that breaks ov_eval's plot.

Usage:
    plot_traj.py <gt.txt> <est.txt> <output.png>
"""
import sys
import os
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import matplotlib.pyplot as plt


def load_tum(path):
    """Load TUM trajectory: returns (t, xyz, quat_xyzw) as ndarrays."""
    data = np.loadtxt(path)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    t = data[:, 0]
    xyz = data[:, 1:4]
    quat = data[:, 4:8]
    return t, xyz, quat


def main():
    if len(sys.argv) != 4:
        print("usage: plot_traj.py <gt.txt> <est.txt> <output.png>",
              file=sys.stderr)
        sys.exit(1)

    gt_path, est_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    t_gt, xyz_gt, _ = load_tum(gt_path)
    t_est, xyz_est, _ = load_tum(est_path)

    # Sanity: if timestamps don't match row-for-row, we can't compute error norm
    # cleanly. For T.1 they should match exactly (both come from the same sim
    # save cadence). Warn if not.
    if len(t_gt) != len(t_est):
        print(f"warn: gt has {len(t_gt)} rows, est has {len(t_est)} rows; "
              f"clipping to min for error norm", file=sys.stderr)
    n = min(len(t_gt), len(t_est))

    # Time base: seconds from start (Unix epochs are ugly on x-axis)
    t0 = t_gt[0]
    t_gt_rel = t_gt - t0
    t_est_rel = t_est - t0

    err = np.linalg.norm(xyz_gt[:n] - xyz_est[:n], axis=1)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    # Panel 1: XY overhead
    ax = axes[0]
    ax.plot(xyz_gt[:, 0], xyz_gt[:, 1], 'k-', linewidth=1.5, label='ground truth')
    ax.plot(xyz_est[:, 0], xyz_est[:, 1], 'r--', linewidth=1.2, label='estimate')
    ax.scatter(xyz_gt[0, 0], xyz_gt[0, 1], marker='o', c='green', s=40,
               zorder=5, label='start')
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_title('XY overhead')
    ax.axis('equal')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=9)

    # Panel 2: Z vs time
    ax = axes[1]
    ax.plot(t_gt_rel, xyz_gt[:, 2], 'k-', linewidth=1.5, label='ground truth')
    ax.plot(t_est_rel, xyz_est[:, 2], 'r--', linewidth=1.2, label='estimate')
    ax.set_xlabel('time (s)')
    ax.set_ylabel('Z (m)')
    ax.set_title('Altitude vs time')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=9)

    # Panel 3: Position error norm vs time
    ax = axes[2]
    ax.plot(t_gt_rel[:n], err, 'b-', linewidth=1.0)
    rmse = np.sqrt(np.mean(err ** 2))
    ax.axhline(rmse, color='k', linestyle=':', linewidth=1.0,
               label=f'RMSE = {rmse:.3f} m')
    ax.set_xlabel('time (s)')
    ax.set_ylabel('||p_gt - p_est|| (m)')
    ax.set_title('Position error norm')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=9)

    fig.suptitle(f'T.1 baseline — udel_gore, stereo, seed 5, '
                 f'sim_do_perturbation=false | RMSE {rmse:.3f} m',
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_path, dpi=140, bbox_inches='tight')
    print(f"wrote {out_path}  (RMSE = {rmse:.4f} m, n = {n})")


if __name__ == "__main__":
    main()
