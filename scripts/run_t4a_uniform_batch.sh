#!/bin/bash
# T.4a uniform: oracle noise (NAVCORE_R_MODE=1) on the T.3a homogeneous sweep. Tests P2 (the cliff).
# With uniform noise the oracle equals a filter configured with the true sigma (MSCKF and SLAM).
# 3 trajectories x 6 sigma levels x 30 seeds = 540 runs; sigma 1.0 skipped (identical to stock, verified).
# Same folder names as T.3a, so each run pairs with its T.3a fixed-R run.
# Seed-outer ordering, resumable. Aborts if a run does not show the oracle active.
export NAVCORE_R_MODE=1
unset NAVCORE_ORACLE_SCALE
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
ROOT=~/navcore_ws/results/t4a_uniform
TRAJS=(udel_gore udel_gore_zupt tum_corridor1_512_16_okvis)
SIGMAS=(1.25 1.5 1.75 2.0 2.5 3.0)
NSEEDS=30
TOTAL=$(( ${#TRAJS[@]} * ${#SIGMAS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4a uniform batch start: $(date) | $TOTAL runs | root $ROOT | NAVCORE_R_MODE=$NAVCORE_R_MODE"
for seed in $(seq 1 $NSEEDS); do
  for traj in "${TRAJS[@]}"; do
    for sig in "${SIGMAS[@]}"; do
      i=$((i+1))
      SIGF=$(printf "%.3f" $sig)
      OUT=$ROOT/$traj/sig${SIGF}_f0.000_bad${SIGF}/seed${seed}
      if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
        echo "[$i/$TOTAL] skip (already done): $traj sig=$SIGF seed=$seed"; continue
      fi
      $S $traj $seed $sig 0 $sig $ROOT 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) |"
      if ! grep -q "NavCore\] R mode 1" "$OUT/run.log" 2>/dev/null; then
        echo "ABORT: oracle not active in $OUT"; exit 1
      fi
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.4a uniform batch done: $(date)"
