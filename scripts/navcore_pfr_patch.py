#!/usr/bin/env python3
"""NavCore: a per-frame version of G1c for the real-data comparison (per-feature vs per-frame from the same signal).
Run from ~/navcore_ws/src/open_vins on branch navcore_t4:  python3 scripts/navcore_pfr_patch.py
With NAVCORE_R_MODE=5 and NAVCORE_G1C_PERFRAME=1, every feature in a frame gets max(configured sigma^2, beta^2 L), the
frame level only: the per-feature excess for clearly noisier features is left out. Unset: G1c exactly as before.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import glob, subprocess, sys

hits = [p for p in glob.glob('ov_msckf/src/**/NavcoreNoise.h', recursive=True)]
if len(hits) != 1:
    sys.exit(f'expected one NavcoreNoise.h under ov_msckf/src, found {hits}; nothing changed')
P = hits[0]
s = open(P).read()
if 'NAVCORE_G1C_PERFRAME' in s:
    sys.exit('already patched (NAVCORE_G1C_PERFRAME found); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', P], capture_output=True, text=True).stdout.strip():
    sys.exit(f'uncommitted changes in {P}; commit them first. Nothing changed.')


def rep(s, old, new, what):
    if s.count(old) != 1:
        sys.exit(f'anchor for {what} found {s.count(old)} times in {P} (need 1); nothing changed')
    return s.replace(old, new)


s = rep(s, '    const double base = std::max(nominal_sq, scale * scale * g1b_level);\n',
        '    const double base = std::max(nominal_sq, scale * scale * g1b_level);\n'
        '    if (g1c_perframe) // per-frame version: frame level only, no per-feature excess\n'
        '      return base;\n', 'g1c_sigma_sq')
s = rep(s, '  bool warned = false;\n',
        '  bool warned = false;\n  bool g1c_perframe = false; ///< NAVCORE_G1C_PERFRAME=1: G1c with one value per frame\n', 'member')
s = rep(s, '    if (const char *v = std::getenv("NAVCORE_NOISE_SEED"))\n      noise_seed = std::strtoull(v, nullptr, 10);\n',
        '    if (const char *v = std::getenv("NAVCORE_NOISE_SEED"))\n      noise_seed = std::strtoull(v, nullptr, 10);\n'
        '    if (const char *v = std::getenv("NAVCORE_G1C_PERFRAME"))\n      g1c_perframe = (v[0] == \'1\');\n'
        '    if (mode == 5 && g1c_perframe)\n'
        '      std::fprintf(stderr, "[NavCore] G1c per-frame: one value per frame, no per-feature excess\\n");\n', 'constructor')
open(P, 'w').write(s)
print(subprocess.run(['git', 'diff', '--stat', P], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf')
