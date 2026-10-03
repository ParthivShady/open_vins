#!/bin/bash
# T.3a trajectory disqualification screen — run stereo baseline (sigma=1.0)
# on candidate trajectories and print elapsed time + final metrics per run.
# Disqualification bar: ATE RMSE > 0.1 m.
set -e
CANDIDATES=(udel_neighborhood udel_gore_zupt tum_corridor1_512_16_okvis)
SCREEN_LOG=~/navcore_ws/results/t3a_screen_summary.log
mkdir -p ~/navcore_ws/results
: > "$SCREEN_LOG"
echo "=== T.3a trajectory disqualification screen ===" | tee -a "$SCREEN_LOG"
echo "Date: $(date -Iseconds)"                          | tee -a "$SCREEN_LOG"
echo "Bar: baseline ATE RMSE > 0.1 m => DISQUALIFIED"   | tee -a "$SCREEN_LOG"
echo ""                                                 | tee -a "$SCREEN_LOG"
for TRAJ in "${CANDIDATES[@]}"; do
  echo "--- Running: $TRAJ ---" | tee -a "$SCREEN_LOG"
  START=$(date +%s)
  ~/navcore_ws/src/open_vins/scripts/run_t2_baseline.sh "$TRAJ" > /dev/null 2>&1 || {
    echo "  RUN FAILED for $TRAJ (see ~/navcore_ws/results/t2_baseline/$TRAJ/run.log)" | tee -a "$SCREEN_LOG"
    continue
  }
  END=$(date +%s)
  ELAPSED=$((END - START))
  # Extract the final rmse line from OpenVINS log
  METRICS=$(grep "rmse =>" ~/navcore_ws/results/t2_baseline/$TRAJ/run.log | tail -1)
  echo "  elapsed: ${ELAPSED}s"     | tee -a "$SCREEN_LOG"
  echo "  ${METRICS}"               | tee -a "$SCREEN_LOG"
  echo ""                           | tee -a "$SCREEN_LOG"
done
echo "=== Screen complete. Full log: $SCREEN_LOG ==="
