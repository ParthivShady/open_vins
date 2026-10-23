#!/bin/bash
# NavCore overnight 19 Oct. Step 1: Monte Carlo calibration on MH_01 (10 dither seeds per setting; resumes, or waits for
# a calibration already running). Step 2, exploratory (no prediction): how the noise setting changes real-data accuracy,
# 10 seeds each: fixed 0.40 / 0.50 / 0.60 / 2.00 / 3.00 px, and G1c with the calibrated multiplier on floors
# 0.40 / 0.50 / 0.60 px, i.e. whether a floor set too low breaks G1c the way it breaks a fixed setting.
# Usage:  nohup bash scripts/night_sweep.sh > ~/navcore_ws/results/night_sweep.log 2>&1 &
set -u
WS=$HOME/navcore_ws; S=$WS/src/open_vins/scripts; RES=$WS/results/t4d_euroc_dither; N=10
echo "$(date +%T) night sweep started"
while pgrep -f "run_t4d_euroc.sh calib" > /dev/null; do sleep 60; done
cd "$WS/src/open_vins" || exit 1
echo "$(date +%T) step 1: calibration on MH_01, $N seeds per setting"
bash "$S/run_t4d_euroc.sh" calib MH_01_easy $N || { echo "$(date +%T) calibration stopped: no sweep"; exit 1; }
B=$(awk '$1 == "g1c" {print $2}' "$RES/calibration_MH_01_easy.txt" | sed 's/^g1c_b\([0-9.]*\)_f.*/\1/')
[ -n "$B" ] || { echo "no G1c choice in the calibration file: no sweep"; exit 1; }
echo "$(date +%T) step 2: sweep, G1c multiplier $B"
# one configuration at a time, so a setting that stops (e.g. OpenVINS failing outright at a very low noise value)
# does not keep the others from running
for c in fixed0.40 fixed0.50 fixed0.60 fixed2.00 fixed3.00 "g1c_b${B}_f0.40" "g1c_b${B}_f0.50" "g1c_b${B}_f0.60"; do
  bash "$S/run_t4d_euroc.sh" sweep MH_01_easy $N "$c" > "$WS/results/t4d_sweep_$c.log" 2>&1 \
    && echo "$(date +%T) $c done" || { echo "$(date +%T) $c stopped:"; grep -E "STOP|FAIL" "$WS/results/t4d_sweep_$c.log"; }
done
T4D_EUROC_RES=$RES "$WS/.venv/bin/python" "$S/t4d_euroc_eval.py" summary MH_01_easy > "$WS/results/t4d_sweep_summary.txt" 2>&1
grep "runs |" "$WS/results/t4d_sweep_summary.txt"
echo "$(date +%T) night sweep finished"
