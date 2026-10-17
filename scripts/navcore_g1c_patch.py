#!/usr/bin/env python3
"""NavCore T.4d G1c patch. Run from ~/navcore_ws/src/open_vins on branch navcore_t4, after the G1b commit:
    python3 scripts/navcore_g1c_patch.py

Adds NAVCORE_R_MODE=5 without changing modes 0-4. Deployed variance of feature j:
    base   = max(configured sigma^2, beta^2 L)        the configured noise is a floor; a noisier frame raises it
    flagged (S_j / L above the 99% point of chi2(m_j)):   base + beta^2 (S_j / m_j - L)   (its measured excess)
    otherwise:                                             base
  L is the frame's clean level as in G1b, but each feature's mean is first divided by the 25th percentile of
  chi2(m_j)/m_j for its own number of samples m_j, so the 25th percentile of the normalised values estimates the
  clean level exactly for any mix of track lengths (G1b used the median m and sat 7% low on clean data).
Why: G1b over-trusted clean features when L sat low, and on real images the stereo residual (about 0.25 px) is far
below the configured noise (1 px), so the measured level must raise the noise, never replace it.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import os, subprocess, sys

NN = 'ov_msckf/src/update/NavcoreNoise.h'
VM = 'ov_msckf/src/core/VioManager.cpp'
for p in (NN, VM):
    if not os.path.isfile(p):
        sys.exit(f'not found: {p}  (run this from ~/navcore_ws/src/open_vins)')
nn, vm = open(NN).read(), open(VM).read()
if 'T.4d G1b' not in nn:
    sys.exit('the G1b patch is not in NavcoreNoise.h; apply and commit it first. Nothing changed.')
if 'T.4d G1c' in nn or 'T.4d G1c' in vm:
    sys.exit('already patched (T.4d G1c found); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', NN, VM], capture_output=True, text=True).stdout.strip():
    sys.exit('uncommitted changes in NavcoreNoise.h or VioManager.cpp; commit the G1b code first. Nothing changed.')


def rep(s, old, new, what):
    n = s.count(old)
    if n != 1:
        sys.exit(f'anchor for {what} found {n} times (need 1); nothing changed')
    return s.replace(old, new)


nn = rep(nn, '//            its own value only if clearly noisier than L (chi-square test, 1%); otherwise L. Beta applies.\n',
         '//            its own value only if clearly noisier than L (chi-square test, 1%); otherwise L. Beta applies.\n'
         '//   T.4d G1c: NAVCORE_R_MODE=5: configured sigma as a floor, raised to beta^2 L when the frame is noisier;\n'
         '//            flagged features add beta^2 (S/m - L). L uses per-feature normalisation (exact for mixed m).\n',
         'header comment')
nn = rep(nn, '    if (mode == 4) // T.4d G1b: robust frame level; own value only if clearly noisier\n',
         '    if (mode == 5) // T.4d G1c: configured noise as a floor; flagged features add their measured excess\n'
         '      return g1c_sigma_sq(featid, nominal_sq);\n'
         '    if (mode == 4) // T.4d G1b: robust frame level; own value only if clearly noisier\n', 'mode 5 branch')
nn = rep(nn, '    if (mode == 4)\n      g1b_update_level();\n',
         '    if (mode == 4)\n      g1b_update_level();\n    if (mode == 5)\n      g1c_update_level();\n', 'end frame')
nn = rep(nn, '  /// L, or the feature\'s own mean if S/L exceeds the 99% point of chi2(m)\n',
         '  // ---- T.4d G1c (mode 5) ----\n'
         '  /// L from per-feature means each divided by its own chi2(m)/m quantile: exact for any mix of track lengths\n'
         '  void g1c_update_level() {\n'
         '    std::vector<double> z;\n'
         '    for (size_t id : epi_frame_ids) {\n'
         '      auto it = epi_acc.find(id);\n'
         '      if (it != epi_acc.end() && it->second.second >= g1b_min_level) {\n'
         '        const double m = it->second.second;\n'
         '        z.push_back((it->second.first / m) / (chi2_point(m, g1b_zq) / m));\n'
         '      }\n'
         '    }\n'
         '    if (z.size() >= 10) {\n'
         '      const size_t k = (size_t)(g1b_q * (z.size() - 1));\n'
         '      std::nth_element(z.begin(), z.begin() + k, z.end());\n'
         '      g1b_level = z[k];\n'
         '    } else if (epi_frame_d2.size() >= 10 && !(g1b_level > 0.0)) {\n'
         '      std::vector<double> d = epi_frame_d2;   // start-up only\n'
         '      std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end());\n'
         '      g1b_level = d[d.size() / 2] / 0.4549364;\n'
         '    }\n'
         '  }\n'
         '  /// max(configured, beta^2 L), plus beta^2 (S/m - L) for a feature clearly noisier than L. Includes beta.\n'
         '  double g1c_sigma_sq(size_t featid, double nominal_sq) const {\n'
         '    if (!(g1b_level > 0.0))\n'
         '      return nominal_sq;\n'
         '    const double base = std::max(nominal_sq, scale * scale * g1b_level);\n'
         '    auto it = epi_acc.find(featid);\n'
         '    if (it == epi_acc.end() || it->second.second < g1b_min_test)\n'
         '      return base;\n'
         '    const double S = it->second.first, m = it->second.second;\n'
         '    if (S / g1b_level > chi2_point(m, g1b_z))\n'
         '      return base + scale * scale * std::max(0.0, S / m - g1b_level);\n'
         '    return base;\n'
         '  }\n'
         '  /// L, or the feature\'s own mean if S/L exceeds the 99% point of chi2(m)\n', 'G1c members')
nn = rep(nn, '    if (mode == 4)\n      std::fprintf(stderr, "[NavCore] G1b: level quantile %.2f, flag test 1%%, min samples %.0f/%.0f, noise seed %llu\\n", g1b_q,\n',
         '    if (mode == 5)\n'
         '      std::fprintf(stderr, "[NavCore] G1c: floor = configured sigma, level quantile %.2f per-feature normalised, flag test 1%%, noise seed %llu\\n",\n'
         '                   g1b_q, noise_seed);\n'
         '    if (mode == 4)\n      std::fprintf(stderr, "[NavCore] G1b: level quantile %.2f, flag test 1%%, min samples %.0f/%.0f, noise seed %llu\\n", g1b_q,\n',
         'constructor print')
vm = rep(vm, '  if ((NavcoreNoise::get().mode == 3 || NavcoreNoise::get().mode == 4) && state->_calib_IMUtoCAM.count(0) &&\n',
         '  if ((NavcoreNoise::get().mode == 3 || NavcoreNoise::get().mode == 4 || NavcoreNoise::get().mode == 5) && // T.4d G1c\n'
         '      state->_calib_IMUtoCAM.count(0) &&\n', 'VioManager condition')
open(NN, 'w').write(nn)
open(VM, 'w').write(vm)
print(subprocess.run(['git', 'diff', '--stat', NN, VM], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf, then scripts/run_t4d_g1c_batch.sh 0 (controls)')
