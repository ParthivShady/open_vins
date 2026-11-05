#!/bin/bash
# NavCore: second-dataset test on TUM-VI rooms 1-5 (predictions P38-P41 in Notion), every setting frozen from EuRoC MH_01.
#   Rooms 1-5 at 512x512, as in OpenVINS's own TUM-VI script (room 6 is left out there too: it needs a different
#   start-up threshold). OpenVINS's TUM-VI config is used unchanged; only the compared noise settings differ.
#   waits for the TUM-VI downloads and any running EuRoC job, then
#   1  converts each room to ROS 2 (rosbags 0.9.11, format 5) on the data drive, links it into ~/euroc_data, and
#      extracts its motion-capture ground truth (tumvi_gt.py)
#   2  a trial run per room (fixed 2.0 px, undithered, not a compared setting); a room whose trial fails is set aside
#   3  per room, 10 seeds: default 1.0 px, tuned fixed, proposed, one value per image, and fixed with the gate widened 2x
#   4  summary
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore TUM-VI" bash scripts/run_tumvi.sh > ~/navcore_ws/results/tumvi.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
D=${TUMVI_DIR:-/mnt/data/tumvi}; CONV=$WS/.venv_rb09/bin/rosbags-convert; PY=$WS/.venv/bin/python; CAL=$RES/calibration_MH_01_easy.txt
SEQS="dataset-room1_512_16 dataset-room2_512_16 dataset-room3_512_16 dataset-room4_512_16 dataset-room5_512_16"
echo "$(date +%T) TUM-VI test started"
case $D in /mnt/data/*) mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; } ;; esac
while pgrep -f "tumvi/calibrated|run_t4d_euroc.sh" > /dev/null; do sleep 60; done   # downloads and EuRoC jobs first
F=$(awk '$1 == "fixed" {print $2}' "$CAL"); G=$(awk '$1 == "g1c" {print $2}' "$CAL"); P=$(awk '$1 == "pfr" {print $2}' "$CAL")
[ -n "$F" ] && [ -n "$G" ] && [ -n "$P" ] || { echo "calibration file incomplete (fixed, g1c, pfr): stopping"; exit 1; }
W="gate2_f${F#fixed}"
echo "frozen settings: $F, $G, $P, $W (and the default fixed1.00)"
echo "$(date +%T) step 1: convert and extract ground truth"
cd "$D" || exit 1
for s in $SEQS; do
  [ -s "$s.bag" ] || { echo "$s: bag not downloaded, skipped"; continue; }
  if [ ! -f "${s}_ros2/metadata.yaml" ]; then
    rm -rf "${s}_ros2"; "$CONV" "$s.bag" --dst "${s}_ros2" > /dev/null 2>&1 || { echo "$s: conversion failed"; continue; }
  fi
  ln -sfn "$D/${s}_ros2" "$HOME/euroc_data/${s}_ros2"
  "$PY" "$S/tumvi_gt.py" "$D/$s.bag" "$WS/results/gt_tumvi/$s.csv" || { echo "$s: no ground truth, skipped"; continue; }
done
cd "$OV" || exit 1
echo "$(date +%T) step 2: trial runs"
OK=""
for s in $SEQS; do
  [ -f "$HOME/euroc_data/${s}_ros2/metadata.yaml" ] && [ -f "$WS/results/gt_tumvi/$s.csv" ] || continue
  out=$(DITHER=0 bash "$S/run_t4d_euroc.sh" one $s fixed2.00 0 2>&1); rc=$?
  echo "$out" | tail -1
  if [ $rc = 0 ]; then OK="$OK $s"; else echo "$s: trial failed, set aside"; fi
done
echo "$(date +%T) step 3: frozen test on:$OK"
for s in $OK; do
  { bash "$S/run_t4d_euroc.sh" test $s $N && bash "$S/run_t4d_euroc.sh" sweep $s $N "$P" "$W"; } > "$WS/results/tumvi_$s.log" 2>&1 \
    && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/tumvi_$s.log)"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
sed -n '/^== dataset-room/,/^== [^d]/p' "$WS/results/t4d_real_summary.txt" > "$WS/results/t4d_tumvi_summary.txt"
echo "$(date +%T) TUM-VI test finished; summary in results/t4d_tumvi_summary.txt"
