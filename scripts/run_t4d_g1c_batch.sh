#!/bin/bash
# NavCore T.4d G1c (simulator): configured noise (1.5 px) as a floor, raised by the measured frame level; flagged
# features add their measured excess (NAVCORE_R_MODE=5 with NAVCORE_FILTER_SIGMA=1.5).
# Usage:  run_t4d_g1c_batch.sh 0       controls: 4 short runs (about 3 min); run first and check that all pass
#         run_t4d_g1c_batch.sh 1234    the batch: 900 runs, about 9 h; resumable
# Parts (beta 1.5):
#   1  G1c, uneven-noise grid: udel_gore, f 0.25/0.5 x bad 1.25/1.5/2.5 x 250/60 pts, seeds 1-30          360 runs
#   2  G1c, held-out: udel_gore_zupt, tum_corridor1, euroc_V1_01_easy; f 0.5, bad 1.25/1.5/2.5, seeds 1-30   270 runs
#   3  G1c, uniform noise, udel_gore: 1.0 px at 250 and 60 pts; 1.5, 2.0, 2.5, 3.0 px at 250 pts, seeds 1-30 180 runs
#   4  fresh seeds 31-45: G1c, udel_gore and TUM, f 0.5, bad 1.25/1.5/2.5 (tuned fixed already run on them) 90 runs
# Seeds 31-45 are interleaved with seeds 1-15, so an interrupted batch stays balanced. Every run is checked from its
# own records (verify_t4d_run.py) before the next one starts; a failed check stops the batch and leaves the run in
# place. Checked runs are compressed and marked, so a relaunch skips them. DRYRUN=1 lists the runs still to do.
set -u
PARTS=${1:?usage: run_t4d_g1c_batch.sh 0 | 1234}
S=$HOME/navcore_ws/src/open_vins/scripts
RES=$HOME/navcore_ws/results
PY=$HOME/navcore_ws/.venv/bin/python
BETA=1.5
unset NAVCORE_FILTER_SIGMA NAVCORE_R_MODE NAVCORE_ORACLE_SCALE NAVCORE_EPI_NU0 NAVCORE_ORACLE_LOGSD NAVCORE_NOISE_SEED
N_DONE=0; N_TODO=0

cond() { local c; c=$(printf "sig%.3f_f%.3f_bad%.3f" "$1" "$2" "$3"); [ -n "$4" ] && c=${c}_n$4; echo "$c"; }

# run_one root traj seed sigma f bad npts
run_one() {
  local root=$1 traj=$2 seed=$3 sig=$4 f=$5 bad=$6 npts=$7 kind=g1c
  local c; c=$(cond "$sig" "$f" "$bad" "$npts")
  local out=$RES/$root/$traj/$c/seed$seed
  [ -f "$out/navcore_verified.txt" ] && return 0
  N_TODO=$((N_TODO + 1))
  if [ "${DRYRUN:-0}" = 1 ]; then
    [ "$N_TODO" -le 5 ] && echo "  to do: $root/$traj/$c/seed$seed"
    return 0
  fi
  local free_kb; free_kb=$(df -Pk "$RES" | awk 'NR == 2 {print $4}')
  if [ "$free_kb" -lt 2000000 ]; then echo "STOP: less than 2 GB free on the results disk"; exit 3; fi
  rm -rf "$out"   # a run interrupted earlier is cleared and redone
  env NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE="$BETA" NAVCORE_FILTER_SIGMA=1.5 NAVCORE_NOISE_SEED="$seed" \
    bash "$S/run_t3_single.sh" "$traj" "$seed" "$sig" "$f" "$bad" "$RES/$root" $npts > /dev/null 2>&1
  "$PY" "$S/verify_t4d_run.py" "$out" 5 "$BETA" 5 0 "$seed" tuned > "$RES/t4d_last_check.txt" 2>&1
  if [ $? -ne 0 ]; then cat "$RES/t4d_last_check.txt"; echo "STOP: check failed; the run is left in $out"; exit 2; fi
  gzip -f "$out/run.log" "$out/state_deviation.txt" "$out/gate_feat.csv" "$out/gate_slam.csv" 2> /dev/null
  echo "$kind beta $BETA seed $seed verified $(date +%F_%T)" > "$out/navcore_verified.txt"
  N_DONE=$((N_DONE + 1))
  [ $((N_DONE % 30)) -eq 0 ] && echo "$(date +%T) $N_DONE runs done (last: $root/$traj/$c/seed$seed)"
}

