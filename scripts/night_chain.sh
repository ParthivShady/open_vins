#!/bin/bash
# NavCore overnight chain (18 Oct): real-data calibration on MH_01, then the simulation check with independent
# camera noise (T.4e). Usage:  nohup bash scripts/night_chain.sh > ~/navcore_ws/results/night_chain.log 2>&1 &
# Each step must succeed before the next starts, and everything it runs can resume, so restarting it is safe.
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts
echo "$(date +%T) night chain started"
while pgrep -f "run_t4d_euroc.sh" > /dev/null; do sleep 60; done   # a calibration started by hand: let it finish
echo "$(date +%T) step 1: real-data calibration on MH_01 (resumes if partly done)"
bash "$S/run_t4d_euroc.sh" calib MH_01_easy 8 || echo "$(date +%T) calibration stopped early (see above); going on with the simulation"
echo "$(date +%T) step 2: simulator switch, build, controls"
cd "$OV" || exit 1
if ! grep -q NAVCORE_SIM_INDEP_CAMS ov_msckf/src/sim/Simulator.cpp; then
  python3 "$S/navcore_simindep_patch.py" || { echo "$(date +%T) patch failed: stopping"; exit 1; }
fi
cd "$WS" && MAKEFLAGS="-j1" colcon build --packages-select ov_msckf --parallel-workers 1 --executor sequential > "$WS/results/t4e_build.log" 2>&1 \
  || { echo "$(date +%T) build failed: stopping (see results/t4e_build.log)"; exit 1; }
cd "$OV" && bash "$S/run_t4e_batch.sh" 0 || { echo "$(date +%T) controls failed: stopping"; exit 1; }
echo "$(date +%T) step 3: T.4e batch, 720 runs"
bash "$S/run_t4e_batch.sh" 123 || { echo "$(date +%T) batch stopped (see above)"; exit 1; }
"$WS/.venv/bin/python" "$S/t4e_summary.py"
echo "$(date +%T) night chain finished"
