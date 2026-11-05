#!/bin/bash
# NavCore: the improved version (trust factor on the per-feature boost) - build, controls, development check.
#   1  patch (navcore_trust_patch.py, header only) and build
#   2  controls on MH_04 (separate folder):
#        a  with the switch off, the proposed method must reproduce its stored test run byte for byte
#        b  with it on, an unlogged run must report the trust factor moving (proves the feedback works without logging)
#   3  development check, exploratory (these sequences are not held out for the improved version): the improved
#      version with the proposed method's frozen settings on all 11 EuRoC sequences and TUM-VI rooms 1-5, 10 seeds
#   4  summary: per sequence, improved vs proposed, vs one value per image, vs tuned fixed; and the trust it settled at
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore trust" bash scripts/dev_trust.sh > ~/navcore_ws/results/dev_trust.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc_dither; N=10
PY=$WS/.venv/bin/python; CAL=$RES/calibration_MH_01_easy.txt
SEQS="MH_01_easy MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult V1_01_easy V1_02_medium V1_03_difficult V2_01_easy V2_02_medium V2_03_difficult dataset-room1_512_16 dataset-room2_512_16 dataset-room3_512_16 dataset-room4_512_16 dataset-room5_512_16"
echo "$(date +%T) improved version: build and development check started"
while pgrep -f "run_t4d_euroc.sh|run_tumvi.sh|night_all.sh" > /dev/null; do sleep 60; done   # nothing else may run
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
G=$(awk '$1 == "g1c" {print $2}' "$CAL"); P=$(awk '$1 == "pfr" {print $2}' "$CAL"); F=$(awk '$1 == "fixed" {print $2}' "$CAL")
[ -n "$G" ] && [ -n "$P" ] && [ -n "$F" ] || { echo "calibration file incomplete: stopping"; exit 1; }
B=${G#g1c_b}; B=${B%%_f*}; T="g1t_b${B}_f${G##*_f}"
echo "proposed $G -> improved $T (same multiplier and floor, nothing new tuned)"

cd "$OV" || exit 1
echo "$(date +%T) step 1: patch and build"
H=$(find ov_msckf/src -name NavcoreNoise.h | head -1)
grep -q "so wait until both groups have 20" "$H" || python3 "$S/navcore_trust_patch.py" || { echo "patch failed: stopping"; exit 1; }
cd "$WS" && MAKEFLAGS="-j1" colcon build --packages-select ov_msckf --parallel-workers 1 --executor sequential > "$WS/results/trust_build.log" 2>&1 \
  || { echo "build failed: stopping (see results/trust_build.log)"; exit 1; }
cd "$OV"

echo "$(date +%T) step 2: controls on MH_04"
C=$WS/results/t4d_euroc_ctrl_trust; rm -rf "$C"
RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "$G" 1 > /dev/null || { echo "control a run failed: stopping"; exit 1; }
if cmp -s "$C/MH_04_difficult/$G/run1/state_estimate.txt" "$RES/MH_04_difficult/$G/run1/state_estimate.txt"; then
  echo "control a PASS: switch off reproduces the stored proposed-method run exactly"
else echo "control a FAIL: the proposed method changed after the patch: stopping"; exit 1; fi
RES_ROOT=$C bash "$S/run_t4d_euroc.sh" one MH_04_difficult "$T" 1 > /dev/null || { echo "control b run failed: stopping"; exit 1; }
TL=$(zcat -f "$C/MH_04_difficult/$T/run1/run.log"* 2> /dev/null | grep "G1c trust [0-9]" | tail -1)
if [ -n "$TL" ]; then echo "control b PASS: unlogged run reports ${TL#\[NavCore\] }"
else echo "control b FAIL: no trust updates reported in an unlogged run: stopping"; exit 1; fi

echo "$(date +%T) step 3: development check, $N seeds per sequence"
for s in $SEQS; do
  [ -d "$RES/$s/$G" ] || { echo "$s: no results for the proposed method, skipped"; continue; }
  bash "$S/run_t4d_euroc.sh" sweep $s $N "$T" > "$WS/results/trust_$s.log" 2>&1 \
    && echo "$(date +%T) $s done, trust $(zcat -f "$RES/$s/$T/run0/run.log"* 2> /dev/null | grep 'G1c trust [0-9]' | tail -1 | awk '{print $4}')" \
    || echo "$(date +%T) $s stopped (see results/trust_$s.log)"
done
T4D_EUROC_RES=$RES "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/t4d_real_summary.txt" 2>&1
awk -v t="$T" -v g="$G" -v p="$P" -v f="$F" '/^== /{s=$2} ($1==t || $1==g || $1==p || $1==f) && /runs \|/ {print s": "$0} index($0, t" against "g":") || index($0, t" against "p":") || index($0, t" against "f":") {print s": "$0}' \
  "$WS/results/t4d_real_summary.txt" > "$WS/results/trust_dev_summary.txt"
echo "$(date +%T) development check finished; summary in results/trust_dev_summary.txt"
