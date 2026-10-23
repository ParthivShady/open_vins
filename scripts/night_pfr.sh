#!/bin/bash
# NavCore overnight 23 Oct: per-feature vs per-frame on real data, plus an exploratory fixed 2.0 px run.
#   waits for the Vicon test to finish, then
#   1  adds the per-frame switch (navcore_pfr_patch.py), builds, and runs two controls:
#        G1c with the switch off must reproduce a stored MH_04 test run byte for byte; the per-frame run must differ
#   2  calibrates the per-frame version on MH_01 like G1c was: multiplier 0.5 / 1.0 / 1.5 on G1c's floor, same rule
#   3  runs the chosen per-frame setting on every held-out sequence that has G1c test results (10 seeds each)
#   4  exploratory, no prediction: fixed 2.0 px on MH_04 and MH_05 (10 seeds each)
# Usage:  nohup bash scripts/night_pfr.sh > ~/navcore_ws/results/night_pfr.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
echo "$(date +%T) per-frame night started"
while pgrep -f "run_t4d_euroc.sh" > /dev/null; do sleep 60; done   # let the Vicon test finish first
cd "$OV" || exit 1
echo "$(date +%T) step 1: per-frame switch, build, controls"
H=$(find ov_msckf/src -name NavcoreNoise.h | head -1)
grep -q NAVCORE_G1C_PERFRAME "$H" || python3 "$S/navcore_pfr_patch.py" || { echo "patch failed: stopping"; exit 1; }
cd "$WS" && MAKEFLAGS="-j1" colcon build --packages-select ov_msckf --parallel-workers 1 --executor sequential > "$WS/results/pfr_build.log" 2>&1 \
  || { echo "build failed: stopping (see results/pfr_build.log)"; exit 1; }
cd "$OV"
G=$(awk '$1 == "g1c" {print $2}' "$RES/calibration_MH_01_easy.txt"); F=${G##*_f}   # G1c's calibrated setting and its floor
[ -n "$G" ] && [ -n "$F" ] || { echo "no G1c choice in the calibration file: stopping"; exit 1; }
C=$WS/results/t4d_euroc_ctrl; rm -rf "$C"
RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "$G" 1 > /dev/null || { echo "control 1 run failed: stopping"; exit 1; }
if cmp -s "$C/MH_04_difficult/$G/run1/state_estimate.txt" "$RES/MH_04_difficult/$G/run1/state_estimate.txt"; then
  echo "control 1 PASS: G1c with the switch off reproduces the MH_04 test run exactly"
else echo "control 1 FAIL: G1c changed after the patch: stopping"; exit 1; fi
for r in 0 1; do RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "pfr_b1.5_f$F" $r > /dev/null || { echo "control 2 run $r failed: stopping"; exit 1; }; done
if cmp -s "$C/MH_04_difficult/pfr_b1.5_f$F/run1/state_estimate.txt" "$C/MH_04_difficult/$G/run1/state_estimate.txt"; then
  echo "control 2 FAIL: the per-frame version gives the same result as G1c: stopping"; exit 1
else echo "control 2 PASS: per-frame run checked (one value per frame) and different from G1c"; fi
echo "$(date +%T) step 2: per-frame calibration on MH_01, $N seeds"
bash "$S/run_t4d_euroc.sh" sweep MH_01_easy $N "pfr_b0.5_f$F" "pfr_b1.0_f$F" "pfr_b1.5_f$F" > "$WS/results/pfr_calib.log" 2>&1 \
  || { echo "calibration stopped: see results/pfr_calib.log"; exit 1; }
P=$(T4D_EUROC_RES=$RES "$WS/.venv/bin/python" "$S/t4d_euroc_eval.py" pick MH_01_easy pfr 2>> "$WS/results/pfr_calib.log") || { echo "no per-frame choice"; exit 1; }
grep -q "^pfr " "$RES/calibration_MH_01_easy.txt" || echo "pfr $P" >> "$RES/calibration_MH_01_easy.txt"
echo "per-frame choice: $P"; tail -1 "$WS/results/pfr_calib.log"
echo "$(date +%T) step 3: per-frame on the held-out sequences"
for s in MH_04_difficult MH_05_difficult V1_01_easy V1_03_difficult V2_03_difficult; do
  [ -d "$RES/$s/$G" ] || { echo "$s: no G1c test results, skipped"; continue; }
  bash "$S/run_t4d_euroc.sh" sweep $s $N "$P" > "$WS/results/pfr_$s.log" 2>&1 && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/pfr_$s.log)"
done
echo "$(date +%T) step 4 (exploratory): fixed 2.0 px on MH_04 and MH_05"
for s in MH_04_difficult MH_05_difficult; do
  bash "$S/run_t4d_euroc.sh" sweep $s $N fixed2.00 > "$WS/results/fixed2_$s.log" 2>&1 && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped"
done
T4D_EUROC_RES=$RES "$WS/.venv/bin/python" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
echo "$(date +%T) per-frame night finished; summary in results/t4d_real_summary.txt"
