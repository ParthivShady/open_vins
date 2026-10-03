#!/bin/bash
# T.3b mini-pilot: 6 cells x 5 seeds on udel_gore_zupt, to aim the full T.3b grid.
# Cells: {250 pts, 60 pts} x {uniform 1.0, half at 1.25, half at 2.5}. Filter fixed at sigma 1.0.
P=~/navcore_ws/results/t3b_pilot
S=~/navcore_ws/src/open_vins/scripts/run_t3_single.sh
T=udel_gore_zupt
for NP in "" 60; do
  for cell in "1.0 0 1.0" "1.0 0.5 1.25" "1.0 0.5 2.5"; do
    for seed in 1 2 3 4 5; do
      $S $T $seed $cell $P $NP > /dev/null 2>&1
      echo "done: n=${NP:-250} cell=[$cell] seed=$seed"
    done
  done
done

cd $P/$T
echo
echo "cell                              ATE mean ± std (m)   rejection   starved"
for d in */; do
  d=${d%/}
  ates=$(for s in 1 2 3 4 5; do grep 'rmse =>' $d/seed$s/run.log | tail -1 | sed -E 's/.*rmse => [0-9.]+, ([0-9.]+).*/\1/'; done)
  rej=$(cat $d/seed*/gate.csv | awk -F, '$1!="timestamp" && $4>0{a+=$4;p+=$5} $8==1{st++} END{printf "%5.1f%%   %4d", 100*(a-p)/a, st}')
  echo "$ates" | awk -v name=$d -v r="$rej" '{x+=$1; xx+=$1*$1; n++} END{m=x/n; printf "%-32s %.3f ± %.3f        %s\n", name, m, sqrt(xx/n-m*m), r}'
done
