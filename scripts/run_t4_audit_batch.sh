#!/bin/bash
# Audit follow-up batch (11 Oct 2026). Predictions written in the Notion roadmap before running.
# Part 1: beta 1.75 / 2.0 at uniform sigma 2 (per-feature oracle, udel_gore, 250 pts), 60 runs -> t4c_uniform_sig2_beta{1.75,2.00}
# Part 2: P7b on udel_arl: fixed / pooled@1.5 / per-feature@1.5, f 0.5, sigma_bad 1.25/1.5/2.5, 250 pts, 270 runs -> t4val_*
# Part 3: tuned fixed (sigma0 1.5): T.3b grid (360) + held-out zupt, tum, arl (270) = 630 -> t4tf_t3bgrid, t4tf_val
# Part 4: tuned fixed on the uniform sweep, cells mirrored from t4a_uniform (540) -> t4tf_uniform
# Usage: scripts/run_t4_audit_batch.sh [parts, default 123]. DRYRUN=1 counts runs only. Resumable.
# Aborts on < 2 GB free, a missing elapsed_s line, or a log that does not show the expected mode / override.
PARTS=${1:-123}
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
RES=~/navcore_ws/results
HELD=(udel_gore_zupt tum_corridor1_512_16_okvis udel_arl)
CELLS=("0.25 1.25" "0.25 1.5" "0.25 2.5" "0.5 1.25" "0.5 1.5" "0.5 2.5")
SB=(1.25 1.5 2.5)
NS=30
i=0
run_one() {  # root traj seed sig f bad npts mode scale tuned
  local root=$1 traj=$2 seed=$3 sig=$4 f=$5 b=$6 np=$7 mode=$8 scale=$9 tuned=${10}
  i=$((i+1))
  local c=sig$(printf "%.3f" $sig)_f$(printf "%.3f" $f)_bad$(printf "%.3f" $b)
  [ -n "$np" ] && c=${c}_n${np}
  local out=$root/$traj/$c/seed$seed
  [ "${DRYRUN:-0}" = 1 ] && return
  if grep -q "^elapsed_s=" "$out/run.log" 2>/dev/null; then echo "[$i] skip (done): $out"; return; fi
  if [ "$(df --output=avail -k ~ | tail -1)" -lt 2097152 ]; then echo "ABORT: under 2 GB free"; exit 1; fi
  unset NAVCORE_R_MODE NAVCORE_ORACLE_SCALE NAVCORE_FILTER_SIGMA
  [ "$mode" != 0 ] && export NAVCORE_R_MODE=$mode NAVCORE_ORACLE_SCALE=$scale
  [ "$tuned" = 1 ] && export NAVCORE_FILTER_SIGMA=1.5
  $S $traj $seed $sig $f $b $root $np 2>&1 | sed "s|^|[$i] $(date +%H:%M) |"
  grep -q "^elapsed_s=" "$out/run.log" || { echo "ABORT: no elapsed_s in $out"; exit 1; }
  if [ "$mode" != 0 ]; then
    grep -q "NavCore\] R mode $mode, oracle scale $(printf "%.3f" $scale)" "$out/run.log" \
      || { echo "ABORT: mode $mode scale $scale not active in $out"; exit 1; }
  elif grep -q "R mode [12]" "$out/run.log"; then echo "ABORT: oracle mode active in $out"; exit 1; fi
  if [ "$tuned" = 1 ]; then
    { grep -q "filter sigma override 1.500" "$out/run.log" && grep -q "overriding node up_msckf_sigma_px" "$out/run.log"; } \
      || { echo "ABORT: override not active in $out"; exit 1; }
  elif grep -q "filter sigma override" "$out/run.log"; then echo "ABORT: unexpected override in $out"; exit 1; fi
}
UNI=()
for d in $RES/t4a_uniform/*/*/; do
  traj=$(basename "$(dirname "$d")"); c=$(basename "$d")
  [[ $c =~ ^sig([0-9.]+)_f([0-9.]+)_bad(-?[0-9.]+)$ ]] && UNI+=("$traj ${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}")
done
[ -f ~/navcore_ws/src/open_vins/ov_data/sim/udel_arl.txt ] || { echo "ABORT: udel_arl.txt not found"; exit 1; }
[ "${DRYRUN:-0}" = 1 ] || echo "Audit batch start: $(date) | parts $PARTS"
for seed in $(seq 1 $NS); do
  if [[ $PARTS == *1* ]]; then
    for be in 1.75 2.0; do run_one $RES/t4c_uniform_sig2_beta$(printf "%.2f" $be) udel_gore $seed 2.0 0 2.0 "" 1 $be 0; done
  fi
  if [[ $PARTS == *2* ]]; then
    for b in "${SB[@]}"; do
      run_one $RES/t4val_fixed udel_arl $seed 1.0 0.5 $b "" 0 1 0
      run_one $RES/t4val_pooled_b1.50 udel_arl $seed 1.0 0.5 $b "" 2 1.5 0
      run_one $RES/t4val_perfeat_b1.50 udel_arl $seed 1.0 0.5 $b "" 1 1.5 0
    done
  fi
  if [[ $PARTS == *3* ]]; then
    for np in "" 60; do for cell in "${CELLS[@]}"; do read F B <<< "$cell"; run_one $RES/t4tf_t3bgrid udel_gore $seed 1.0 $F $B "$np" 0 1 1; done; done
    for tr in "${HELD[@]}"; do for b in "${SB[@]}"; do run_one $RES/t4tf_val $tr $seed 1.0 0.5 $b "" 0 1 1; done; done
  fi
  if [[ $PARTS == *4* ]]; then
    for u in "${UNI[@]}"; do read tr sg f b <<< "$u"; run_one $RES/t4tf_uniform $tr $seed $sg $f $b "" 0 1 1; done
  fi
  [ "${DRYRUN:-0}" = 1 ] || echo "=== seed $seed finished: $(date +%H:%M) ==="
done
echo "Audit batch: $i runs, parts $PARTS"
[ "${DRYRUN:-0}" = 1 ] || echo "Audit batch done: $(date)"
