#!/bin/bash
# NavCore T.4e (simulator): the key comparisons rerun with independent noise in the two cameras (NAVCORE_SIM_INDEP_CAMS=1).
# Usage:  run_t4e_batch.sh 0      controls: 3 short runs; run first and check that all pass
#         run_t4e_batch.sh 123    the batch: 720 runs, about 4.5 h; resumable, seed-outer order
# Parts (udel_gore, seeds 1-30, all with independent camera noise):
#   1  half the features noisier (f 0.5, bad 1.25/1.5/2.5, 250 pts): exact oracle, per-frame, tuned fixed, stock, G1c   450 runs
#   2  clean data (1.0 px, 250 pts): G1 (mode 3), G1c, tuned fixed                                                      90 runs
#   3  same noise on every feature: stock at 1.5 and 1.75 px, tuned fixed at 2.0 and 2.5 px, G1c at 2.5 and 3.0 px      180 runs
# Every run is checked from its own records (verify_t4d_run.py ... indep) before the next one starts; a failed check
# stops the batch. Checked runs are compressed and marked, so a relaunch skips them. DRYRUN=1 lists what is left.
set -u
PARTS=${1:?usage: run_t4e_batch.sh 0 | 123}
S=$HOME/navcore_ws/src/open_vins/scripts
RES=$HOME/navcore_ws/results
PY=$HOME/navcore_ws/.venv/bin/python
unset NAVCORE_FILTER_SIGMA NAVCORE_R_MODE NAVCORE_ORACLE_SCALE NAVCORE_EPI_NU0 NAVCORE_ORACLE_LOGSD NAVCORE_NOISE_SEED NAVCORE_SIM_INDEP_CAMS
N_DONE=0; N_TODO=0

cond() { printf "sig%.3f_f%.3f_bad%.3f" "$1" "$2" "$3"; }

# kind -> environment and verifier arguments
kind_env() {   # kind seed
  case $1 in
    stock)  echo "" ;;
    tuned)  echo "NAVCORE_FILTER_SIGMA=1.5" ;;
    oracle) echo "NAVCORE_R_MODE=1 NAVCORE_ORACLE_SCALE=1.5" ;;
    pooled) echo "NAVCORE_R_MODE=2 NAVCORE_ORACLE_SCALE=1.5" ;;
    g1)     echo "NAVCORE_R_MODE=3 NAVCORE_ORACLE_SCALE=1.5 NAVCORE_EPI_NU0=5 NAVCORE_ORACLE_LOGSD=0" ;;
    g1c)    echo "NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE=1.5 NAVCORE_FILTER_SIGMA=1.5" ;;
  esac
}
kind_verify() {   # kind seed -> verifier arguments after the run folder
  case $1 in
    stock)  echo "0 1.0 5 0 $2 indep" ;;
    tuned)  echo "0 1.0 5 0 $2 tuned indep" ;;
    oracle) echo "1 1.5 5 0 $2 indep" ;;
    pooled) echo "2 1.5 5 0 $2 indep" ;;
    g1)     echo "3 1.5 5 0 $2 indep" ;;
    g1c)    echo "5 1.5 5 0 $2 tuned indep" ;;
  esac
}

# run_one kind seed sigma f bad
run_one() {
  local kind=$1 seed=$2 sig=$3 f=$4 bad=$5
  local c; c=$(cond "$sig" "$f" "$bad")
  local out=$RES/t4e_$kind/udel_gore/$c/seed$seed
  [ -f "$out/navcore_verified.txt" ] && return 0
  N_TODO=$((N_TODO + 1))
  if [ "${DRYRUN:-0}" = 1 ]; then [ "$N_TODO" -le 5 ] && echo "  to do: t4e_$kind/udel_gore/$c/seed$seed"; return 0; fi
  local free_kb; free_kb=$(df -Pk "$RES" | awk 'NR == 2 {print $4}')
  if [ "$free_kb" -lt 2000000 ]; then echo "STOP: less than 2 GB free on the results disk"; exit 3; fi
  rm -rf "$out"
  # shellcheck disable=SC2046
  env NAVCORE_SIM_INDEP_CAMS=1 NAVCORE_NOISE_SEED="$seed" $(kind_env "$kind") \
    bash "$S/run_t3_single.sh" udel_gore "$seed" "$sig" "$f" "$bad" "$RES/t4e_$kind" > /dev/null 2>&1
  # shellcheck disable=SC2046
  if ! "$PY" "$S/verify_t4d_run.py" "$out" $(kind_verify "$kind" "$seed") > "$RES/t4d_last_check.txt" 2>&1; then
    cat "$RES/t4d_last_check.txt"; echo "STOP: check failed; the run is left in $out"; exit 2
  fi
  gzip -f "$out/run.log" "$out/state_deviation.txt" "$out/gate_feat.csv" "$out/gate_slam.csv" 2> /dev/null
  echo "$kind indep seed $seed verified $(date +%F_%T)" > "$out/navcore_verified.txt"
  N_DONE=$((N_DONE + 1))
  [ $((N_DONE % 30)) -eq 0 ] && echo "$(date +%T) $N_DONE runs done (last: t4e_$kind/udel_gore/$c/seed$seed)"
}

