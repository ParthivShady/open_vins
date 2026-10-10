#!/bin/bash
# T.4 validation on held-out trajectories. beta* = 1.5 was calibrated on udel_gore; test P5 on udel_gore_zupt and tum_corridor.
# Prediction (written before running): per-feature@1.5 beats pooled@1.5; gap largest at sigma_bad 2.5.
# 2 trajectories x 3 cells (f=0.5, sigma_bad 1.25/1.5/2.5, 250 pts) x 3 methods x 30 seeds = 540 runs.
# Methods: fixed (stock, no NavCore mode), pooled@1.5 (mode 2), per-feature@1.5 (mode 1). Resumable; aborts on a wrong mode.
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
TRAJS=(udel_gore_zupt tum_corridor1_512_16_okvis)
CELLS=("0.5 1.25" "0.5 1.5" "0.5 2.5")
METHODS=(fixed pooled perfeat)
NSEEDS=30
TOTAL=$(( ${#TRAJS[@]} * ${#CELLS[@]} * ${#METHODS[@]} * NSEEDS ))
i=0; T0=$(date +%s)
echo "T.4 validation batch start: $(date) | $TOTAL runs"
for seed in $(seq 1 $NSEEDS); do
  for traj in "${TRAJS[@]}"; do
    for method in "${METHODS[@]}"; do
      case $method in
        fixed)   unset NAVCORE_R_MODE NAVCORE_ORACLE_SCALE; ROOT=~/navcore_ws/results/t4val_fixed; WANT="" ;;
        pooled)  export NAVCORE_R_MODE=2 NAVCORE_ORACLE_SCALE=1.5; ROOT=~/navcore_ws/results/t4val_pooled_b1.50; WANT="R mode 2, oracle scale 1.500" ;;
        perfeat) export NAVCORE_R_MODE=1 NAVCORE_ORACLE_SCALE=1.5; ROOT=~/navcore_ws/results/t4val_perfeat_b1.50; WANT="R mode 1, oracle scale 1.500" ;;
      esac
      for cell in "${CELLS[@]}"; do
        i=$((i+1))
        read F B <<< "$cell"
        COND=sig1.000_f$(printf "%.3f" $F)_bad$(printf "%.3f" $B)
        OUT=$ROOT/$traj/$COND/seed${seed}
        if grep -q "^elapsed_s=" "$OUT/run.log" 2>/dev/null; then
          echo "[$i/$TOTAL] skip (already done): $method $traj $COND seed=$seed"; continue
        fi
        $S $traj $seed 1.0 $F $B $ROOT 2>&1 | sed "s|^|[$i/$TOTAL] $(date +%H:%M) $method |"
        if [ -z "$WANT" ]; then
          if grep -q "NavCore\] R mode" "$OUT/run.log" 2>/dev/null; then echo "ABORT: fixed run shows a NavCore mode in $OUT"; exit 1; fi
        elif ! grep -q "NavCore\] $WANT" "$OUT/run.log" 2>/dev/null; then
          echo "ABORT: expected '$WANT' not found in $OUT"; exit 1
        fi
      done
    done
  done
  echo "=== seed $seed finished: $(date +%H:%M), $(( ($(date +%s) - T0) / 60 )) min elapsed ==="
done
echo "T.4 validation batch done: $(date)"
