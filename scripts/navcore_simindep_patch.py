#!/usr/bin/env python3
"""NavCore T.4e simulator switch. Run from ~/navcore_ws/src/open_vins on branch navcore_t4:
    python3 scripts/navcore_simindep_patch.py

OpenVINS seeds every camera's measurement-noise generator with the same sim_seed_measurements (Simulator.cpp), and
both cameras' feature lists are cut to num_pts, so the generators stay in step and features at the same list position
get identical noise in both images. NAVCORE_SIM_INDEP_CAMS=1 re-seeds camera i > 0 with its own seed, so the two
images get independent noise, as with real cameras. Unset (or any other value): bit-identical to before.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import os, subprocess, sys

SIM = 'ov_msckf/src/sim/Simulator.cpp'
if not os.path.isfile(SIM):
    sys.exit(f'not found: {SIM}  (run this from ~/navcore_ws/src/open_vins)')
s = open(SIM).read()
if 'NAVCORE_SIM_INDEP_CAMS' in s:
    sys.exit('already patched (NAVCORE_SIM_INDEP_CAMS found); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', SIM], capture_output=True, text=True).stdout.strip():
    sys.exit('uncommitted changes in Simulator.cpp; commit them first. Nothing changed.')

anchor = '    gen_meas_cams.at(i).seed(params.sim_seed_measurements);\n'
if s.count(anchor) != 1:
    sys.exit(f'anchor found {s.count(anchor)} times in {SIM} (need 1); paste: grep -n gen_meas_cams {SIM}. Nothing changed.')
s = s.replace(anchor, anchor +
              '    // NavCore T.4e: NAVCORE_SIM_INDEP_CAMS=1 gives each camera its own noise stream. OpenVINS seeds all cameras\n'
              '    // alike, so features at the same list position get identical noise in both images. Unset: unchanged.\n'
              '    if (i > 0) {\n'
              '      const char *navcore_ic = std::getenv("NAVCORE_SIM_INDEP_CAMS");\n'
              '      if (navcore_ic != nullptr && navcore_ic[0] == \'1\') {\n'
              '        gen_meas_cams.at(i).seed(params.sim_seed_measurements + 1000003u * (unsigned)i);\n'
              '        if (i == 1)\n'
              '          std::fprintf(stderr, "[NavCore] sim: independent noise per camera\\n");\n'
              '      }\n'
              '    }\n')
inc = '#include "Simulator.h"\n'
if s.count(inc) == 1:
    s = s.replace(inc, inc + '#include <cstdio>\n#include <cstdlib>\n')
open(SIM, 'w').write(s)
print(subprocess.run(['git', 'diff', '--stat', SIM], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf, then scripts/run_t4e_batch.sh 0 (controls)')
