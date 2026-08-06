#!/bin/bash
# T.3 stereo degradation sweep — sim_sigma_pix ramp × 3 seeds on udel_gore
# Filter fixed at up_msckf_sigma_px=1.0. Presentation deliverable for 20 Aug.
set -e
source ~/navcore_ws/install/setup.bash

CONFIG_DIR=~/navcore_ws/src/open_vins/config/navcore_sim_decouple_smoke
BASE_CONFIG=${CONFIG_DIR}/estimator_config.yaml
BACKUP=${CONFIG_DIR}/estimator_config.yaml.bak
BASE_OUT=~/navcore_ws/results/t3_sweep

cp "$BASE_CONFIG" "$BACKUP"
trap 'mv "$BACKUP" "$BASE_CONFIG"' EXIT

SIGMAS=(1.0 1.25 1.5 1.75 2.0 2.5 3.0)
SEEDS=(5 7 11)

TOTAL=$(( ${#SIGMAS[@]} * ${#SEEDS[@]} ))
COUNT=0

for SIGMA in "${SIGMAS[@]}"; do
  for SEED in "${SEEDS[@]}"; do
    COUNT=$((COUNT + 1))
    OUT=${BASE_OUT}/sigma_${SIGMA}_seed_${SEED}
    mkdir -p "$OUT"

    sed -i "s/^sim_sigma_pix:.*/sim_sigma_pix: ${SIGMA}/" "$BASE_CONFIG"
    sed -i "s/^sim_seed_preturb:.*/sim_seed_preturb: ${SEED}/" "$BASE_CONFIG"
    sed -i "s/^sim_seed_measurements:.*/sim_seed_measurements: ${SEED}/" "$BASE_CONFIG"

    echo "=== [${COUNT}/${TOTAL}] sigma=${SIGMA} seed=${SEED} ==="
    START=$(date +%s)
    ros2 run ov_msckf run_simulation "$BASE_CONFIG" \
      --ros-args \
      -p save_total_state:=true \
      -p filepath_est:=$OUT/state_estimate.txt \
      -p filepath_std:=$OUT/state_deviation.txt \
      -p filepath_gt:=$OUT/state_groundtruth.txt \
      > "$OUT/run.log" 2>&1 || true
    END=$(date +%s)

    echo "  elapsed: $((END - START))s"
    grep -E "rmse =>|avg nees" "$OUT/run.log" | tail -2 | sed 's/^/  /'
  done
done
echo "=== Sweep complete: ${TOTAL} runs ==="
