#!/usr/bin/env python3
"""NavCore: two published adaptive-noise baselines, in the same filter and update path as the proposed method.
Run from ~/navcore_ws/src/open_vins on branch navcore_t4 (commit your current work first):
    python3 scripts/navcore_baselines_patch.py
  NAVCORE_R_MODE=6  Sage-Husa adaptive noise: one pixel-noise value for every feature (MSCKF and SLAM), estimated from
                    the MSCKF residuals after each update. Per feature, an unbiased estimate is
                    (r'r - trace(H P H')) / dof, in pixel units (the code undoes the whitening); the update's mean moves
                    the shared value with the Sage-Husa weight d_k = (1 - b) / (1 - b^(k+1)), b = NAVCORE_IAE_B
                    (default 0.98), clamped to 0.25-10 px. Starts at the configured noise.
  NAVCORE_R_MODE=7  Huber weighting: per MSCKF feature, u = sqrt(chi2 / dof) at the configured noise; beyond the
                    threshold c = NAVCORE_HUBER_C (default 1.345) its variance is inflated by u / c (weight c / u),
                    before the gate and the update. SLAM features keep the configured noise.
Any other mode: exactly as before (the new calls return at once).
Edits NavcoreNoise.h and UpdaterMSCKF.cpp; every edit is anchored; on any mismatch nothing is written."""
import glob, subprocess, sys

H = glob.glob('ov_msckf/src/**/NavcoreNoise.h', recursive=True)
U = 'ov_msckf/src/update/UpdaterMSCKF.cpp'
if len(H) != 1 or not glob.os.path.isfile(U):
    sys.exit(f'expected one NavcoreNoise.h and {U}; found {H}; nothing changed')
H = H[0]
h, u = open(H).read(), open(U).read()
if 'NAVCORE_IAE_B' in h or 'msckf_feature_begin' in u:
    sys.exit('already patched (baselines found); nothing changed')
if 'so wait until both groups have 20' not in h:
    sys.exit('the improved version (navcore_trust_patch.py) is not in NavcoreNoise.h; nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', H, U], capture_output=True, text=True).stdout.strip():
    sys.exit('uncommitted changes in NavcoreNoise.h or UpdaterMSCKF.cpp; commit them first. Nothing changed.')


def rep(s, old, new, what):
    if s.count(old) != 1:
        sys.exit(f'anchor for {what} found {s.count(old)} times (need 1); nothing changed')
    return s.replace(old, new)


# ---- NavcoreNoise.h ----
h = rep(h, '  double sigma_sq(size_t featid, double nominal_sq) {\n    if (mode == 3)',
        '  double sigma_sq(size_t featid, double nominal_sq) {\n'
        '    if (mode == 6) // baseline: Sage-Husa adaptive noise, one value for every feature\n'
        '      return iae_s2 > 0.0 ? iae_s2 : nominal_sq;\n'
        '    if (mode == 7) { // baseline: Huber weight per MSCKF feature (set by UpdaterMSCKF), configured noise otherwise\n'
        '      auto it = huber_s2.find(featid);\n'
        '      return it != huber_s2.end() ? it->second : nominal_sq;\n'
        '    }\n'
        '    if (mode == 3)', 'dispatch')
h = rep(h, '  int mode = 0;\n',
        '  // ---- published baselines (modes 6 and 7) ----\n'
        '  bool huber_on() const { return mode == 7; }\n'
        '  /// mode 7: weight c/u beyond the threshold, u = sqrt(chi2/dof) at the configured noise; stores and returns the\n'
        '  /// feature\'s variance (configured / weight)\n'
        '  double huber_set(size_t featid, double u, double nominal_sq) {\n'
        '    const double w = (u > huber_c) ? huber_c / u : 1.0;\n'
        '    const double s2 = nominal_sq / w;\n'
        '    huber_s2[featid] = s2;\n'
        '    return s2;\n'
        '  }\n'
        '  /// UpdaterMSCKF, once per feature before its noise is chosen: a new update (timestamp) folds the previous one\n'
        '  void msckf_feature_begin(double t) {\n'
        '    if (t != iae_t) {\n'
        '      iae_fold();\n'
        '      iae_t = t;\n'
        '    }\n'
        '  }\n'
        '  /// mode 6, after the chi-square test; res and S are whitened by sqrt(nominal / used), S = H P H\' + nominal I\n'
        '  void iae_feedback(size_t featid, double res_sq, double S_trace, int dof, double nominal_sq) {\n'
        '    if (mode != 6 || dof <= 0)\n'
        '      return;\n'
        '    const double w2 = nominal_sq / sigma_sq(featid, nominal_sq);                   // whitening factor squared\n'
        '    const double rr = res_sq / w2, hph = (S_trace - dof * nominal_sq) / w2;         // back to pixel units\n'
        '    iae_sum += (rr - hph) / dof; // unbiased one-feature estimate of the pixel-noise variance\n'
        '    iae_n++;\n'
        '    iae_nominal = nominal_sq;\n'
        '  }\n'
        '  double iae_s2 = -1.0; ///< mode 6: current shared pixel-noise variance (px^2); -1 until the first update\n'
        '  int mode = 0;\n', 'public')
