#!/usr/bin/env python3
"""
Extract TUM-format trajectory (t tx ty tz qx qy qz qw) from an OpenVINS
state file written by ROSVisualizerHelper::sim_save_total_state_to_file.

State file schema (whitespace-separated, one row per MSCKF update):
    col 0    : timestamp (s)
    cols 1-4 : quaternion q_GtoI (qx, qy, qz, qw)   -- JPL Hamiltonian order
    cols 5-7 : position p_IinG (tx, ty, tz)
    cols 8-  : velocity, biases, calibration, ...   -- ignored
Lines starting with '#' are headers and are skipped.

Usage:
    state_to_tum.py <input_state.txt> <output_tum.txt>
"""
import sys
from pathlib import Path

def main():
    if len(sys.argv) != 3:
        print("usage: state_to_tum.py <input_state.txt> <output_tum.txt>",
              file=sys.stderr)
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    if not src.is_file():
        print(f"error: input file not found: {src}", file=sys.stderr)
        sys.exit(2)

    rows_written = 0
    with src.open() as fin, dst.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                print(f"warn: skipping short row ({len(parts)} cols): "
                      f"{line[:60]}", file=sys.stderr)
                continue
            t = parts[0]
            qx, qy, qz, qw = parts[1:5]
            tx, ty, tz = parts[5:8]
            # TUM order: t tx ty tz qx qy qz qw
            fout.write(f"{t} {tx} {ty} {tz} {qx} {qy} {qz} {qw}\n")
            rows_written += 1

    print(f"wrote {rows_written} rows to {dst}")

if __name__ == "__main__":
    main()
