#!/bin/bash
# NavCore 24 Oct: does widening the chi-square gate rescue fixed noise? (predictions P35-P37 in Notion)
#   waits for night_more.sh (the five extra sequences) to finish, then
#   1  control: gate widening 1 must reproduce the tuned fixed-noise run on MH_01 byte for byte
#      (proves the setting reaches OpenVINS and that 1 is the EuRoC default)
#   2  calibration on MH_01 (10 seeds): tuned fixed noise with the gate widened 1 / 2 / 5 / 10 times, pick rule as
#      before (lowest median; within 2% the smallest widening)
#   3  widenings 2 / 5 / 10 on every held-out sequence with test results (10 seeds); widening 1 is the existing fixed run
#   4  summary over all sequences
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore gate" bash scripts/night_gate.sh > ~/navcore_ws/results/night_gate.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
PY=$WS/.venv/bin/python; CAL=$RES/calibration_MH_01_easy.txt
HELD="MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult V1_01_easy V1_02_medium V1_03_difficult V2_01_easy V2_02_medium V2_03_difficult"
echo "$(date +%T) gate study started"
while pgrep -f "night_more.sh|run_t4d_euroc.sh" > /dev/null; do sleep 60; done   # let the five-sequence run finish first
cd "$OV" || exit 1
F=$(awk '$1 == "fixed" {print $2}' "$CAL"); G1C=$(awk '$1 == "g1c" {print $2}' "$CAL"); SIG=${F#fixed}
[ -n "$F" ] && [ -n "$G1C" ] || { echo "calibration file incomplete: stopping"; exit 1; }
echo "$(date +%T) step 1: control (gate widening 1 = $F)"
C=$WS/results/t4d_euroc_ctrl_gate; rm -rf "$C"
RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_01_easy "gate1_f$SIG" 1 > /dev/null || { echo "control run failed: stopping"; exit 1; }
if cmp -s "$C/MH_01_easy/gate1_f$SIG/run1/state_estimate.txt" "$RES/MH_01_easy/$F/run1/state_estimate.txt"; then
  echo "control PASS: widening 1 reproduces $F exactly"
else echo "control FAIL: widening 1 differs from $F (default not 1, or the setting changes something else): stopping"; exit 1; fi
echo "$(date +%T) step 2: calibration of the gate widening on MH_01, $N seeds"
bash "$S/run_t4d_euroc.sh" sweep MH_01_easy $N "gate1_f$SIG" "gate2_f$SIG" "gate5_f$SIG" "gate10_f$SIG" > "$WS/results/gate_calib.log" 2>&1 \
  || { echo "calibration stopped: see results/gate_calib.log"; grep -E "FAIL|STOP|gate check" "$WS/results/gate_calib.log" | head -5; exit 1; }
grep "gate check" "$WS/results/gate_calib.log" | head -4
P=$(T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" pick MH_01_easy gate 2>> "$WS/results/gate_calib.log") || { echo "no gate choice"; exit 1; }
grep -q "^gate " "$CAL" || echo "gate $P" >> "$CAL"
echo "gate choice: $P"; tail -1 "$WS/results/gate_calib.log"
echo "$(date +%T) step 3: widenings 2 / 5 / 10 on the held-out sequences"
for s in $HELD; do
  [ -d "$RES/$s/$G1C" ] || { echo "$s: no test results, skipped"; continue; }
  bash "$S/run_t4d_euroc.sh" sweep $s $N "gate2_f$SIG" "gate5_f$SIG" "gate10_f$SIG" > "$WS/results/gate_$s.log" 2>&1 \
    && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/gate_$s.log)"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
echo "$(date +%T) gate study finished; summary in results/t4d_real_summary.txt"