part_runs() {   # part seed
  local p=$1 s=$2 b k
  case $p in
    1) for b in 1.25 1.5 2.5; do for k in oracle pooled tuned stock g1c; do run_one $k "$s" 1.0 0.5 $b; done; done ;;
    2) for k in g1 g1c tuned; do run_one $k "$s" 1.0 0.0 1.0; done ;;
    3) run_one stock "$s" 1.5 0.0 1.5; run_one stock "$s" 1.75 0.0 1.75
       run_one tuned "$s" 2.0 0.0 2.0; run_one tuned "$s" 2.5 0.0 2.5
       run_one g1c "$s" 2.5 0.0 2.5;   run_one g1c "$s" 3.0 0.0 3.0 ;;
    *) echo "unknown part $p"; exit 1 ;;
  esac
}

controls() {
  local C=$RES/t4e_controls ok=1 d1 d2
  rm -rf "$C"; mkdir -p "$C"
  echo "[1/3] switch off: the stock filter must still match T.3a byte for byte (udel_gore, 1.0 px, seed 1)"
  bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.0 1.0 "$C/off" > /dev/null 2>&1
  d1=$C/off/udel_gore/sig1.000_f0.000_bad1.000/seed1
  if cmp -s "$d1/state_estimate.txt" "$RES/t3a/udel_gore/sig1.000_f0.000_bad1.000/seed1/state_estimate.txt"; then echo "  PASS identical"; else echo "  FAIL differs"; ok=0; fi
  "$PY" "$S/verify_t4d_run.py" "$d1" 0 1.0 5 0 1 || ok=0
  echo "[2/3] switch on: the same run must complete, show the switch line, and differ"
  env NAVCORE_SIM_INDEP_CAMS=1 NAVCORE_NOISE_SEED=1 bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.0 1.0 "$C/on" > /dev/null 2>&1
  d2=$C/on/udel_gore/sig1.000_f0.000_bad1.000/seed1
  "$PY" "$S/verify_t4d_run.py" "$d2" 0 1.0 5 0 1 indep || ok=0
  if cmp -s "$d1/state_estimate.txt" "$d2/state_estimate.txt"; then echo "  FAIL the switch changed nothing"; ok=0; else echo "  PASS the noise changed"; fi
  echo "[3/3] G1 epipolar estimate (mode 3) with the switch on, clean data: its level should now sit near 1.00"
  env NAVCORE_SIM_INDEP_CAMS=1 NAVCORE_R_MODE=3 NAVCORE_ORACLE_SCALE=1.5 NAVCORE_EPI_NU0=5 NAVCORE_ORACLE_LOGSD=0 NAVCORE_NOISE_SEED=1 \
    bash "$S/run_t3_single.sh" udel_gore 1 1.0 0.0 1.0 "$C/g1" > /dev/null 2>&1
  "$PY" "$S/verify_t4d_run.py" "$C/g1/udel_gore/sig1.000_f0.000_bad1.000/seed1" 3 1.5 5 0 1 indep || ok=0
  "$PY" "$S/t3_ate.py" "$d1" "$d2" 2> /dev/null | awk -F'\t' '{n = split($1, p, "/"); printf "  ATE %-4s %s m  %s deg\n", p[n-3], $2, $3}'
  if [ $ok = 1 ]; then echo "ALL CONTROLS PASSED"; else echo "SOME CONTROLS FAILED: do not start the batch"; exit 1; fi
}

if [ "$PARTS" = 0 ]; then controls; exit $?; fi
case $PARTS in *[!1-3]*) echo "parts must be digits 1-3 (or 0 for the controls)"; exit 1 ;; esac
echo "$(date +%T) T.4e batch (independent camera noise), parts $PARTS"
for s in ${T4E_SEEDS:-$(seq 1 30)}; do   # T4E_SEEDS is only for testing the script on a few seeds
  for (( i = 0; i < ${#PARTS}; i++ )); do part_runs "${PARTS:$i:1}" "$s"; done
done
if [ "${DRYRUN:-0}" = 1 ]; then echo "DRYRUN: $N_TODO runs still to do"; exit 0; fi
echo "$(date +%T) finished: $N_DONE runs done in this session; all planned runs of parts $PARTS are verified"
