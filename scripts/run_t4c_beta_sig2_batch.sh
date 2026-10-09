#!/bin/bash
# T.4c additive-vs-multiplicative check: best inflation beta at true sigma 2.0 (uniform noise), per-feature oracle, udel_gore, 250 pts.
# Predictions (written before running): multiplicative unmodelled error -> best beta ~1.5 again;
# additive floor (sigma_eff^2 = sigma^2 + c, c ~ 1.25 px^2 from the sigma-1 test) -> best beta ~1.15.
# beta {1.15, 1.3, 1.5} x 30 seeds = 90 runs. beta = 1 at sigma 2.0 is results/t4a_uniform.
# Waits for the equal-calibration batch to finish first. Resumable; aborts if the scaled oracle is not active.
while pgrep -f "run_t4cal_batch.sh" > /dev/null; do sleep 60; done
export NAVCORE_R_MODE=1
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
TRAJ=udel_gore
BETAS=(1.15 1.3 1.5)
NSEEDS=30
TOTAL=$(( ${#BETAS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4c sigma-2 beta batch start: $(date) | $TOTAL runs"
for seed in $(seq 1 $NSEEDS); do
  for beta in "${BETAS[@]}"; do
    i=$((i+1))
    export NAVCORE_ORACLE_SCALE=$beta
    ROOT=~/navcore_ws/results/t4c_uniform_sig2_beta$(printf "%.2f" $beta)
    OUT=$ROOT/$TRAJ/sig2.000_f0.000_bad2.000/seed${seed}
    if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
      echo "[$i/$TOTAL] skip (already done): beta=$beta seed=$seed"; continue
    fi
    $S $TRAJ $seed 2.0 0 2.0 $ROOT 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) beta=$beta |"
    if ! grep -q "NavCore\] R mode 1, oracle scale $(printf "%.3f" $beta)" "$OUT/run.log" 2>/dev/null; then
      echo "ABORT: scaled oracle not active in $OUT"; exit 1
    fi
  done
done
echo "T.4c sigma-2 beta batch done: $(date)"
