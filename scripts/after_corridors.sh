#!/bin/bash
# NavCore: queued after the corridor test (exploratory, no predictions).
#   1  baseline: tuned fixed noise with the gate widened 2x on corridors 1-4, 10 seeds              about 1.2 h
#   2  compute cost: each method 3 times on MH_01 (unlogged, separate folder), wall-clock and CPU time  about 12 min
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore extra" bash scripts/after_corridors.sh > ~/navcore_ws/results/after_corridors.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10; PY=$WS/.venv/bin/python
CAL=$RES/calibration_MH_01_easy.txt
echo "$(date +%T) queued work started; waiting for the corridor test"
while pgrep -f "run_corridors.sh|run_t4d_euroc.sh" > /dev/null; do sleep 60; done
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
F=$(awk '$1 == "fixed" {print $2}' "$CAL"); G=$(awk '$1 == "g1c" {print $2}' "$CAL"); P=$(awk '$1 == "pfr" {print $2}' "$CAL")
B=${G#g1c_b}; B=${B%%_f*}; T="g1t_b${B}_f${G##*_f}"; W="gate2_f${F#fixed}"
cd "$OV" || exit 1
echo "$(date +%T) step 1: $W on corridors 1-4"
for s in dataset-corridor1_512_16 dataset-corridor2_512_16 dataset-corridor3_512_16 dataset-corridor4_512_16; do
  [ -d "$RES/$s/$G" ] || { echo "$s: no corridor test results, skipped"; continue; }
  bash "$S/run_t4d_euroc.sh" sweep $s $N "$W" > "$WS/results/corridor_gate_$s.log" 2>&1 && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
awk -v t="$T" '/^== /{s=$2} s ~ /corridor/ && /runs \|/ {print s": "$0} s ~ /corridor/ && index($0, t" against ") {print s": "$0}' "$WS/results/t4d_real_summary.txt" > "$WS/results/t4d_corridor_summary.txt"
echo "$(date +%T) step 2: compute cost on MH_01 (3 unlogged runs per method)"
C=$WS/results/t4d_timing; rm -rf "$C" "$C.txt"; TIMEFORMAT='%R %U %S'
for c in fixed1.00 "$F" "$P" "$G" "$T"; do
  for r in 1 2 3; do
    t=$( { time RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_01_easy "$c" $r > /dev/null 2>&1; } 2>&1 )
    echo "$c $r $t" >> "$C.txt"
  done
done
awk '{w[$1] += $3; u[$1] += $4 + $5; n[$1]++} END {for (c in w) printf "  %-16s wall %.1f s, CPU %.1f s per run (mean of %d)\n", c, w[c] / n[c], u[c] / n[c], n[c]}' "$C.txt" | sort
echo "(MH_01 has about 3680 stereo frames; divide by it for time per frame)"
cp -a "$RES" /mnt/data/navcore_backup/ 2> /dev/null
echo "$(date +%T) queued work finished"
