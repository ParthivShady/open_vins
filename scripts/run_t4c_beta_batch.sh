#!/bin/bash
# T.4c-pre: does inflating R help when every feature already has its true sigma?
# Uniform noise (sigma 1.0), per-feature oracle scaled by beta (NAVCORE_ORACLE_SCALE), udel_gore.
# beta {1.25, 1.5, 2.0} x num_pts {250, 60} x 30 seeds = 180 runs. beta = 1 is the T.3b uniform cell.
# Seed-outer ordering, resumable. Aborts if a run does not show the scaled oracle active.
export NAVCORE_R_MODE=1
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
TRAJ=udel_gore
BETAS=(1.25 1.5 2.0)
NPTS=("" 60)
NSEEDS=30
TOTAL=$(( ${#BETAS[@]} * ${#NPTS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4c beta batch start: $(date) | $TOTAL runs"
for seed in $(seq 1 $NSEEDS); do
  for np in "${NPTS[@]}"; do
    for beta in "${BETAS[@]}"; do
      i=$((i+1))
      export NAVCORE_ORACLE_SCALE=$beta
      ROOT=~/navcore_ws/results/t4c_uniform_beta$(printf "%.2f" $beta)
      COND=sig1.000_f0.000_bad1.000; [ -n "$np" ] && COND=${COND}_n${np}
      OUT=$ROOT/$TRAJ/$COND/seed${seed}
      if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
        echo "[$i/$TOTAL] skip (already done): beta=$beta $COND seed=$seed"; continue
      fi
      $S $TRAJ $seed 1.0 0 1.0 $ROOT $np 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) beta=$beta |"
      if ! grep -q "NavCore\] R mode 1, oracle scale $(printf "%.3f" $beta)" "$OUT/run.log" 2>/dev/null; then
        echo "ABORT: scaled oracle not active in $OUT"; exit 1
      fi
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.4c beta batch done: $(date)"
