#!/bin/bash
# NavCore T.4d real data: OpenVINS on EuRoC ROS2 bags.
# Default: the deterministic serial runner (ros2_serial_msckf reads the bag directly; no idle machine needed) with
# seeded IMU dither, seed = run number (results/t4d_euroc_dither). DITHER=0: undithered serial runs
# (results/t4d_euroc_serial). REALTIME=1: live subscriber + ros2 bag play (results/t4d_euroc).
# Usage:  run_t4d_euroc.sh one <seq> <config> <run> [rate]     one run
#         run_t4d_euroc.sh calib <seq> <N> [rate]               two-stage calibration on <seq> (MH data), resumable:
#             stage 1: fixed noise 0.75 / 1.0 / 1.5 px, pick by the rule in t4d_euroc_eval.py;
#             stage 2: G1c with that value as floor and excess multiplier 0.5 / 1.0 / 1.5, pick by the same rule;
#             the choices are written to calibration_<seq>.txt in the results folder
#         run_t4d_euroc.sh test <seq> <N> [rate]                held-out test with the frozen calibration (V sequences)
#         run_t4d_euroc.sh sweep <seq> <N> <config>...           runs 0..N of each listed configuration, then a summary
#   config: fixed<sigma> (e.g. fixed1.00) | g1c_b<beta>_f<sigma> (e.g. g1c_b1.0_f1.00)
#   Each configuration gets a logged check run 0 (gate logs; verifies the settings; left out of the statistics) and
#   unlogged runs 1..N. Serial: run 1 must match run 0 byte for byte (same seed; determinism check), or the batch stops.
#   bag: ~/euroc_data/<seq>_ros2      ground truth: ov_data/euroc_mav/<seq>.csv
#   start offset (serial runs): OpenVINS's own EuRoC script values for the hand-carried machine hall starts, MH_04 10 s and
#   MH_05 5 s; 0 s otherwise (MH_01 stays at 0 s, as calibrated). BAG_START=<s> overrides.
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts
# Serial runs are Monte Carlo runs with seeded IMU dither (seed = run number; run 0 repeats seed 1 with logging, so the
# determinism check still applies). DITHER=0 gives the undithered single run (results/t4d_euroc_serial).
if [ "${REALTIME:-0}" = 1 ]; then RES=$WS/results/t4d_euroc
elif [ "${DITHER:-1}" = 1 ]; then RES=$WS/results/t4d_euroc_dither
else RES=$WS/results/t4d_euroc_serial; fi
[ -n "${RES_ROOT:-}" ] && RES=$RES_ROOT   # a separate folder, e.g. for controls that must not touch real results
export T4D_EUROC_RES=$RES
PY=$WS/.venv/bin/python
CONFIG=$OV/config/euroc_mav/estimator_config.yaml

