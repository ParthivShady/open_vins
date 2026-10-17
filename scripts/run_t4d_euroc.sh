#!/bin/bash
# NavCore T.4d real data: OpenVINS on a EuRoC ROS2 bag, played in real time.
# Usage:  run_t4d_euroc.sh one <seq> <config> <repeat> [rate]     one run, e.g. run_t4d_euroc.sh one MH_01_easy g1c 1
#         run_t4d_euroc.sh batch <seq> <repeats> [rate]           configurations interleaved, resumable
#   config: stock (configured 1 px) | fixed15 (1.5 px) | g1c (mode 5: 1 px floor, beta 1.5)
#   bag:    ~/euroc_data/<seq>_ros2          ground truth: ov_data/euroc_mav/<seq>.csv
# Output:   ~/navcore_ws/results/t4d_euroc/<seq>/<config>/run<repeat>/  state_estimate.txt, ate.txt, logs (compressed)
# Real-data runs differ slightly from run to run (message timing), so each configuration is repeated.
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; RES=$WS/results/t4d_euroc
PY=$WS/.venv/bin/python
CONFIG=$OV/config/euroc_mav/estimator_config.yaml

one() {
  local seq=$1 cfg=$2 rep=$3 rate=${4:-1.0}
  local bag=$HOME/euroc_data/${seq}_ros2 gt=$OV/ov_data/euroc_mav/${seq}.csv out=$RES/$seq/$cfg/run$rep
  [ -f "$bag/metadata.yaml" ] || { echo "ERROR: no ROS2 bag at $bag"; return 1; }
  [ -f "$gt" ] || { echo "ERROR: no ground truth at $gt"; return 1; }
  if pgrep -f "run_subscribe_msckf|run_simulation|run_t4d_g1" > /dev/null; then
    echo "ERROR: another OpenVINS process or batch is running; real-time runs need the machine to themselves"; return 1
  fi
  rm -rf "$out"; mkdir -p "$out"
  local envv=(env -u NAVCORE_R_MODE -u NAVCORE_FILTER_SIGMA -u NAVCORE_ORACLE_SCALE -u NAVCORE_EPI_NU0 -u NAVCORE_ORACLE_LOGSD)
  local extra=()
  case $cfg in
    stock) ;;
    fixed15) extra=(-p up_msckf_sigma_px:=1.5 -p up_slam_sigma_px:=1.5) ;;
    g1c) envv+=(NAVCORE_R_MODE=5 NAVCORE_ORACLE_SCALE=1.5 NAVCORE_NOISE_SEED=$rep) ;;
    *) echo "unknown configuration $cfg"; return 1 ;;
  esac
  set +u; source $WS/install/setup.bash; set -u   # ROS setup scripts are not set -u safe
  "${envv[@]}" NAVCORE_GATE_LOG=$out/gate.csv ros2 run ov_msckf run_subscribe_msckf "$CONFIG" --ros-args \
    -p save_total_state:=true -p filepath_est:=$out/state_estimate.txt -p filepath_std:=$out/state_deviation.txt \
    -p filepath_gt:=$out/state_groundtruth.txt "${extra[@]}" > "$out/run.log" 2>&1 &
  sleep 6
  ros2 bag play "$bag" --rate "$rate" > "$out/bag.log" 2>&1
  sleep 5
  # SIGTERM, not SIGINT: a script's background job ignores SIGINT, while ROS 2 (rclcpp) shuts down cleanly on SIGTERM
  pkill -TERM -f run_subscribe_msckf
  for _ in $(seq 1 30); do pgrep -f run_subscribe_msckf > /dev/null || break; sleep 1; done
  pkill -9 -f run_subscribe_msckf 2> /dev/null
  wait 2> /dev/null
  local n; n=$(grep -vc '^#' "$out/state_estimate.txt" 2> /dev/null || echo 0)
  if [ "$n" -lt 500 ]; then echo "FAIL $seq $cfg run$rep: only $n states written (see $out/run.log)"; return 1; fi
  if [ "$cfg" = g1c ] && ! grep -q "\[NavCore\] G1c:" "$out/run.log"; then echo "FAIL $seq g1c run$rep: no [NavCore] G1c line"; return 1; fi
  if [ "$cfg" = g1c ] && ! awk -F, 'NR > 1 && $5 < 0.999999 {bad = 1} END {exit bad}' "$out/gate_feat.csv"; then
    echo "FAIL $seq g1c run$rep: sigma_used below the 1 px floor"; return 1
  fi
  if [ "$cfg" = fixed15 ] && ! awk -F, 'NR > 1 && $5 != 1.5 {bad = 1} END {exit bad}' "$out/gate_feat.csv"; then
    echo "FAIL $seq fixed15 run$rep: sigma_used is not 1.5 everywhere"; return 1
  fi
  "$PY" "$S/t4d_euroc_eval.py" run "$out" "$gt" || return 1
  gzip -f "$out/run.log" "$out/bag.log" "$out/gate_feat.csv" "$out/gate_slam.csv" "$out/state_deviation.txt" 2> /dev/null
  return 0
}

case ${1:-} in
  one) one "${2:?seq}" "${3:?config}" "${4:?repeat}" "${5:-1.0}" ;;
  batch)
    seq=${2:?seq}; n=${3:?repeats}; rate=${4:-1.0}
    for r in $(seq 1 "$n"); do
      for cfg in stock fixed15 g1c; do
        [ -f "$RES/$seq/$cfg/run$r/ate.txt" ] && continue
        one "$seq" "$cfg" "$r" "$rate" || { echo "STOP at $seq $cfg run$r"; exit 2; }
      done
    done
    "$PY" "$S/t4d_euroc_eval.py" summary "$seq" ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
