#!/bin/bash
# T.3a: homogeneous sigma sweep with fixed filter R (up_msckf_sigma_px = 1.0).
# 3 trajectories x 7 sigma levels x 30 seeds = 630 runs.
# Seed-outer ordering: stopping early still leaves a balanced dataset (fewer seeds, all cells).
# Resumable: runs whose run.log already has an elapsed_s line are skipped.
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
ROOT=~/navcore_ws/results/t3a
TRAJS=(udel_gore udel_gore_zupt tum_corridor1_512_16_okvis)
SIGMAS=(1.0 1.25 1.5 1.75 2.0 2.5 3.0)
NSEEDS=30
TOTAL=$(( ${#TRAJS[@]} * ${#SIGMAS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.3a batch start: $(date) | $TOTAL runs | root $ROOT"
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
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.3a COMPLETE: $(date)"