one() {
  local seq=$1 cfg=$2 rep=$3 rate=${4:-1.0}
  local bag=$HOME/euroc_data/${seq}_ros2 gt=$OV/ov_data/euroc_mav/${seq}.csv out=$RES/$seq/$cfg/run$rep
  [ -f "$bag/metadata.yaml" ] || { echo "ERROR: no ROS2 bag at $bag"; return 1; }
  [ -f "$gt" ] || { echo "ERROR: no ground truth at $gt"; return 1; }
  if [ "${REALTIME:-0}" = 1 ] && pgrep -f "run_subscribe_msckf|run_simulation|run_t4d_g1|run_t4e" > /dev/null; then
    echo "ERROR: another OpenVINS process or batch is running; real-time runs need the machine to themselves"; return 1
  fi
  local sig beta="" pf=0 envv=(env -u NAVCORE_R_MODE -u NAVCORE_FILTER_SIGMA -u NAVCORE_ORACLE_SCALE -u NAVCORE_EPI_NU0 -u NAVCORE_ORACLE_LOGSD -u NAVCORE_GATE_LOG -u NAVCORE_G1C_PERFRAME)
  case $cfg in
    fixed*) sig=${cfg#fixed} ;;
    g1c_b*_f*) beta=${cfg#g1c_b}; beta=${beta%%_f*}; sig=${cfg##*_f}
               envv+=(NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE=$beta NAVCORE_NOISE_SEED=$rep) ;;
    pfr_b*_f*) beta=${cfg#pfr_b}; beta=${beta%%_f*}; sig=${cfg##*_f}; pf=1   # G1c's per-frame version
               envv+=(NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE=$beta NAVCORE_NOISE_SEED=$rep NAVCORE_G1C_PERFRAME=1) ;;
    *) echo "unknown configuration $cfg (use fixed<sigma>, g1c_b<beta>_f<sigma> or pfr_b<beta>_f<sigma>)"; return 1 ;;
  esac
  sig=$(printf "%.3f" "$sig")   # ROS 2 needs a decimal point for doubles
  rm -rf "$out"; mkdir -p "$out"
  [ "$rep" = 0 ] && envv+=(NAVCORE_GATE_LOG=$out/gate.csv)
  set +u; source $WS/install/setup.bash; set -u   # ROS setup scripts are not set -u safe
  if [ "${REALTIME:-0}" = 1 ]; then
    "${envv[@]}" ros2 run ov_msckf run_subscribe_msckf "$CONFIG" --ros-args \
      -p save_total_state:=true -p filepath_est:=$out/state_estimate.txt -p filepath_std:=$out/state_deviation.txt \
      -p filepath_gt:=$out/state_groundtruth.txt -p up_msckf_sigma_px:=$sig -p up_slam_sigma_px:=$sig > "$out/run.log" 2>&1 &
    sleep 6
    ros2 bag play "$bag" --rate "$rate" > "$out/bag.log" 2>&1
    sleep 5
    # SIGTERM, not SIGINT: a script's background job ignores SIGINT, while ROS 2 (rclcpp) shuts down cleanly on SIGTERM
    pkill -TERM -f run_subscribe_msckf
    for _ in $(seq 1 30); do pgrep -f run_subscribe_msckf > /dev/null || break; sleep 1; done
    pkill -9 -f run_subscribe_msckf 2> /dev/null
    wait 2> /dev/null
  else
    # serial: reads the bag in recorded order; '|| true' because of the known harmless segfault at ROS 2 shutdown
    local start=${BAG_START:-}
    if [ -z "$start" ]; then case $seq in MH_04_difficult) start=10.0 ;; MH_05_difficult) start=5.0 ;; *) start=0.0 ;; esac; fi
    start=$(printf "%.2f" "$start")   # always a decimal, so ROS 2 reads it as a double
    local dseed=0
    if [ "${DITHER:-1}" = 1 ]; then dseed=$(( rep > 0 ? rep : 1 )); fi
    "${envv[@]}" timeout -s INT -k 30 900 ros2 run ov_msckf ros2_serial_msckf "$CONFIG" --ros-args -p path_bag:=$bag -p navcore_dither_seed:=$dseed -p navcore_bag_start:=$start \
      -p save_total_state:=true -p filepath_est:=$out/state_estimate.txt -p filepath_std:=$out/state_deviation.txt \
      -p filepath_gt:=$out/state_groundtruth.txt -p up_msckf_sigma_px:=$sig -p up_slam_sigma_px:=$sig > "$out/run.log" 2>&1 || true
    grep -q "\[NavCore\] serial: [0-9]* IMU messages" "$out/run.log" || { echo "FAIL $seq $cfg run$rep: the serial runner did not finish reading the bag (see $out/run.log)"; return 1; }
    if [ "$start" != 0.00 ] && ! grep -q "\[NavCore\] serial: skipping the first" "$out/run.log"; then
      echo "FAIL $seq $cfg run$rep: a start offset of $start s was requested but is not in the log"; return 1; fi
    if [ "$dseed" -gt 0 ] && ! grep -q "\[NavCore\] serial: IMU dither seed $dseed," "$out/run.log"; then
      echo "FAIL $seq $cfg run$rep: IMU dither seed $dseed was requested but is not in the log"; return 1; fi
  fi
  local n; n=$(grep -vc '^#' "$out/state_estimate.txt" 2> /dev/null || echo 0)
  if [ "$n" -lt 500 ]; then echo "FAIL $seq $cfg run$rep: only $n states written (see $out/run.log)"; return 1; fi
  if [ -n "$beta" ] && ! grep -q "\[NavCore\] G1c:" "$out/run.log"; then echo "FAIL $seq $cfg run$rep: no [NavCore] G1c line"; return 1; fi
  if [ -n "$beta" ] && ! grep -q "\[NavCore\] R mode 5, oracle scale $(printf "%.3f" "$beta")" "$out/run.log"; then
    echo "FAIL $seq $cfg run$rep: G1c multiplier not $beta"; return 1
  fi
  if [ "$pf" = 1 ] && ! grep -q "\[NavCore\] G1c per-frame" "$out/run.log"; then echo "FAIL $seq $cfg run$rep: per-frame switch not on"; return 1; fi
  if [ "$pf" = 0 ] && grep -q "\[NavCore\] G1c per-frame" "$out/run.log"; then echo "FAIL $seq $cfg run$rep: per-frame switch on unexpectedly"; return 1; fi
  if [ "$rep" = 0 ]; then   # the check run: every row must sit at the configured noise (fixed) or at/above it (G1c)
    local ok
    if [ -n "$beta" ]; then ok=$(awk -F, -v s="$sig" 'NR > 1 && $5 < s * 0.999999 {b = 1} END {print b ? 0 : 1}' "$out/gate_feat.csv")
    else ok=$(awk -F, -v s="$sig" 'NR > 1 && ($5 < s * 0.999999 || $5 > s * 1.000001) {b = 1} END {print b ? 0 : 1}' "$out/gate_feat.csv"); fi
    [ "$ok" = 1 ] || { echo "FAIL $seq $cfg run0: sigma_used does not match the configuration ($sig px)"; return 1; }
    [ "$(wc -l < "$out/gate_feat.csv")" -gt 100 ] || { echo "FAIL $seq $cfg run0: gate log nearly empty"; return 1; }
    if [ "$pf" = 1 ]; then   # per-frame: all MSCKF rows of one update share one value
      ok=$(awk -F, 'NR > 1 && $2 == 0 { if (!($1 in lo) || $5 < lo[$1]) lo[$1] = $5; if (!($1 in hi) || $5 > hi[$1]) hi[$1] = $5 }
                    END { b = 0; for (t in lo) if (hi[t] > lo[t] * 1.000001) b = 1; print b ? 0 : 1 }' "$out/gate_feat.csv")
      [ "$ok" = 1 ] || { echo "FAIL $seq $cfg run0: per-frame run has more than one value in a frame"; return 1; }
    fi
  fi
  "$PY" "$S/t4d_euroc_eval.py" run "$out" "$gt" || return 1
  gzip -f "$out/run.log" "$out/bag.log" "$out/gate_feat.csv" "$out/gate_slam.csv" "$out/state_deviation.txt" 2> /dev/null
  return 0
}

