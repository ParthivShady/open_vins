#!/bin/bash
# T.2 baseline sim run — override sim_traj_path over the T.1 config.
# Everything else (seeds, sim_do_perturbation=false, stereo, sigma) inherits from navcore_sim_t1.
# Usage: run_t2_baseline.sh <trajectory_basename>
#   e.g. run_t2_baseline.sh udel_arl
set -e

TRAJ=${1:?usage: $0 <trajectory_basename e.g. udel_arl>}
TRAJ_PATH=~/navcore_ws/src/open_vins/ov_data/sim/${TRAJ}.txt

if [ ! -f "$TRAJ_PATH" ]; then
  echo "ERROR: trajectory file not found: $TRAJ_PATH"
  exit 1
fi

source ~/navcore_ws/install/setup.bash
CONFIG=~/navcore_ws/src/open_vins/config/navcore_sim_t1/estimator_config.yaml
OUT=~/navcore_ws/results/t2_baseline/${TRAJ}
mkdir -p "$OUT"

ros2 run ov_msckf run_simulation "$CONFIG" \
  --ros-args \
  -p sim_traj_path:=$TRAJ_PATH \
  -p save_total_state:=true \
  -p filepath_est:=$OUT/state_estimate.txt \
  -p filepath_std:=$OUT/state_deviation.txt \
  -p filepath_gt:=$OUT/state_groundtruth.txt \
  2>&1 | tee "$OUT/run.log"

echo "Done -> $OUT"
