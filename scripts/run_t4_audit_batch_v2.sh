#!/bin/bash
# Audit follow-up batch, v2 (13 Oct 2026). Replaces run_t4_audit_batch.sh, which aborted on its own log check.
# Changes from v1:
#  (1) every run is verified from what the filter actually used (sigma_used in gate_feat.csv + gate_slam.csv, all rows),
#      plus the plain [NavCore] lines; no check reads colour-coded ROS log text. Finished runs are verified on every launch.
#  (2) udel_arl replaced by euroc_V1_01_easy (udel_arl: 101 MB and 6.5 min per run, ~39 h for its 360 runs; cost only,
#      decided before any udel_arl summary). The 9 udel_arl seed-1 runs stay on disk and are reported.
#  (3) an unfinished run's folder is cleared before it is rerun (no appended or mixed logs); log lines are unbuffered;
#      a short state file gives a WARN, not an abort (tuned fixed may diverge on the uniform sweep).
# Part 1: beta 1.75 / 2.0 at uniform sigma 2 (per-feature oracle, udel_gore, 250 pts), 60 runs -> t4c_uniform_sig2_beta{1.75,2.00}
# Part 2: P7b on euroc_V1_01_easy: fixed / pooled@1.5 / per-feature@1.5, f 0.5, sigma_bad 1.25/1.5/2.5, 250 pts, 270 -> t4val_*
# Part 3: tuned fixed (sigma0 1.5): T.3b grid (360) + held-out zupt, tum, euroc (270) = 630 -> t4tf_t3bgrid, t4tf_val
# Part 4: tuned fixed on the uniform sweep, cells mirrored from t4a_uniform (540) -> t4tf_uniform
# Usage: scripts/run_t4_audit_batch_v2.sh [parts, default 123]. DRYRUN=1 counts runs only; VERIFY_ONLY=1 verifies
# finished runs without starting any. Resumable.
# Stop safely: pkill -f run_t4_audit_batch_v2; pkill -f run_simulation
PARTS=${1:-123}
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
RES=~/navcore_ws/results
SIMDIR=~/navcore_ws/src/open_vins/ov_data/sim
HELD=(udel_gore_zupt tum_corridor1_512_16_okvis euroc_V1_01_easy)
CELLS=("0.25 1.25" "0.25 1.5" "0.25 2.5" "0.5 1.25" "0.5 1.5" "0.5 2.5")
SB=(1.25 1.5 2.5)
NS=${NSEEDS:-30}
declare -A FULL=([udel_gore]=1699 [udel_gore_zupt]=2156 [tum_corridor1_512_16_okvis]=2918)
i=0

rd() { if [ -f "$1" ]; then cat "$1"; elif [ -f "$1.gz" ]; then zcat "$1.gz"; fi; }

verify() {  # out mode scale tuned sig f bad ; prints the reason and returns 1 on failure
  local out=$1 mode=$2 scale=$3 tuned=$4 sig=$5 f=$6 b=$7 s0=1.0
  [ "$tuned" = 1 ] && s0=1.5
  rd "$out/run.log" | grep -q "^elapsed_s=" || { echo "no elapsed_s line"; return 1; }
  rd "$out/run.log" | grep -qF "[NavCore] sim noise: sim_sigma_pix=$(printf "%.3f" $sig) sim_bad_fraction=$(printf "%.3f" $f) sim_sigma_bad=$(printf "%.3f" $b)" \
    || { echo "sim noise line missing or different"; return 1; }
  if [ "$mode" != 0 ]; then
    rd "$out/run.log" | grep -qF "[NavCore] R mode $mode, oracle scale $(printf "%.3f" $scale)" || { echo "R mode $mode line missing"; return 1; }
  elif rd "$out/run.log" | grep -q "R mode [12]"; then echo "oracle mode active in a stock run"; return 1; fi
  { rd "$out/gate_feat.csv"; rd "$out/gate_slam.csv"; } | awk -F, -v mode=$mode -v beta=$scale -v s0=$s0 '
    $1 == "timestamp" || NF < 5 { next }
    { t = $4 + 0; u = $5 + 0; n++
      if (mode == 0)      { if (u < s0 - 1e-4 || u > s0 + 1e-4) bad++ }
      else if (mode == 1) { e = beta * t; if (u < e - 1e-3 || u > e + 1e-3) bad++ }
      else                { if ($1 in v) { if (u < v[$1] - 1e-4 || u > v[$1] + 1e-4) bad++ } else v[$1] = u } }
    END { if (n == 0) { print "no gate rows"; exit 1 }
          if (bad) { print bad " of " n " gate rows with unexpected sigma_used"; exit 1 } }' || return 1
  return 0
}

