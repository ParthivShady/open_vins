#!/bin/bash
# NavCore T.4d G1 (simulator): stereo epipolar sigma estimate (NAVCORE_R_MODE=3) and noisy oracle (mode 1 + log-normal error).
# Usage:  run_t4d_g1_batch.sh 0        controls: 4 short runs (about 3 min); run first and check that all pass
#         run_t4d_g1_batch.sh 12345    the batch: 1,170 runs, about 8.5 h; resumable, seed-outer order
# Parts (all with beta 1.5, 30 seeds per cell):
#   1  epipolar, uneven-noise grid: udel_gore, f 0.25/0.5 x bad 1.25/1.5/2.5 x 250/60 pts            360 runs
#   2  epipolar, held-out: udel_gore_zupt, tum_corridor1, euroc_V1_01_easy; f 0.5, bad 1.25/1.5/2.5   270 runs
#   3  epipolar, uniform noise, udel_gore: 1.0 px at 250 and 60 pts; 1.5, 2.0, 2.5, 3.0 px at 250 pts 180 runs
#   4  noisy oracle, s = 0.10 / 0.20 / 0.40: udel_gore, f 0.5, bad 1.25/1.5/2.5, 250 pts               270 runs
#   5  epipolar with nu0 = 20: udel_gore, f 0.5, bad 1.25/1.5/2.5, 250 pts                              90 runs
# Every run is checked from its own records (verify_t4d_run.py) before the next one starts; a failed check
# stops the batch and leaves that run in place. Checked runs are compressed like the earlier batches and
# marked with navcore_verified.txt, so a relaunch skips them and reruns anything unfinished.
# DRYRUN=1 lists the runs still to do, without running them.
set -u
PARTS=${1:?usage: run_t4d_g1_batch.sh 0 | 12345}
S=$HOME/navcore_ws/src/open_vins/scripts
RES=$HOME/navcore_ws/results
PY=$HOME/navcore_ws/.venv/bin/python
BETA=1.5
unset NAVCORE_FILTER_SIGMA NAVCORE_R_MODE NAVCORE_ORACLE_SCALE NAVCORE_EPI_NU0 NAVCORE_ORACLE_LOGSD NAVCORE_NOISE_SEED
N_DONE=0; N_TODO=0

cond() { local c; c=$(printf "sig%.3f_f%.3f_bad%.3f" "$1" "$2" "$3"); [ -n "$4" ] && c=${c}_n$4; echo "$c"; }

# run_one root traj seed sigma f bad npts mode nu0 logsd
run_one() {
  local root=$1 traj=$2 seed=$3 sig=$4 f=$5 bad=$6 npts=$7 mode=$8 nu0=$9 logsd=${10}
  local c; c=$(cond "$sig" "$f" "$bad" "$npts")
  local out=$RES/$root/$traj/$c/seed$seed
  [ -f "$out/navcore_verified.txt" ] && return 0
  N_TODO=$((N_TODO + 1))
  if [ "${DRYRUN:-0}" = 1 ]; then
    [ "$N_TODO" -le 5 ] && echo "  to do: $root/$traj/$c/seed$seed (mode $mode, nu0 $nu0, s $logsd)"
    return 0
  fi
  local free_kb; free_kb=$(df -Pk "$RES" | awk 'NR == 2 {print $4}')
  if [ "$free_kb" -lt 2000000 ]; then echo "STOP: less than 2 GB free on the results disk"; exit 3; fi
  rm -rf "$out"   # a run interrupted earlier is cleared and redone
  env NAVCORE_R_MODE="$mode" NAVCORE_ORACLE_SCALE="$BETA" NAVCORE_EPI_NU0="$nu0" NAVCORE_ORACLE_LOGSD="$logsd" NAVCORE_NOISE_SEED="$seed" \
    bash "$S/run_t3_single.sh" "$traj" "$seed" "$sig" "$f" "$bad" "$RES/$root" $npts > /dev/null 2>&1
  if ! "$PY" "$S/verify_t4d_run.py" "$out" "$mode" "$BETA" "$nu0" "$logsd" "$seed" > "$RES/t4d_last_check.txt" 2>&1; then
    cat "$RES/t4d_last_check.txt"; echo "STOP: check failed; the run is left in $out"; exit 2
  fi
  gzip -f "$out/run.log" "$out/state_deviation.txt" "$out/gate_feat.csv" "$out/gate_slam.csv" 2> /dev/null
  echo "mode $mode beta $BETA nu0 $nu0 logsd $logsd seed $seed verified $(date +%F_%T)" > "$out/navcore_verified.txt"
  N_DONE=$((N_DONE + 1))
  [ $((N_DONE % 30)) -eq 0 ] && echo "$(date +%T) $N_DONE runs done (last: $root/$traj/$c/seed$seed)"
}

