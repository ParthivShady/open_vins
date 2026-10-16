#!/usr/bin/env python3
"""NavCore T.4d G1b patch. Run from ~/navcore_ws/src/open_vins on branch navcore_t4, after the G1 commit:
    python3 scripts/navcore_g1b_patch.py

Adds NAVCORE_R_MODE=4 without changing modes 0-3:
  - a robust frame level L: the 25th percentile of the per-feature mean Sampson d^2 over the features seen in stereo
    this frame (at least 5 samples each), divided by the 25th percentile of chi2(m)/m at their median m, so that it
    estimates the clean noise level even when many features are noisier (the per-frame average was pulled up by them);
  - a feature gets its own value S/m only if it is clearly noisier than L: S/L above the 99% point of chi2(m)
    (at least 3 samples); otherwise it gets L. Clean features therefore carry no estimation noise.
  - beta applies as in modes 1-3. Chi-square points use the Wilson-Hilferty formula (no new dependency).
The stereo samples are those of mode 3 (VioManager hook), which now also runs in mode 4.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import os, subprocess, sys

NN = 'ov_msckf/src/update/NavcoreNoise.h'
VM = 'ov_msckf/src/core/VioManager.cpp'
for p in (NN, VM):
    if not os.path.isfile(p):
        sys.exit(f'not found: {p}  (run this from ~/navcore_ws/src/open_vins)')
nn, vm = open(NN).read(), open(VM).read()
if 'T.4d G1 ' not in nn and 'T.4d G1:' not in nn:
    sys.exit('the G1 patch is not in NavcoreNoise.h; apply and commit it first. Nothing changed.')
if 'T.4d G1b' in nn or 'T.4d G1b' in vm:
    sys.exit('already patched (T.4d G1b found); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', NN, VM], capture_output=True, text=True).stdout.strip():
    sys.exit('uncommitted changes in NavcoreNoise.h or VioManager.cpp; commit the G1 code first. Nothing changed.')


def rep(s, old, new, what):
    n = s.count(old)
    if n != 1:
        sys.exit(f'anchor for {what} found {n} times (need 1); nothing changed')
    return s.replace(old, new)


nn = rep(nn, '#include <utility>\n', '#include <utility>\n#include <algorithm>\n#include <vector>\n', 'includes')
nn = rep(nn, '//            spread (default 0 = exact oracle), seeded by NAVCORE_NOISE_SEED.\n',
         '//            spread (default 0 = exact oracle), seeded by NAVCORE_NOISE_SEED.\n'
         '//   T.4d G1b: NAVCORE_R_MODE=4: robust frame level L (25th percentile of per-feature means); a feature gets\n'
         '//            its own value only if clearly noisier than L (chi-square test, 1%); otherwise L. Beta applies.\n',
         'header comment')
nn = rep(nn, '      return scale * scale * epi_sigma_sq(featid, nominal_sq);\n',
         '      return scale * scale * epi_sigma_sq(featid, nominal_sq);\n'
         '    if (mode == 4) // T.4d G1b: robust frame level; own value only if clearly noisier\n'
         '      return scale * scale * g1b_sigma_sq(featid, nominal_sq);\n', 'mode 4 branch')
nn = rep(nn, '  void epi_begin_frame() {\n    epi_fsum = 0.0;\n    epi_fn = 0;\n  }\n',
         '  void epi_begin_frame() {\n    epi_fsum = 0.0;\n    epi_fn = 0;\n    epi_frame_ids.clear();\n    epi_frame_d2.clear();\n  }\n',
         'begin frame')
nn = rep(nn, '    epi_fsum += d2;\n    epi_fn++;\n  }\n',
         '    epi_fsum += d2;\n    epi_fn++;\n    epi_frame_ids.push_back(featid);\n    epi_frame_d2.push_back(d2);\n  }\n',
         'add sample')
nn = rep(nn, '  void epi_end_frame() {\n    if (epi_fn > 0)\n      epi_pool = epi_fsum / epi_fn;\n  }\n',
         '  void epi_end_frame() {\n    if (epi_fn > 0)\n      epi_pool = epi_fsum / epi_fn;\n    if (mode == 4)\n      g1b_update_level();\n  }\n',
         'end frame')
nn = rep(nn, '    return (epi_nu0 + m > 0.0) ? (epi_nu0 * epi_pool + S) / (epi_nu0 + m) : epi_pool;\n  }\n',
         '    return (epi_nu0 + m > 0.0) ? (epi_nu0 * epi_pool + S) / (epi_nu0 + m) : epi_pool;\n  }\n'
         '\n'
         '  // ---- T.4d G1b (mode 4) ----\n'
         '  double g1b_level = -1.0;      ///< robust frame level L (px^2), before beta\n'
         '  double g1b_z = 2.3263479;     ///< normal score of the 1% test (one-sided)\n'
         '  double g1b_q = 0.25;          ///< quantile of the per-feature means used for L\n'
         '  double g1b_zq = -0.6744898;   ///< its normal score\n'
         '  double g1b_min_test = 3.0, g1b_min_level = 5.0;\n'
         '  /// Wilson-Hilferty: the point of chi2(m) at normal score z\n'
         '  static double chi2_point(double m, double z) {\n'
         '    const double a = 2.0 / (9.0 * m), c = 1.0 - a + z * std::sqrt(a);\n'
         '    return m * c * c * c;\n'
         '  }\n'
         '  void g1b_update_level() {\n'
         '    std::vector<double> means, ms;\n'
         '    for (size_t id : epi_frame_ids) {\n'
         '      auto it = epi_acc.find(id);\n'
         '      if (it != epi_acc.end() && it->second.second >= g1b_min_level) {\n'
         '        means.push_back(it->second.first / it->second.second);\n'
         '        ms.push_back(it->second.second);\n'
         '      }\n'
         '    }\n'
         '    if (means.size() >= 10) {\n'
         '      const size_t k = (size_t)(g1b_q * (means.size() - 1));\n'
         '      std::nth_element(means.begin(), means.begin() + k, means.end());\n'
         '      std::nth_element(ms.begin(), ms.begin() + ms.size() / 2, ms.end());\n'
         '      const double mm = ms[ms.size() / 2];\n'
         '      g1b_level = means[k] / (chi2_point(mm, g1b_zq) / mm);\n'
         '    } else if (epi_frame_d2.size() >= 10 && !(g1b_level > 0.0)) {\n'
         '      // start-up only: median single sample over the median of chi2(1)\n'
         '      std::vector<double> d = epi_frame_d2;\n'
         '      std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end());\n'
         '      g1b_level = d[d.size() / 2] / 0.4549364;\n'
         '    }\n'
         '  }\n'
         '  /// L, or the feature\'s own mean if S/L exceeds the 99% point of chi2(m)\n'
         '  double g1b_sigma_sq(size_t featid, double nominal_sq) const {\n'
         '    if (!(g1b_level > 0.0))\n'
         '      return nominal_sq;\n'
         '    auto it = epi_acc.find(featid);\n'
         '    if (it == epi_acc.end() || it->second.second < g1b_min_test)\n'
         '      return g1b_level;\n'
         '    const double S = it->second.first, m = it->second.second;\n'
         '    if (S / g1b_level > chi2_point(m, g1b_z))\n'
         '      return std::max(g1b_level, S / m);\n'
         '    return g1b_level;\n'
         '  }\n', 'G1b members')
nn = rep(nn, '      std::fprintf(stderr, "[NavCore] G1: epi nu0 %.2f, oracle logsd %.3f, noise seed %llu\\n", epi_nu0, oracle_logsd, noise_seed);\n',
         '      std::fprintf(stderr, "[NavCore] G1: epi nu0 %.2f, oracle logsd %.3f, noise seed %llu\\n", epi_nu0, oracle_logsd, noise_seed);\n'
         '    if (mode == 4)\n'
         '      std::fprintf(stderr, "[NavCore] G1b: level quantile %.2f, flag test 1%%, min samples %.0f/%.0f, noise seed %llu\\n", g1b_q,\n'
         '                   g1b_min_test, g1b_min_level, noise_seed);\n', 'constructor print')
nn = rep(nn, '  int epi_fn = 0;\n',
         '  int epi_fn = 0;\n  std::vector<size_t> epi_frame_ids; ///< T.4d G1b: features seen in stereo this frame\n'
         '  std::vector<double> epi_frame_d2;   ///< T.4d G1b: their samples this frame\n', 'private members')
vm = rep(vm, '  if (NavcoreNoise::get().mode == 3 && state->_calib_IMUtoCAM.count(0) && state->_calib_IMUtoCAM.count(1)) {\n',
         '  // T.4d G1b: mode 4 uses the same stereo samples\n'
         '  if ((NavcoreNoise::get().mode == 3 || NavcoreNoise::get().mode == 4) && state->_calib_IMUtoCAM.count(0) &&\n'
         '      state->_calib_IMUtoCAM.count(1)) {\n', 'VioManager condition')
open(NN, 'w').write(nn)
open(VM, 'w').write(vm)
print(subprocess.run(['git', 'diff', '--stat', NN, VM], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf, then scripts/run_t4d_g1b_batch.sh 0 (controls)')