h = rep(h, '                   g1c_trust, g1c_trust_rate);\n',
        '                   g1c_trust, g1c_trust_rate);\n'
        '    if (const char *v = std::getenv("NAVCORE_IAE_B"))\n'
        '      iae_b = std::atof(v);\n'
        '    if (const char *v = std::getenv("NAVCORE_HUBER_C"))\n'
        '      huber_c = std::atof(v);\n'
        '    if (mode == 6)\n'
        '      std::fprintf(stderr, "[NavCore] IAE: Sage-Husa adaptive noise, one value for all features (b %.3f, clamp %.2f-%.2f px)\\n", iae_b,\n'
        '                   iae_min, iae_max);\n'
        '    if (mode == 7)\n'
        '      std::fprintf(stderr, "[NavCore] Huber: per-feature weight from the residual at the configured noise (threshold %.3f)\\n", huber_c);\n',
        'settings')
h = rep(h, '  bool g1c_innov = false;     ///< NAVCORE_G1C_INNOV=1: improved version (trust factor on the boost)\n',
        '  bool g1c_innov = false;     ///< NAVCORE_G1C_INNOV=1: improved version (trust factor on the boost)\n'
        '  double iae_b = 0.98, iae_min = 0.25, iae_max = 10.0, iae_t = -1.0, iae_sum = 0.0, iae_nominal = 1.0;\n'
        '  int iae_n = 0, iae_k = 0;\n'
        '  double huber_c = 1.345;\n'
        '  std::unordered_map<size_t, double> huber_s2;\n'
        '  void iae_fold() {\n'
        '    if (iae_n == 0)\n'
        '      return;\n'
        '    const double v = iae_sum / iae_n;                                         // this update\'s mean estimate\n'
        '    const double d = (1.0 - iae_b) / (1.0 - std::pow(iae_b, iae_k + 1));      // Sage-Husa weight\n'
        '    const double prev = iae_s2 > 0.0 ? iae_s2 : iae_nominal;\n'
        '    iae_s2 = std::min(iae_max * iae_max, std::max(iae_min * iae_min, (1.0 - d) * prev + d * v));\n'
        '    iae_k++;\n'
        '    iae_sum = 0.0;\n'
        '    iae_n = 0;\n'
        '    if (iae_k % 200 == 0)\n'
        '      std::fprintf(stderr, "[NavCore] IAE sigma %.3f px after %d updates\\n", std::sqrt(iae_s2), iae_k);\n'
        '  }\n', 'private')
# ---- UpdaterMSCKF.cpp ----
u = rep(u, '      const double navcore_s2 = NavcoreNoise::get().sigma_sq((*it2)->featid, _options.sigma_pix_sq);\n',
        '      NavcoreNoise::get().msckf_feature_begin(state->_timestamp); // NavCore baselines: a new update folds the last one\n'
        '      double navcore_s2 = NavcoreNoise::get().sigma_sq((*it2)->featid, _options.sigma_pix_sq);\n'
        '      if (NavcoreNoise::get().huber_on()) { // NavCore baseline: Huber weight from the residual at the configured noise\n'
        '        Eigen::MatrixXd navcore_P0 = StateHelper::get_marginal_covariance(state, Hx_order);\n'
        '        Eigen::MatrixXd navcore_S0 = H_x * navcore_P0 * H_x.transpose();\n'
        '        navcore_S0.diagonal() += _options.sigma_pix_sq * Eigen::VectorXd::Ones(navcore_S0.rows());\n'
        '        const double navcore_u = std::sqrt(res.dot(navcore_S0.llt().solve(res)) / std::max(1, (int)res.rows()));\n'
        '        navcore_s2 = NavcoreNoise::get().huber_set((*it2)->featid, navcore_u, _options.sigma_pix_sq);\n'
        '      }\n', 'updater noise')
u = rep(u, '    double chi2 = res.dot(S.llt().solve(res));\n',
        '    double chi2 = res.dot(S.llt().solve(res));\n'
        '    NavcoreNoise::get().iae_feedback((*it2)->featid, res.squaredNorm(), S.trace(), (int)res.rows(), _options.sigma_pix_sq); // NavCore baseline\n',
        'updater feedback')
open(H, 'w').write(h)
open(U, 'w').write(u)
print(subprocess.run(['git', 'diff', '--stat', H, U], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf')
