#!/bin/bash
# NavCore: held-out test of the improved version on TUM-VI corridors 1-4 (predictions P42-P46 frozen in Notion first).
#   Corridor 5 is set aside: its trial run never started up (no state written) with OpenVINS's TUM-VI config, as the
#   pre-declared rule says; nothing is tuned per corridor. Ground truth exists only at the start and end of each run.
#   Per corridor, 10 seeds: default 1.0 px, tuned fixed, current version, improved version, one value per image.
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore corridors" bash scripts/run_corridors.sh > ~/navcore_ws/results/corridors.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
PY=$WS/.venv/bin/python; CAL=$RES/calibration_MH_01_easy.txt
SEQS="dataset-corridor1_512_16 dataset-corridor2_512_16 dataset-corridor3_512_16 dataset-corridor4_512_16"
echo "$(date +%T) corridor test started"
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
while pgrep -f "run_t4d_euroc.sh|dev_trust.sh|night_trust.sh" > /dev/null; do sleep 60; done
G=$(awk '$1 == "g1c" {print $2}' "$CAL"); P=$(awk '$1 == "pfr" {print $2}' "$CAL"); F=$(awk '$1 == "fixed" {print $2}' "$CAL")
[ -n "$G" ] && [ -n "$P" ] && [ -n "$F" ] || { echo "calibration file incomplete: stopping"; exit 1; }
B=${G#g1c_b}; B=${B%%_f*}; T="g1t_b${B}_f${G##*_f}"
grep -q "so wait until both groups have 20" "$(find "$OV/ov_msckf/src" -name NavcoreNoise.h | head -1)" || { echo "the improved version is not in the build: stopping"; exit 1; }
echo "frozen settings: default fixed1.00, $F, $G, $T, $P"
cd "$OV" || exit 1
for s in $SEQS; do
  [ -f "$HOME/euroc_data/${s}_ros2/metadata.yaml" ] && [ -f "$WS/results/gt_tumvi/$s.csv" ] || { echo "$s: not prepared, skipped"; continue; }
  { bash "$S/run_t4d_euroc.sh" test $s $N && bash "$S/run_t4d_euroc.sh" sweep $s $N "$T" "$P"; } > "$WS/results/corridor_$s.log" 2>&1 \
    && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/corridor_$s.log)"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
awk -v t="$T" '/^== /{s=$2} s ~ /corridor/ && /runs \|/ {print s": "$0} s ~ /corridor/ && index($0, t" against ") {print s": "$0}' "$WS/results/t4d_real_summary.txt" > "$WS/results/t4d_corridor_summary.txt"
mkdir -p /mnt/data/navcore_backup && cp -a "$RES" /mnt/data/navcore_backup/ 2> /dev/null
echo "$(date +%T) corridor test finished; summary in results/t4d_corridor_summary.txt (results backed up)"
