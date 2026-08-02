# NavCore Sim Parameter Reference

**Purpose.** Every knob that affects the OpenVINS simulator + MSCKF filter, where it lives, what it does, its stock default, and NavCore's T.1 value. Consult before changing any sim parameter for T.2–T.7. Also serves as raw material for Chapter 2 (OpenVINS architecture) and Chapter 3 (method plumbing).

**Baseline commits.**
- Stock OpenVINS: `6948812` (Merge PR #530 from rpng/android)
- NavCore T.1 (current HEAD): `f356326` on branch `navcore_weighting`
- All row/column references below are pinned to those hashes. If OpenVINS master moves, re-verify before assuming this doc holds.

**Trajectory & seed.** T.1 uses `udel_gore.txt` (225.29 m, 1698 MSCKF updates at 10 Hz cam / 400 Hz IMU), stereo, seed 5.

---

## 1. Where sim parameters live

Two entirely separate control surfaces feed the sim, and confusing them is the first-order bug source.

### 1a. YAML: `config/navcore_sim_t1/estimator_config.yaml`
Passed to `run_simulation` as `argv[1]`. Parsed by `VioManager`'s config loader. Everything about filter tuning, sim seeds, sim trajectory, camera and IMU frequencies, feature generation, and — importantly — pixel noise σ (indirectly, via `up_msckf_sigma_px`).

### 1b. ROS2 node parameters (passed via `--ros-args -p`)
Read by `ROS2Visualizer` at construction time (`ROS2Visualizer.cpp:84–118`). Controls output file writing. **These are not in the YAML.** The ROS1 launch file set them via `<param>` tags; in ROS2 they must be passed at the command line or via a Python launch file.

NavCore's `run_t1_sim.sh` passes:
- `save_total_state:=true`
- `filepath_est:=~/navcore_ws/results/t1/state_estimate.txt`
- `filepath_std:=~/navcore_ws/results/t1/state_deviation.txt`
- `filepath_gt:=~/navcore_ws/results/t1/state_groundtruth.txt`

If these aren't set, the sim runs successfully but writes nothing to disk. `ROS2Visualizer.cpp` uses `has_parameter()` before `get_parameter()`, so undeclared parameters silently default to `save_total_state = false`. This is exactly what happened on the first T.1 run.

---

## 2. State file column schema (load-bearing)

`state_estimate.txt` and `state_groundtruth.txt` use **manifold storage** — quaternion is 4 numbers `(qx qy qz qw)`.

`state_deviation.txt` uses **tangent-space std devs** — quaternion uncertainty is 3 numbers (rotation vector σ).

**Consequence: column indices differ between the estimate/gt files (79 cols) and the deviation file (75 cols).** Every quaternion in the state block collapses 4→3 in the std file, and every downstream block is shifted left by 1 per collapsed quaternion.

Verified position column indices:

| Block | Estimate / GT cols | Deviation cols |
|---|---|---|
| timestamp | 0 | 0 |
| q_GtoI | 1–4 | 1–3 |
| p_IinG | **5–7** | **4–6** |
| v_IinG | 8–10 | 7–9 |
| bias_g | 11–13 | 10–12 |
| bias_a | 14–16 | 13–15 |

If you index `state_deviation.txt` at cols 5–7 assuming position, you pull `(σ_pz, σ_vx, σ_vy)` — velocity σ leaks into the position slot. This inflates position NEES from ~0.4 to ~8 and violates ±3σ bounds in the z axis while x/y still look fine. **This bug was caught during T.1 by cross-checking against the sim's online NEES average.** `scripts/plot_nees.py` handles the offset correctly.

Full column layout for est/gt (79 cols): timestamp, q_GtoI (4), p_IinG (3), v_IinG (3), bias_g (3), bias_a (3), cam_imu_dt (1), num_cam (1), cam0 [K(4) D(4) q_ItoC0(4) p_C0inI(3)], cam1 [K(4) D(4) q_ItoC1(4) p_C1inI(3)], imu_model (1), Dw (6, upper-triangular), Da (6), Tg (9, full 3×3), q_GYROtoI (4), q_ACCtoI (4).

---

## 3. Simulation parameters (YAML)

Grouped by function. Column "NavCore T.1" shows the value in `navcore_sim_t1/estimator_config.yaml`; "Stock" shows `rpng_sim/estimator_config.yaml` at commit `6948812`.

### 3a. Trajectory & timing

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `sim_traj_path` | `src/open_vins/ov_data/sim/tum_corridor1_512_16_okvis.txt` | `/home/parthivshady/navcore_ws/src/open_vins/ov_data/sim/udel_gore.txt` | Absolute path required for reproducibility across launch directories. |
| `sim_freq_cam` | 10 | 10 | Camera frame rate (Hz). MSCKF update cadence is bounded by this. |
| `sim_freq_imu` | 400 | 400 | IMU sample rate. Propagation cadence. |
| `sim_distance_threshold` | 1.1 | 1.1 | Feature culling threshold (m). |

### 3b. Seeds (pinned for reproducibility)

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `sim_seed_state_init` | 0 | 0 | Initial state perturbation seed. Zero → filter starts exactly at GT. |
| `sim_seed_preturb` | 0 | 5 | Calibration perturbation seed. Dormant while `sim_do_perturbation: false`. |
| `sim_seed_measurements` | 0 | 5 | Pixel noise draws — this is what `w(gen_meas_cams)` in `Simulator.cpp:440–441` samples. |

### 3c. Feature generation

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `sim_min_feature_gen_dist` | 5.0 | 5.0 | Min distance from camera to spawn a feature (m). |
| `sim_max_feature_gen_dist` | 7.0 | 7.0 | Max distance. Together, these bound depth diversity. |
| `num_pts` | 250 | 250 | Total feature target per frame. |

### 3d. Perturbation & calibration

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `sim_do_perturbation` | false | false | **T.1 keeps false.** T.2 flips this true. Under false, calibration starts at truth and NEES sits low (0.4/1.3) because the filter reserves covariance budget it never uses. |
| `calib_cam_extrinsics` | true | true | Filter estimates cam-IMU rigid transform. |
| `calib_cam_intrinsics` | true | true | Filter estimates focal, principal point, distortion. |
| `calib_cam_timeoffset` | true | true | Filter estimates cam-IMU timing offset. |
| `calib_imu_intrinsics` | true | true | Filter estimates IMU intrinsic matrices Dw, Da. |
| `calib_imu_g_sensitivity` | true | true | Filter estimates gyro-gravity sensitivity Tg. |

### 3e. Filter core

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `use_fej` | true | true | First-estimate Jacobians. **Must stay on for consistency; do not touch.** |
| `integration` | rk4 | rk4 | IMU integration. Analytical covariance propagation is used with rk4/analytical. |
| `use_stereo` | true | true | Stereo tracking. **Load-bearing for T.3 claim.** |
| `max_cameras` | 2 | 2 | 2 = stereo. |
| `max_clones` | 11 | 11 | Sliding window length in MSCKF. |
| `max_slam` | 50 | 50 | SLAM features in the state. |
| `max_slam_in_update` | 25 | 25 | |
| `max_msckf_in_update` | 10 | 10 | |
| `gravity_mag` | 9.81 | 9.81 | |

### 3f. Feature representation

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `feat_rep_msckf` | GLOBAL_3D | GLOBAL_3D | Feature parameterisation for MSCKF updates. |
| `feat_rep_slam` | GLOBAL_3D | GLOBAL_3D | |
| `feat_rep_aruco` | GLOBAL_3D | GLOBAL_3D | |

---

## 4. Noise parameters (the coupling story)

### 4a. Filter-assumed R

| Key | Stock | NavCore T.1 | Notes |
|---|---|---|---|
| `up_msckf_sigma_px` | 1 | 1 | Filter's assumed per-pixel noise for MSCKF updates. This is what builds R inside `UpdaterMSCKF`. |
| `up_slam_sigma_px` | 1 | 1 | Same, for SLAM feature updates. |
| `up_aruco_sigma_px` | 1 | 1 | ArUco updates, not exercised in NavCore. |

### 4b. Truth-side pixel noise: **coupled to filter-assumed R (T.1 finding)**

There is no `sim_sigma_px` key. Instead, `Simulator.cpp:440–441` scales injected Gaussian pixel noise by `params.msckf_options.sigma_pix` — the *same* field that `UpdaterMSCKF` uses to construct R:

```cpp
uvs.at(j).second(0) += params.msckf_options.sigma_pix * w(gen_meas_cams.at(i));
uvs.at(j).second(1) += params.msckf_options.sigma_pix * w(gen_meas_cams.at(i));
```

**Implication.** In stock OpenVINS, changing `up_msckf_sigma_px` changes both the injected noise and the filter's belief about it simultaneously. Model match is preserved by construction. NEES stays at ≈3 with `sim_do_perturbation: true`. A T.3 σ-mismatch sweep cannot produce a degradation curve with this simulator.

**T.1 → T.3 bridge: the decoupling patch.** Required before T.3 begins. Introduces `params.sim.sigma_pix_truth` as a per-feature vector, keeps `params.msckf_options.sigma_pix` as the filter's scalar belief. Touches only `Simulator.cpp`, `Simulator.h`, the options struct, and `parse_ros.h`. Does not touch H, FEJ, or `State.h`. Roughly 20 lines; see the T.1 → T.3 patch commit when it lands.

### 4c. IMU noise

IMU continuous-time noise densities are pulled from `kalibr_imu_chain.yaml`, not from `estimator_config.yaml`. Not audited in this doc for T.1; revisit for T.6 stress runs.

---

## 5. NavCore output paths (via ROS parameters)

Written as ROS2 node parameters, not YAML keys. Passed by `run_t1_sim.sh` on the `ros2 run` command line. See section 1b.

- `filepath_est` → `~/navcore_ws/results/t1/state_estimate.txt` (79 cols)
- `filepath_std` → `~/navcore_ws/results/t1/state_deviation.txt` (75 cols)
- `filepath_gt` → `~/navcore_ws/results/t1/state_groundtruth.txt` (79 cols)

---

## 6. T.1 exit results (locked)

Reproduced by: `~/navcore_ws/scripts/run_t1_sim.sh` at commit `f356326` on branch `navcore_weighting`.

**Trajectory:** `udel_gore.txt`, 225.29 m, 1698 MSCKF updates.
**Config:** `navcore_sim_t1/estimator_config.yaml`.
**Seed:** 5.
**Perturbation:** off.

**Absolute Trajectory Error (position):**
- RMSE = **0.046 m**
- mean 0.042 m, max 0.093 m, std 0.018 m

**ATE (orientation):**
- RMSE = **0.277°**
- mean 0.244°, max 1.211°, std 0.132°

**Relative Pose Error (median position error per segment length):**
- 8 m → 0.017 m
- 16 m → 0.024 m
- 24 m → 0.033 m
- 32 m → 0.040 m
- 40 m → 0.047 m

Roughly linear drift at ~0.1% per metre.

**Position NEES (offline, `scripts/plot_nees.py`):** mean **0.398**, 100% inside ±3σ on all axes. Consistent with the sim log's online average (0.4). The low value is expected under `sim_do_perturbation: false`: initial state and calibration start at truth, so the filter's covariance budget goes unused. **Re-verify at T.2 with `sim_do_perturbation: true` — target is NEES ≈ 3.**

**Cross-checks (four independent code paths, all agreeing):**
- Sim's own online RMSE: 0.045 m, NEES 0.4
- `ov_eval error_singlerun`: 0.046 m
- `scripts/plot_traj.py`: 0.0455 m
- `scripts/plot_nees.py`: NEES 0.398

**Artifacts:**
- `~/navcore_ws/results/t1/plot_traj.png` (168 KB, 2090×623)
- `~/navcore_ws/results/t1/plot_nees.png` (207 KB, 1525×1377)
- `~/navcore_ws/results/t1/ate.log`
- `~/navcore_ws/results/t1/run.log`
- `~/navcore_ws/results/t1/traj_estimate.txt`, `traj_groundtruth.txt` (TUM format, 1698 rows)
- `~/navcore_ws/results/t1/state_estimate.txt`, `state_deviation.txt`, `state_groundtruth.txt`

---

## 7. Code locations that matter

| Path | Why it matters |
|---|---|
| `ov_msckf/src/sim/Simulator.cpp:440–441` | Where injected pixel noise is scaled by `params.msckf_options.sigma_pix`. The coupling smoking gun. |
| `ov_msckf/src/sim/Simulator.h` | Simulator class declaration. Options struct lives adjacent. |
| `ov_msckf/src/update/UpdaterMSCKF.cpp` | Where R is built from `sigma_pix`. **The only file NavCore modifies for adaptive R.** |
| `ov_msckf/src/update/UpdaterHelper.cpp` | Read but do not modify. Contains null-space projection. Trace before Gate 2.5 to confirm per-feature R survives it. |
| `ov_msckf/src/state/State.h` | **Do not modify. Ever.** |
| `ov_msckf/src/state/PropagatorHelper*` | **Do not modify.** FEJ evaluation lives here. |
| `ov_core/src/track/TrackKLT.cpp` | Where front-end reliability metrics (F-B error, keypoint density, flow consistency) will originate at T.4. |
| `ov_msckf/src/core/VioManager.cpp` | Front-end → back-end plumbing. Route reliability metrics here at T.4. |
| `ov_msckf/src/utils/parse_ros.h` | YAML → options struct parser. Decoupling patch will edit here. |
| `ov_msckf/src/ros/ROS2Visualizer.cpp:84–118` | Where `save_total_state` and the three filepath ROS parameters are read. |
| `ov_msckf/cmake/ROS2.cmake:96` | Executable registration for `run_simulation`. |

---

## 8. Open questions parked for future gates

- **T.2:** flip `sim_do_perturbation: true`, confirm NEES climbs toward ~3 with matched noise. If not, filter is still miscalibrated somewhere.
- **T.3:** requires the decoupling patch. Once landed, sweep `sigma_pix_truth` from 1 → 5 px while filter belief stays at 1 px. Report ATE and NEES.
- **T.3 escalation:** if uniform stereo σ mismatch does not degrade the filter, add per-feature heterogeneity, then asymmetric single-camera degradation, then outlier injection.
- **T.4:** IMU noise density audit from `kalibr_imu_chain.yaml`. Add to this doc when relevant.
