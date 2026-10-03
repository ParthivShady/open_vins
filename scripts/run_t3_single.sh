#!/bin/bash
# T.3 single run: one trajectory, one noise condition, one seed.
# Usage: run_t3_single.sh <traj> <seed> <sim_sigma_pix> <bad_fraction> <sigma_bad> <out_root> [num_pts]
#   e.g. run_t3_single.sh udel_gore 5 1.0 0.5 4.0 ~/navcore_ws/results/t3_smoke
#        run_t3_single.sh udel_gore 5 1.0 0.5 2.5 ~/navcore_ws/results/t3b_pilot 60
# Filter stays at the config's up_msckf_sigma_px (1.0). Monte Carlo varies sim_seed_measurements only.
# num_pts is optional; if omitted the config value (250) is used and the folder name has no _n suffix.
set -e
TRAJ=${1:?traj}; SEED=${2:?seed}; ROOT=${6:?out_root}; NPTS=${7:-}
# Force decimal formatting: ROS2 reads "1" as int and OpenVINS expects double.
SIG=$(printf "%.3f" "${3:?sim_sigma_pix}")
FRAC=$(printf "%.3f" "${4:?bad_fraction}")
SBAD=$(printf "%.3f" "${5:?sigma_bad}")

TRAJ_PATH=~/navcore_ws/src/open_vins/ov_data/sim/${TRAJ}.txt
[ -f "$TRAJ_PATH" ] || { echo "ERROR: trajectory not found: $TRAJ_PATH"; exit 1; }
CONFIG=~/navcore_ws/src/open_vins/config/navcore_sim_t1/estimator_config.yaml

COND=sig${SIG}_f${FRAC}_bad${SBAD}
EXTRA=()
if [ -n "$NPTS" ]; then
  COND=${COND}_n${NPTS}
  EXTRA=(-p num_pts:=$NPTS)   # integer param, no decimal
fi
OUT=$ROOT/$TRAJ/$COND/seed${SEED}
mkdir -p "$OUT"

source ~/navcore_ws/install/setup.bash
START=$(date +%s)
# '|| true': run_simulation segfaults on ROS2 shutdown (known, harmless); don't abort batches on it.
NAVCORE_GATE_LOG=$OUT/gate.csv timeout -s INT -k 30 900 ros2 run ov_msckf run_simulation "$CONFIG" --ros-args \
  -p sim_traj_path:=$TRAJ_PATH \
  -p sim_seed_measurements:=$SEED \
  -p sim_sigma_pix:=$SIG \
  -p sim_bad_fraction:=$FRAC \
  -p sim_sigma_bad:=$SBAD \
  "${EXTRA[@]}" \
  -p save_total_state:=true \
  -p filepath_est:=$OUT/state_estimate.txt \
  -p filepath_std:=$OUT/state_deviation.txt \
  -p filepath_gt:=$OUT/state_groundtruth.txt \
  > "$OUT/run.log" 2>&1 || true
echo "elapsed_s=$(( $(date +%s) - START ))" >> "$OUT/run.log"

# Sanity: confirm the run used the requested noise settings
grep -q "\[NavCore\] sim noise: sim_sigma_pix=$SIG sim_bad_fraction=$FRAC sim_sigma_bad=$SBAD" "$OUT/run.log" \
  || echo "WARN: requested noise settings NOT confirmed in $OUT/run.log"
echo "$TRAJ seed=$SEED $COND | $(grep 'rmse =>' "$OUT/run.log" | tail -1)"