# part_runs part seed
part_runs() {
  local p=$1 s=$2 n f b tr g ls
  case $p in
    1) for n in "" 60; do for f in 0.25 0.5; do for b in 1.25 1.5 2.5; do
         run_one t4d_epi_nu5 udel_gore "$s" 1.0 "$f" "$b" "$n" 3 5 0; done; done; done ;;
    2) for tr in udel_gore_zupt tum_corridor1_512_16_okvis euroc_V1_01_easy; do for b in 1.25 1.5 2.5; do
         run_one t4d_epi_nu5 "$tr" "$s" 1.0 0.5 "$b" "" 3 5 0; done; done ;;
    3) for n in "" 60; do run_one t4d_epi_nu5 udel_gore "$s" 1.0 0.0 1.0 "$n" 3 5 0; done
       for g in 1.5 2.0 2.5 3.0; do run_one t4d_epi_nu5 udel_gore "$s" "$g" 0.0 "$g" "" 3 5 0; done ;;
    4) for ls in 0.10 0.20 0.40; do for b in 1.25 1.5 2.5; do
         run_one "t4d_noisy_s$ls" udel_gore "$s" 1.0 0.5 "$b" "" 1 5 "$ls"; done; done ;;
    5) for b in 1.25 1.5 2.5; do run_one t4d_epi_nu20 udel_gore "$s" 1.0 0.5 "$b" "" 3 20 0; done ;;
    *) echo "unknown part $p"; exit 1 ;;
  esac
}

controls() {
  local C=$RES/t4d_controls ok=1 ref d
  rm -rf "$C"; mkdir -p "$C"
  local cell=sig1.000_f0.500_bad2.500
  echo "[1/4] stock filter must match T.3a byte for byte (udel_gore, 1.0 px, seed 1)"
  bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.0 1.0 "$C/stock" > /dev/null 2>&1
  d=$C/stock/udel_gore/sig1.000_f0.000_bad1.000/seed1; ref=$RES/t3a/udel_gore/sig1.000_f0.000_bad1.000/seed1/state_estimate.txt
  if cmp -s "$d/state_estimate.txt" "$ref"; then echo "  PASS identical to $ref"; else echo "  FAIL differs from $ref"; ok=0; fi
  "$PY" "$S/verify_t4d_run.py" "$d" 0 1.0 5 0 1 || ok=0
  echo "[2/4] exact oracle, beta 1.5, must match the equal-calibration run byte for byte (f 0.5, bad 2.5, seed 1)"
  env NAVCORE_R_MODE=1 NAVCORE_ORACLE_SCALE=$BETA bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/oracle" > /dev/null 2>&1
  d=$C/oracle/udel_gore/$cell/seed1; ref=$RES/t4cal_perfeat_b1.50/udel_gore/$cell/seed1/state_estimate.txt
  if cmp -s "$d/state_estimate.txt" "$ref"; then echo "  PASS identical to $ref"; else echo "  FAIL differs from $ref"; ok=0; fi
  "$PY" "$S/verify_t4d_run.py" "$d" 1 $BETA 5 0 1 || ok=0
  echo "[3/4] epipolar estimate, nu0 5, same cell"
  env NAVCORE_R_MODE=3 NAVCORE_ORACLE_SCALE=$BETA NAVCORE_EPI_NU0=5 NAVCORE_ORACLE_LOGSD=0 NAVCORE_NOISE_SEED=1 \
    bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/epi" > /dev/null 2>&1
  "$PY" "$S/verify_t4d_run.py" "$C/epi/udel_gore/$cell/seed1" 3 $BETA 5 0 1 || ok=0
  echo "[4/4] noisy oracle, s 0.20, same cell"
  env NAVCORE_R_MODE=1 NAVCORE_ORACLE_SCALE=$BETA NAVCORE_EPI_NU0=5 NAVCORE_ORACLE_LOGSD=0.20 NAVCORE_NOISE_SEED=1 \
    bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.5 2.5 "$C/noisy" > /dev/null 2>&1
  "$PY" "$S/verify_t4d_run.py" "$C/noisy/udel_gore/$cell/seed1" 1 $BETA 5 0.20 1 || ok=0
  echo "Position / orientation ATE, seed 1, f 0.5, bad 2.5 (one seed only, not a result):"
  "$PY" "$S/t3_ate.py" "$C/oracle/udel_gore/$cell/seed1" "$C/epi/udel_gore/$cell/seed1" "$C/noisy/udel_gore/$cell/seed1" \
    "$RES/t4cal_pooled_b1.50/udel_gore/$cell/seed1" 2> /dev/null | awk -F'\t' '{n = split($1, p, "/"); printf "  %-22s %s m  %s deg\n", p[n-3], $2, $3}'
  if [ $ok = 1 ]; then echo "ALL CONTROLS PASSED"; else echo "SOME CONTROLS FAILED: do not start the batch"; exit 1; fi
}

if [ "$PARTS" = 0 ]; then controls; exit $?; fi
case $PARTS in *[!1-5]*) echo "parts must be digits 1-5 (or 0 for the controls)"; exit 1 ;; esac
echo "$(date +%T) T.4d G1 batch, parts $PARTS"
for s in ${G1_SEEDS:-$(seq 1 30)}; do   # G1_SEEDS is only for testing the script on a few seeds
  for (( i = 0; i < ${#PARTS}; i++ )); do part_runs "${PARTS:$i:1}" "$s"; done
done
if [ "${DRYRUN:-0}" = 1 ]; then echo "DRYRUN: $N_TODO runs still to do"; exit 0; fi
echo "$(date +%T) finished: $N_DONE runs done in this session; all planned runs of parts $PARTS are verified"
