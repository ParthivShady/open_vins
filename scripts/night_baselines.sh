#!/bin/bash
# NavCore: published adaptive baselines (predictions P47-P50 frozen in Notion first).
#   1  patch (navcore_baselines_patch.py) and build
#   2  controls on MH_04 (separate folder): the current and the improved versions must reproduce their stored runs
#      byte for byte; an unlogged Sage-Husa run must report its shared noise moving
#   3  calibration on MH_01, 10 seeds, same rule as every method: Sage-Husa forgetting factor 0.95 / 0.98 / 0.99,
#      Huber threshold 1.0 / 1.345 / 2.0, both on the tuned 0.75 px
#   4  the chosen settings on all 19 held-out sequences (EuRoC 10, TUM-VI rooms 5, corridors 1-4), 10 seeds
#   5  summary and backup
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore baselines" bash scripts/night_baselines.sh > ~/navcore_ws/results/night_baselines.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
PY=$WS/.venv/bin/python; CAL=$RES/calibration_MH_01_easy.txt
HELD="MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult V1_01_easy V1_02_medium V1_03_difficult V2_01_easy V2_02_medium V2_03_difficult dataset-room1_512_16 dataset-room2_512_16 dataset-room3_512_16 dataset-room4_512_16 dataset-room5_512_16 dataset-corridor1_512_16 dataset-corridor2_512_16 dataset-corridor3_512_16 dataset-corridor4_512_16"
echo "$(date +%T) baselines started"
while pgrep -f "run_t4d_euroc.sh|run_corridors.sh|after_corridors.sh|dev_trust.sh" > /dev/null; do sleep 60; done
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
F=$(awk '$1 == "fixed" {print $2}' "$CAL"); G=$(awk '$1 == "g1c" {print $2}' "$CAL"); SIG=${F#fixed}
B=${G#g1c_b}; B=${B%%_f*}; T="g1t_b${B}_f${G##*_f}"
[ -n "$F" ] && [ -n "$G" ] || { echo "calibration file incomplete: stopping"; exit 1; }

cd "$OV" || exit 1
echo "$(date +%T) step 1: patch and build"
grep -q msckf_feature_begin ov_msckf/src/update/UpdaterMSCKF.cpp || python3 "$S/navcore_baselines_patch.py" || { echo "patch failed: stopping"; exit 1; }
cd "$WS" && MAKEFLAGS="-j1" colcon build --packages-select ov_msckf --parallel-workers 1 --executor sequential > "$WS/results/baselines_build.log" 2>&1 \
  || { echo "build failed: stopping (see results/baselines_build.log)"; exit 1; }
cd "$OV"

echo "$(date +%T) step 2: controls on MH_04"
C=$WS/results/t4d_euroc_ctrl_baselines; rm -rf "$C"
for c in "$G" "$T"; do
  RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "$c" 1 > /dev/null || { echo "control run $c failed: stopping"; exit 1; }
  if cmp -s "$C/MH_04_difficult/$c/run1/state_estimate.txt" "$RES/MH_04_difficult/$c/run1/state_estimate.txt"; then echo "control PASS: $c unchanged"
  else echo "control FAIL: $c changed after the patch: stopping"; exit 1; fi
done
RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "iae_b0.98_f$SIG" 1 > /dev/null || { echo "control run Sage-Husa failed: stopping"; exit 1; }
IL=$(zcat -f "$C/MH_04_difficult/iae_b0.98_f$SIG/run1/run.log"* | grep -o "IAE sigma [0-9.]* px after [0-9]* updates" | tail -1)
[ -n "$IL" ] && echo "control PASS: unlogged Sage-Husa run reports $IL" || { echo "control FAIL: no Sage-Husa updates reported: stopping"; exit 1; }

echo "$(date +%T) step 3: calibration on MH_01, $N seeds"
bash "$S/run_t4d_euroc.sh" sweep MH_01_easy $N "iae_b0.95_f$SIG" "iae_b0.98_f$SIG" "iae_b0.99_f$SIG" "hub_c1.0_f$SIG" "hub_c1.345_f$SIG" "hub_c2.0_f$SIG" \
  > "$WS/results/baselines_calib.log" 2>&1 || { echo "calibration stopped: see results/baselines_calib.log"; grep -E "FAIL|STOP" "$WS/results/baselines_calib.log" | head -3; exit 1; }
PI=$(T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" pick MH_01_easy iae 2>> "$WS/results/baselines_calib.log") || { echo "no Sage-Husa choice"; exit 1; }
PH=$(T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" pick MH_01_easy hub 2>> "$WS/results/baselines_calib.log") || { echo "no Huber choice"; exit 1; }
grep -q "^iae " "$CAL" || echo "iae $PI" >> "$CAL"; grep -q "^hub " "$CAL" || echo "hub $PH" >> "$CAL"
echo "choices: $PI, $PH"; grep -E " -> " "$WS/results/baselines_calib.log"

echo "$(date +%T) step 4: held-out sequences"
for s in $HELD; do
  [ -d "$RES/$s/$T" ] || { echo "$s: no results for the improved version, skipped"; continue; }
  bash "$S/run_t4d_euroc.sh" sweep $s $N "$PI" "$PH" > "$WS/results/baselines_$s.log" 2>&1 && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/baselines_$s.log)"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
awk -v t="$T" -v a="$PI" -v b="$PH" '/^== /{s=$2} ($1 == a || $1 == b || $1 == t) && /runs \|/ {print s": "$0} index($0, t" against "a":") || index($0, t" against "b":") {print s": "$0}' \
  "$WS/results/t4d_real_summary.txt" > "$WS/results/t4d_baselines_summary.txt"
mkdir -p /mnt/data/navcore_backup && cp -a "$RES" /mnt/data/navcore_backup/ 2> /dev/null
echo "$(date +%T) baselines finished; summary in results/t4d_baselines_summary.txt (results backed up)"