# stage <seq> <N> <rate> <config...>: run 0 (logged) and runs 1..N of each configuration, interleaved; skips finished runs
stage() {
  local seq=$1 n=$2 rate=$3; shift 3
  local r c
  for r in $(seq 0 "$n"); do
    for c in "$@"; do
      [ -f "$RES/$seq/$c/run$r/ate.txt" ] && continue
      one "$seq" "$c" "$r" "$rate" || { echo "STOP at $seq $c run$r"; exit 2; }
    done
  done
  if [ "${REALTIME:-0}" != 1 ]; then   # determinism: the logged run 0 and the unlogged run 1 must be identical
    for c in "$@"; do
      if ! cmp -s "$RES/$seq/$c/run0/state_estimate.txt" "$RES/$seq/$c/run1/state_estimate.txt"; then
        echo "STOP: $seq $c run 0 and run 1 differ, so the serial runner is not deterministic here"; exit 2
      fi
    done
    echo "determinism check passed for $seq: $*"
  fi
}

case ${1:-} in
  one) one "${2:?seq}" "${3:?config}" "${4:?run}" "${5:-1.0}" ;;
  calib)
    seq=${2:?seq}; n=${3:?N}; rate=${4:-1.0}
    stage "$seq" "$n" "$rate" fixed0.75 fixed1.00 fixed1.50
    fx=$("$PY" "$S/t4d_euroc_eval.py" pick "$seq" fixed) || exit 2
    f=${fx#fixed}
    stage "$seq" "$n" "$rate" "g1c_b0.5_f$f" "g1c_b1.0_f$f" "g1c_b1.5_f$f"
    gx=$("$PY" "$S/t4d_euroc_eval.py" pick "$seq" g1c) || exit 2
    printf "calibrated on %s, %s runs each, %s\nfixed %s\ng1c %s\n" "$seq" "$n" "$(date +%F)" "$fx" "$gx" > "$RES/calibration_$seq.txt"
    cat "$RES/calibration_$seq.txt"
    "$PY" "$S/t4d_euroc_eval.py" summary "$seq" ;;
  test)
    seq=${2:?seq}; n=${3:?N}; rate=${4:-1.0}
    cal=$(ls "$RES"/calibration_*.txt 2> /dev/null | head -1)
    [ -n "$cal" ] || { echo "ERROR: no calibration file; run calib on MH data first"; exit 1; }
    fx=$(awk '$1 == "fixed" {print $2}' "$cal"); gx=$(awk '$1 == "g1c" {print $2}' "$cal")
    echo "frozen calibration from $cal: $fx and $gx"
    stage "$seq" "$n" "$rate" fixed1.00 "$fx" "$gx"
    "$PY" "$S/t4d_euroc_eval.py" summary "$seq" ;;
  sweep)
    seq=${2:?seq}; n=${3:?N}; shift 3
    [ $# -gt 0 ] || { echo "sweep: list at least one configuration"; exit 1; }
    stage "$seq" "$n" 1.0 "$@"
    "$PY" "$S/t4d_euroc_eval.py" summary "$seq" ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac
