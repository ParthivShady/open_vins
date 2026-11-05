#!/bin/bash
# NavCore overnight queue: the improved version's build, controls and development check, then corridor preparation.
#   1  dev_trust.sh: patch, build, controls a and b, exploratory check on EuRoC (11) and TUM-VI rooms (5)   about 2.5 h
#   2  prep_corridors.sh: convert, ground truth, trial runs for TUM-VI corridors 1-5 (nothing compared)     about 1 h
#   3  results backed up to /mnt/data/navcore_backup
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore night" bash scripts/night_trust.sh > ~/navcore_ws/results/night_trust.log 2>&1 &
set -u
WS=$HOME/navcore_ws; S=$WS/src/open_vins/scripts
echo "$(date +%T) night queue started"
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
bash "$S/dev_trust.sh" > "$WS/results/dev_trust.log" 2>&1; echo "$(date +%T) step 1 exit status $?"; tail -3 "$WS/results/dev_trust.log"
bash "$S/prep_corridors.sh" > "$WS/results/prep_corridors.log" 2>&1; echo "$(date +%T) step 2 exit status $?"
mkdir -p /mnt/data/navcore_backup && cp -a "$WS/results/t4d_euroc_dither" "$WS/results/gt_tumvi" "$WS/results/t4d_real_summary.txt" /mnt/data/navcore_backup/ 2> /dev/null
echo "$(date +%T) night queue finished (results backed up)"