# part_runs part seed
part_runs() {
  local p=$1 s=$2 n f b tr g k
  case $p in
    1) for n in "" 60; do for f in 0.25 0.5; do for b in 1.25 1.5 2.5; do
         run_one t4d_g1c udel_gore "$s" 1.0 "$f" "$b" "$n"; done; done; done ;;
    2) for tr in udel_gore_zupt tum_corridor1_512_16_okvis euroc_V1_01_easy; do for b in 1.25 1.5 2.5; do
         run_one t4d_g1c "$tr" "$s" 1.0 0.5 "$b" ""; done; done ;;
    3) for n in "" 60; do run_one t4d_g1c udel_gore "$s" 1.0 0.0 1.0 "$n"; done
       for g in 1.5 2.0 2.5 3.0; do run_one t4d_g1c udel_gore "$s" "$g" 0.0 "$g" ""; done ;;
    4) for tr in udel_gore tum_corridor1_512_16_okvis; do for b in 1.25 1.5 2.5; do
         run_one t4d_g1c "$tr" "$s" 1.0 0.5 "$b" ""; done; done ;;
    *) echo "unknown part $p"; exit 1 ;;
  esac
}

controls() {
  local C=$RES/t4d_g1c_controls ok=1 d
  local cell=sig1.000_f0.500_bad2.500
  rm -rf "$C"; mkdir -p "$C"
  check_same() {
    if cmp -s "$1" "$2"; then echo "  PASS identical to $2"; else echo "  FAIL differs from $2"; ok=0; fi
  }
  echo "[1/4] stock filter must match T.3a byte for byte (udel_gore, 1.0 px, seed 1)"
  bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.0 1.0 "$C/stock" > /dev/null 2>&1
  check_same "$C/stock/udel_gore/sig1.000_f0.000_bad1.000/seed1/state_estimate.txt" "$RES/t3a/udel_gore/sig1.000_f0.000_bad1.000/seed1/state_estimate.txt"
  echo "[2/4] G1b (mode 4) must match its G1b run byte for byte (f 0.5, bad 2.5, seed 1)"
  env NAVCORE_R_MODE=4 NAVCORE_ORACLE_SCALE=$BETA NAVCORE_NOISE_SEED=1 bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/g1b" > /dev/null 2>&1
  check_same "$C/g1b/udel_gore/$cell/seed1/state_estimate.txt" "$RES/t4d_g1b/udel_gore/$cell/seed1/state_estimate.txt"
  echo "[3/4] tuned fixed (sigma 1.5) must match its P8 run byte for byte (same cell)"
  env NAVCORE_FILTER_SIGMA=1.5 bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/tuned" > /dev/null 2>&1
  check_same "$C/tuned/udel_gore/$cell/seed1/state_estimate.txt" "$RES/t4tf_t3bgrid/udel_gore/$cell/seed1/state_estimate.txt"
  echo "[4/4] G1c (mode 5, floor 1.5 px), same cell"
  env NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE=$BETA NAVCORE_FILTER_SIGMA=1.5 NAVCORE_NOISE_SEED=1 \
    bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/g1c" > /dev/null 2>&1
  "$PY" "$S/verify_t4d_run.py" "$C/g1c/udel_gore/$cell/seed1" 5 $BETA 5 0 1 tuned || ok=0
  echo "Position / orientation ATE, seed 1, f 0.5, bad 2.5 (one seed only, not a result):"
  "$PY" "$S/t3_ate.py" "$RES/t4cal_perfeat_b1.50/udel_gore/$cell/seed1" "$C/g1b/udel_gore/$cell/seed1" "$C/g1c/udel_gore/$cell/seed1" \
    "$C/tuned/udel_gore/$cell/seed1" "$RES/t4cal_pooled_b1.50/udel_gore/$cell/seed1" 2> /dev/null |
    awk -F'\t' '{n = split($1, p, "/"); printf "  %-22s %s m  %s deg\n", p[n-3], $2, $3}'
  if [ $ok = 1 ]; then echo "ALL CONTROLS PASSED"; else echo "SOME CONTROLS FAILED: do not start the batch"; exit 1; fi
}

if [ "$PARTS" = 0 ]; then controls; exit $?; fi
case $PARTS in *[!1-4]*) echo "parts must be digits 1-4 (or 0 for the controls)"; exit 1 ;; esac
echo "$(date +%T) T.4d G1c batch, parts $PARTS"
for s in ${G1C_SEEDS:-$(seq 1 30)}; do   # G1C_SEEDS is only for testing the script on a few seeds
  for (( i = 0; i < ${#PARTS}; i++ )); do
    p=${PARTS:$i:1}
    if [ "$p" = 4 ]; then [ "$s" -le 15 ] && part_runs 4 $((s + 30)); else part_runs "$p" "$s"; fi
  done
done
if [ "${DRYRUN:-0}" = 1 ]; then echo "DRYRUN: $N_TODO runs still to do"; exit 0; fi
echo "$(date +%T) finished: $N_DONE runs done in this session; all planned runs of parts $PARTS are verified"