run_one() {  # root traj seed sig f bad npts mode scale tuned
  local root=$1 traj=$2 seed=$3 sig=$4 f=$5 b=$6 np=$7 mode=$8 scale=$9 tuned=${10}
  i=$((i+1))
  local c=sig$(printf "%.3f" $sig)_f$(printf "%.3f" $f)_bad$(printf "%.3f" $b)
  [ -n "$np" ] && c=${c}_n${np}
  local out=$root/$traj/$c/seed$seed why n
  [ "${DRYRUN:-0}" = 1 ] && return
  if rd "$out/run.log" | grep -q "^elapsed_s="; then
    why=$(verify "$out" $mode $scale $tuned $sig $f $b) || { echo "ABORT: finished run fails verification ($why): $out"; exit 1; }
    echo "[$i] skip (done, verified): $out"; return
  fi
  [ "${VERIFY_ONLY:-0}" = 1 ] && { echo "[$i] not run yet: $out"; return; }
  if [ "$(df --output=avail -k ~ | tail -1)" -lt 2097152 ]; then echo "ABORT: under 2 GB free"; exit 1; fi
  rm -rf "$out"
  unset NAVCORE_R_MODE NAVCORE_ORACLE_SCALE NAVCORE_FILTER_SIGMA
  [ "$mode" != 0 ] && export NAVCORE_R_MODE=$mode NAVCORE_ORACLE_SCALE=$scale
  [ "$tuned" = 1 ] && export NAVCORE_FILTER_SIGMA=1.5
  $S $traj $seed $sig $f $b $root $np 2>&1 | sed -u "s|^|[$i] $(date +%H:%M) |"
  why=$(verify "$out" $mode $scale $tuned $sig $f $b) || { echo "ABORT ($why): $out"; exit 1; }
  if [ -n "${FULL[$traj]:-}" ]; then
    n=$(wc -l < "$out/state_estimate.txt"); [ "$n" = "${FULL[$traj]}" ] || echo "WARN: $out has $n of ${FULL[$traj]} lines"
  fi
}

# Verify one existing run and exit:  VERIFY_PATH=<run dir> VERIFY_ARGS="mode scale tuned sig f bad" scripts/run_t4_audit_batch_v2.sh
if [ -n "${VERIFY_PATH:-}" ]; then
  read m sc tu sg ff bb <<< "$VERIFY_ARGS"
  if why=$(verify "$VERIFY_PATH" $m $sc $tu $sg $ff $bb); then echo "VERIFIED: $VERIFY_PATH"; exit 0; else echo "FAILED ($why): $VERIFY_PATH"; exit 1; fi
fi
for t in udel_gore "${HELD[@]}"; do [ -f "$SIMDIR/$t.txt" ] || { echo "ABORT: trajectory $t not found"; exit 1; }; done
UNI=()
for d in $RES/t4a_uniform/*/*/; do
  traj=$(basename "$(dirname "$d")"); c=$(basename "$d")
  [[ $c =~ ^sig([0-9.]+)_f([0-9.]+)_bad(-?[0-9.]+)$ ]] && UNI+=("$traj ${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}")
done
[ "${DRYRUN:-0}" = 1 ] || echo "Audit batch v2 start: $(date) | parts $PARTS"
for seed in $(seq 1 $NS); do
  if [[ $PARTS == *1* ]]; then
    for be in 1.75 2.0; do run_one $RES/t4c_uniform_sig2_beta$(printf "%.2f" $be) udel_gore $seed 2.0 0 2.0 "" 1 $be 0; done
  fi
  if [[ $PARTS == *2* ]]; then
    for b in "${SB[@]}"; do
      run_one $RES/t4val_fixed euroc_V1_01_easy $seed 1.0 0.5 $b "" 0 1 0
      run_one $RES/t4val_pooled_b1.50 euroc_V1_01_easy $seed 1.0 0.5 $b "" 2 1.5 0
      run_one $RES/t4val_perfeat_b1.50 euroc_V1_01_easy $seed 1.0 0.5 $b "" 1 1.5 0
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
echo "Audit batch v2: $i runs, parts $PARTS"
[ "${DRYRUN:-0}" = 1 ] || echo "Audit batch v2 done: $(date)"
