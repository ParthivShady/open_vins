#!/bin/bash
# T.3b: heterogeneous per-feature noise on udel_gore. Filter fixed at 1.0 px; base sim noise 1.0 px.
# Cells: uniform reference + f {0.25, 0.5} x sigma_bad {1.25, 1.5, 2.5}, each at num_pts {250, 60}.
# 14 cells x 30 seeds = 420 runs. Seed-outer ordering, resumable.
# Optional first argument --after-t3a: wait until run_t3a_batch.sh has exited, then start.
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
ROOT=~/navcore_ws/results/t3b
TRAJ=udel_gore
if [ "$1" = "--after-t3a" ]; then
  echo "Waiting for T.3a to finish: $(date)"
  while pgrep -f run_t3a_batch.sh > /dev/null; do sleep 60; done
  echo "T.3a finished. Starting T.3b: $(date)"
fi
CELLS=("0 1.0" "0.25 1.25" "0.25 1.5" "0.25 2.5" "0.5 1.25" "0.5 1.5" "0.5 2.5")
NPTS=("" 60)   # "" = config default (250)
NSEEDS=30
TOTAL=$(( ${#CELLS[@]} * ${#NPTS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.3b batch start: $(date) | $TOTAL runs | root $ROOT"
for seed in $(seq 1 $NSEEDS); do
  for np in "${NPTS[@]}"; do
    for cell in "${CELLS[@]}"; do
      i=$((i+1))
      read F B <<< "$cell"
      COND=sig1.000_f$(printf "%.3f" $F)_bad$(printf "%.3f" $B)
      [ -n "$np" ] && COND=${COND}_n${np}
      OUT=$ROOT/$TRAJ/$COND/seed${seed}
      if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
        echo "[$i/$TOTAL] skip (already done): $COND seed=$seed"; continue
      fi
      $S $TRAJ $seed 1.0 $F $B $ROOT $np 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) |"
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.3b COMPLETE: $(date)"
