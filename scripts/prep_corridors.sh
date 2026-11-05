#!/bin/bash
# NavCore: prepare TUM-VI corridors 1-5 for the improved version's held-out test. No compared method is run here.
#   1  convert each corridor to ROS 2 (rosbags 0.9.11, format 5) on the data drive and link it into ~/euroc_data
#   2  extract its motion-capture ground truth (only at the start and end of a corridor run, in the capture room)
#   3  a trial run per corridor with a setting that is not compared (fixed 2.0 px, undithered), to confirm start-up and
#      that enough poses match the ground truth; a corridor whose trial fails will be set aside
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; D=/mnt/data/tumvi
CONV=$WS/.venv_rb09/bin/rosbags-convert; PY=$WS/.venv/bin/python
SEQS="dataset-corridor1_512_16 dataset-corridor2_512_16 dataset-corridor3_512_16 dataset-corridor4_512_16 dataset-corridor5_512_16"
echo "$(date +%T) corridor preparation started"
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
cd "$D" || exit 1
for s in $SEQS; do
  [ -s "$s.bag" ] || { echo "$s: bag not downloaded, skipped"; continue; }
  if [ ! -f "${s}_ros2/metadata.yaml" ]; then
    rm -rf "${s}_ros2"; "$CONV" "$s.bag" --dst "${s}_ros2" > /dev/null 2>&1 || { echo "$s: conversion failed"; continue; }
  fi
  ln -sfn "$D/${s}_ros2" "$HOME/euroc_data/${s}_ros2"
  "$PY" "$S/tumvi_gt.py" "$D/$s.bag" "$WS/results/gt_tumvi/$s.csv" || echo "$s: no ground truth"
done
cd "$OV" || exit 1
echo "$(date +%T) trial runs (fixed 2.0 px, undithered; not a compared setting)"
for s in $SEQS; do
  [ -f "$HOME/euroc_data/${s}_ros2/metadata.yaml" ] && [ -f "$WS/results/gt_tumvi/$s.csv" ] || continue
  out=$(DITHER=0 bash "$S/run_t4d_euroc.sh" one $s fixed2.00 0 2>&1); rc=$?
  echo "$out" | tail -1
  [ $rc = 0 ] && echo "$s: trial OK" || echo "$s: trial FAILED (will be set aside)"
done
echo "$(date +%T) corridor preparation finished"
