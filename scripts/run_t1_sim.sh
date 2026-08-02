#!/bin/bash
# T.1 baseline sim run — udel_gore, stereo, seed 5, sim_do_perturbation=false
# Config: navcore_sim_t1/estimator_config.yaml (commit c63b681 or later)

set -e
source ~/navcore_ws/install/setup.bash

CONFIG=~/navcore_ws/src/open_vins/config/navcore_sim_t1/estimator_config.yaml
OUT=~/navcore_ws/results/t1

mkdir -p "$OUT"

ros2 run ov_msckf run_simulation "$CONFIG" \
  --ros-args \
  -p save_total_state:=true \
  -p filepath_est:=$OUT/state_estimate.txt \
  -p filepath_std:=$OUT/state_deviation.txt \
  -p filepath_gt:=$OUT/state_groundtruth.txt \
  2>&1 | tee "$OUT/run.log"
