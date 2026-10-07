#!/bin/bash
# T.4b: per-frame pooled oracle noise (NAVCORE_R_MODE=2) on the T.3b uneven-noise grid, udel_gore.
# Same seeds, cells and folder names as T.3b, so each run pairs with its T.3b fixed-R run.
# 12 cells x 30 seeds = 360 runs. Uniform cells skipped: there the oracle equals stock (verified bit-identical).
# Seed-outer ordering, resumable. Aborts if a run does not show the oracle active.
export NAVCORE_R_MODE=2
unset NAVCORE_ORACLE_SCALE
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
ROOT=~/navcore_ws/results/t4b_t3bgrid
TRAJ=udel_gore
CELLS=("0.25 1.25" "0.25 1.5" "0.25 2.5" "0.5 1.25" "0.5 1.5" "0.5 2.5")
NPTS=("" 60)   # "" = config default (250)
NSEEDS=30
TOTAL=$(( ${#CELLS[@]} * ${#NPTS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4b batch start: $(date) | $TOTAL runs | root $ROOT | NAVCORE_R_MODE=$NAVCORE_R_MODE"
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
      if ! grep -q "NavCore\] R mode 2" "$OUT/run.log" 2>/dev/null; then
        echo "ABORT: oracle not active in $OUT"; exit 1
      fi
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.4b batch done: $(date)"
