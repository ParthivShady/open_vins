#!/bin/bash
# T.4 equal calibration: per-feature (mode 1) vs per-frame pooled (mode 2), both with global inflation beta = 1.5,
# calibrated on the uniform cell (results/t4c_uniform_beta*). T.3b uneven-noise grid, udel_gore.
# 2 modes x 12 cells x 30 seeds = 720 runs. Uniform cells skipped: both modes equal results/t4c_uniform_beta1.50 there.
# Seed-outer ordering, resumable. Aborts if a run does not show the expected mode and scale.
export NAVCORE_ORACLE_SCALE=1.5
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
TRAJ=udel_gore
CELLS=("0.25 1.25" "0.25 1.5" "0.25 2.5" "0.5 1.25" "0.5 1.5" "0.5 2.5")
NPTS=("" 60)
MODES=(1 2)
NSEEDS=30
TOTAL=$(( ${#CELLS[@]} * ${#NPTS[@]} * ${#MODES[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4 equal-calibration batch start: $(date) | $TOTAL runs | beta=$NAVCORE_ORACLE_SCALE"
for seed in $(seq 1 $NSEEDS); do
  for np in "${NPTS[@]}"; do
    for mode in "${MODES[@]}"; do
      export NAVCORE_R_MODE=$mode
      if [ "$mode" = 1 ]; then ROOT=~/navcore_ws/results/t4cal_perfeat_b1.50; else ROOT=~/navcore_ws/results/t4cal_pooled_b1.50; fi
      for cell in "${CELLS[@]}"; do
        i=$((i+1))
        read F B <<< "$cell"
        COND=sig1.000_f$(printf "%.3f" $F)_bad$(printf "%.3f" $B)
        [ -n "$np" ] && COND=${COND}_n${np}
        OUT=$ROOT/$TRAJ/$COND/seed${seed}
        if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
          echo "[$i/$TOTAL] skip (already done): mode=$mode $COND seed=$seed"; continue
        fi
        $S $TRAJ $seed 1.0 $F $B $ROOT $np 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) mode=$mode |"
        if ! grep -q "NavCore\] R mode $mode, oracle scale 1.500" "$OUT/run.log" 2>/dev/null; then
          echo "ABORT: expected mode $mode scale 1.500 not active in $OUT"; exit 1
        fi
      done
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.4 equal-calibration batch done: $(date)"
