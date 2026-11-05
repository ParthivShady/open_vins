#!/bin/bash
# NavCore overnight queue (24 Oct). One command before bed; each step runs after the previous one.
#   1  TUM-VI rooms 1-5 test (run_tumvi.sh; predictions P38-P41 frozen in Notion)                       about 3.5 h
#      in parallel, network only: TUM-VI corridor1-5 downloads to /mnt/data/tumvi, kept unseen for the
#      improved version's validation (nothing is run on them)                                          about 2.5 h
#   2  exploratory, no prediction: tuned fixed with the gate widened 2x on MH_04 and MH_05 at the 15 s start,
#      next to the other methods already run there                                                     about 15 min
#   3  figures redrawn, results backed up to /mnt/data/navcore_backup
# Usage:  nohup systemd-inhibit --what=sleep:idle --why="NavCore night" bash scripts/night_all.sh > ~/navcore_ws/results/night_all.log 2>&1 &
set -u
WS=$HOME/navcore_ws; OV=$WS/src/open_vins; S=$OV/scripts; PY=$WS/.venv/bin/python; T=/mnt/data/tumvi
echo "$(date +%T) night queue started"
mountpoint -q /mnt/data || { echo "the data drive is not mounted at /mnt/data: stopping"; exit 1; }
cd "$OV" || exit 1

# corridor downloads start 5 minutes in, after run_tumvi.sh has passed its wait-for-downloads check
( sleep 300; cd "$T" || exit 1
  for i in 1 2 3 4 5; do f=dataset-corridor${i}_512_16.bag; [ -s "$f" ] && continue
    for u in https://cdn3.vision.in.tum.de/tumvi/calibrated/512_16/$f http://vision.in.tum.de/tumvi/calibrated/512_16/$f; do
      wget -q --user-agent="Mozilla/5.0 (X11; Linux x86_64)" -O "$f.part" "$u" && mv "$f.part" "$f" && echo "$(date +%T) $f done" && break
      echo "$(date +%T) $f: failed from $u"; rm -f "$f.part"
    done
  done ) > "$T/dl_corridor.log" 2>&1 &

echo "$(date +%T) step 1: TUM-VI test"
bash "$S/run_tumvi.sh" > "$WS/results/tumvi.log" 2>&1
tail -4 "$WS/results/tumvi.log"

echo "$(date +%T) step 2 (exploratory): gate widened 2x at the 15 s start"
for s in MH_04_difficult MH_05_difficult; do
  BAG_START=15 RES_ROOT=$WS/results/t4d_euroc_offset15 bash "$S/run_t4d_euroc.sh" sweep $s 10 gate2_f0.75 > "$WS/results/offset15_gate_$s.log" 2>&1 \
    && echo "$(date +%T) $s done" || echo "$(date +%T) $s stopped"
done
T4D_EUROC_RES=$WS/results/t4d_euroc_offset15 "$PY" "$S/t4d_euroc_eval.py" summary > "$WS/results/offset15_summary.txt" 2>&1

echo "$(date +%T) step 3: figures and backup"
"$PY" "$S/make_t4d_real_figures.py" 2>&1 | grep wrote
mkdir -p /mnt/data/navcore_backup && cp -a "$WS/results/t4d_euroc_dither" "$WS/results/t4d_euroc_offset15" "$WS/results/gt_tumvi" \
  "$WS/results/t4d_real_summary.txt" "$WS/results/t4d_tumvi_summary.txt" "$WS/results/offset15_summary.txt" /mnt/data/navcore_backup/ 2> /dev/null
echo "backed up to /mnt/data/navcore_backup"
wait   # let the corridor downloads finish before the sleep lock is released
cat "$T/dl_corridor.log"
echo "$(date +%T) night queue finished"
