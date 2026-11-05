#!/bin/bash
# NavCore overnight 24 Oct: the five remaining EuRoC sequences as further held-out tests, settings frozen from MH_01.
#   1  unpacks MH_02, MH_03 (machine hall), V1_02 (vicon room 1), V2_01, V2_02 (vicon room 2) onto the data drive,
#      converts them with rosbags 0.9.11 (format 5, as Humble needs) and links them into ~/euroc_data
#   2  a trial run per sequence (fixed 2.0 px, undithered, not a compared setting); a sequence whose trial fails is skipped
#   3  per sequence: the frozen test (stock 1.0 px, calibrated fixed, G1c; 10 seeds) and the frozen per-frame setting
#   4  a summary over every sequence
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore night" bash scripts/night_more.sh > ~/navcore_ws/results/night_more.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10; D=${EUROC_DIR:-/mnt/data/euroc}
CONV=$WS/.venv_rb09/bin/rosbags-convert
SEQS="MH_02_easy MH_03_medium V1_02_medium V2_01_easy V2_02_medium"
echo "$(date +%T) night (five more sequences) started"
case $D in /mnt/data/*) mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; } ;; esac
P=$(awk '$1 == "pfr" {print $2}' "$RES/calibration_MH_01_easy.txt"); [ -n "$P" ] || { echo "no per-frame choice in the calibration file: stopping"; exit 1; }
echo "$(date +%T) step 1: unpack and convert"
cd "$D" || exit 1
for s in $SEQS; do
  case $s in MH_*) z=machine_hall.zip ;; V1_*) z=vicon_room1.zip ;; V2_*) z=vicon_room2.zip ;; esac
  if [ ! -f "${s}_ros2/metadata.yaml" ]; then
    [ -f "$s.bag" ] || unzip -o -q -j "$z" "*/$s.bag" -d . || { echo "$s: not found in $z"; continue; }
    rm -rf "${s}_ros2"; "$CONV" "$s.bag" --dst "${s}_ros2" > /dev/null 2>&1 || { echo "$s: conversion failed"; continue; }
  fi
  ln -sfn "$D/${s}_ros2" "$HOME/euroc_data/${s}_ros2"
  printf "%s: format %s, %s\n" "$s" "$(grep -m1 'version:' ${s}_ros2/metadata.yaml | awk '{print $2}')" "$(ros2 bag info "$HOME/euroc_data/${s}_ros2" 2>&1 | grep -m1 Duration | tr -s ' ')"
done
cd "$OV" || exit 1
echo "$(date +%T) step 2: trial runs"
OK=""
for s in $SEQS; do
  [ -f "$HOME/euroc_data/${s}_ros2/metadata.yaml" ] || continue
  out=$(DITHER=0 bash "$S/run_t4d_euroc.sh" one $s fixed2.00 0 2>&1); rc=$?
  echo "$out" | tail -1
  if [ $rc = 0 ]; then OK="$OK $s"; else echo "$s: trial failed, skipped"; fi
done
echo "$(date +%T) step 3: frozen tests on:$OK"
for s in $OK; do
  { bash "$S/run_t4d_euroc.sh" test $s $N && bash "$S/run_t4d_euroc.sh" sweep $s $N "$P"; } > "$WS/results/more_$s.log" 2>&1 \
    && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped (see results/more_$s.log)"
done
T4D_EUROC_RES=$RES "$WS/.venv/bin/python" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
echo "$(date +%T) night finished; summary in results/t4d_real_summary.txt"
