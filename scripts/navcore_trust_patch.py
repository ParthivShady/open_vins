#!/usr/bin/env python3
"""NavCore: the improved version of the per-feature method (switch NAVCORE_G1C_INNOV=1, with NAVCORE_R_MODE=5).
Run from ~/navcore_ws/src/open_vins on branch navcore_t4:  python3 scripts/navcore_trust_patch.py
The stereo check still decides which features look noisier and proposes a boost; a trust factor in [0, 1] scales that
boost. After each frame's updates, every MSCKF feature's residual energy per dimension, (chi2 / dof) x the variance it
was given, is compared: median over flagged features minus median over the others is the excess the filter actually
saw; divided by the median proposed boost and clipped to [0, 1], it moves the trust factor 10% of the way. Feedback is
pooled across frames until both groups hold 20 features (an MSCKF update has only a few features per frame), and each
group keeps at most its 400 newest values (fixed by design: start 1, rate 0.1, 20 per group, chi2/dof capped at 50).
Trust 1 = the current version,
trust 0 = one value per image. Unset: everything exactly as before (the boost is multiplied by exactly 1.0).
Only NavcoreNoise.h changes: the feedback rides on the gate logger's row(), which OpenVINS calls for every MSCKF
feature after its chi-square test, logged or not. Every edit is anchored; on any mismatch nothing is written."""
import glob, subprocess, sys

hits = glob.glob('ov_msckf/src/**/NavcoreNoise.h', recursive=True)
if len(hits) != 1:
    sys.exit(f'expected one NavcoreNoise.h under ov_msckf/src, found {hits}; nothing changed')
P = hits[0]
s = open(P).read()
if 'so wait until both groups have 20' in s:
    sys.exit('already patched with this version; nothing changed')
if 'NAVCORE_G1C_INNOV' in s:   # the first version (per-frame groups of 5) is applied: restore the committed file first
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', P]).returncode == 0:
        sys.exit('the switch is in the committed file; edit by hand. Nothing changed.')
    subprocess.run(['git', 'checkout', '--', P], check=True)
    s = open(P).read()
    print('first version removed (file restored from the last commit)')
if 'NAVCORE_G1C_PERFRAME' not in s:
    sys.exit('the per-frame switch is missing (apply navcore_pfr_patch.py first); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', P], capture_output=True, text=True).stdout.strip():
    sys.exit(f'uncommitted changes in {P}; commit them first. Nothing changed.')


def rep(s, old, new, what):
    if s.count(old) != 1:
        sys.exit(f'anchor for {what} found {s.count(old)} times in {P} (need 1); nothing changed')
    return s.replace(old, new)


# 1  the boost is scaled by the trust factor (exactly 1.0 when the switch is off)
s = rep(s, '      return base + scale * scale * std::max(0.0, S / m - g1b_level);\n',
        '      return base + (g1c_innov ? g1c_trust : 1.0) * scale * scale * std::max(0.0, S / m - g1b_level);\n', 'boost')
# 2  fold last frame's feedback before this frame's level, so every feature in a frame sees the same trust
s = rep(s, '  void g1c_update_level() {\n    std::vector<double> z;\n',
        '  void g1c_update_level() {\n    g1c_fold(); // improved version: last frame\'s residual feedback moves the trust factor (no-op when off)\n'
        '    std::vector<double> z;\n', 'level')
# 3  public: proposed boost, feedback entry point, trust factor
s = rep(s, '  /// max(configured, beta^2 L), plus beta^2 (S/m - L) for a feature clearly noisier than L. Includes beta.\n',
        '  // ---- improved version (NAVCORE_G1C_INNOV=1): trust factor on the per-feature boost ----\n'
        '  /// The boost the stereo check proposes for this feature (px^2, includes beta); 0 if not clearly noisier\n'
        '  double g1c_boost(size_t featid) const {\n'
        '    if (!(g1b_level > 0.0) || g1c_perframe)\n'
        '      return 0.0;\n'
        '    auto it = epi_acc.find(featid);\n'
        '    if (it == epi_acc.end() || it->second.second < g1b_min_test)\n'
        '      return 0.0;\n'
        '    const double S = it->second.first, m = it->second.second;\n'
        '    if (S / g1b_level > chi2_point(m, g1b_z))\n'
        '      return scale * scale * std::max(0.0, S / m - g1b_level);\n'
        '    return 0.0;\n'
        '  }\n'
        '  /// Every MSCKF feature after its chi-square test: residual energy per dimension, (chi2/dof) x its variance,\n'
        '  /// collected separately for flagged features (with their proposed boost) and the others\n'
        '  void g1c_feedback(size_t featid, int dof, double chi2, double nominal_sq) {\n'
        '    if (mode != 5 || !g1c_innov || g1c_perframe || dof <= 0 || !std::isfinite(chi2))\n'
        '      return;\n'
        '    const double e2 = std::min(chi2 / dof, 50.0) * g1c_sigma_sq(featid, nominal_sq);\n'
        '    const double b = g1c_boost(featid);\n'
        '    if (b > 0.0) {\n'
        '      fb_flag_e2.push_back(e2);\n'
        '      fb_flag_boost.push_back(b);\n'
        '    } else {\n'
        '      fb_rest_e2.push_back(e2);\n'
        '    }\n'
        '  }\n'
        '  double g1c_trust = 1.0; ///< trust factor in [0, 1] on the per-feature boost (improved version)\n'
        '  /// max(configured, beta^2 L), plus beta^2 (S/m - L) for a feature clearly noisier than L. Includes beta.\n', 'public')
# 4  settings: switch and start-up line
s = rep(s, '    if (mode == 5 && g1c_perframe)\n'
           '      std::fprintf(stderr, "[NavCore] G1c per-frame: one value per frame, no per-feature excess\\n");\n',
        '    if (mode == 5 && g1c_perframe)\n'
        '      std::fprintf(stderr, "[NavCore] G1c per-frame: one value per frame, no per-feature excess\\n");\n'
        '    if (const char *v = std::getenv("NAVCORE_G1C_INNOV"))\n'
        '      g1c_innov = (v[0] == \'1\');\n'
        '    if (mode == 5 && g1c_innov && !g1c_perframe)\n'
        '      std::fprintf(stderr, "[NavCore] G1c trust: boost scaled by the filter residuals (start %.2f, rate %.2f, pooled 20/20, cap 50)\\n",\n'
        '                   g1c_trust, g1c_trust_rate);\n', 'settings')
# 5  private: state and the fold step
s = rep(s, '  bool g1c_perframe = false; ///< NAVCORE_G1C_PERFRAME=1: G1c with one value per frame\n',
        '  bool g1c_perframe = false; ///< NAVCORE_G1C_PERFRAME=1: G1c with one value per frame\n'
        '  bool g1c_innov = false;     ///< NAVCORE_G1C_INNOV=1: improved version (trust factor on the boost)\n'
        '  double g1c_trust_rate = 0.1; ///< fraction of the way the trust factor moves per frame (fixed by design)\n'
        '  int fb_n = 0;                ///< pooled updates that moved the trust factor\n'
        '  std::vector<double> fb_flag_e2, fb_flag_boost, fb_rest_e2;\n'
        '  void g1c_fold() {\n'
        '    // pooled across frames: an MSCKF update holds only a few features, so wait until both groups have 20\n'
        '    auto window = [](std::vector<double> &v) {\n'
        '      if (v.size() > 400)\n'
        '        v.erase(v.begin(), v.end() - 400);\n'
        '    };\n'
        '    window(fb_flag_e2);\n'
        '    window(fb_flag_boost);\n'
        '    window(fb_rest_e2);\n'
        '    if (fb_flag_e2.size() >= 20 && fb_rest_e2.size() >= 20) {\n'
        '      auto median = [](std::vector<double> v) {\n'
        '        std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end());\n'
        '        return v[v.size() / 2];\n'
        '      };\n'
        '      const double boost = median(fb_flag_boost);\n'
        '      if (boost > 0.0) {\n'
        '        const double r = std::min(1.0, std::max(0.0, (median(fb_flag_e2) - median(fb_rest_e2)) / boost));\n'
        '        g1c_trust += g1c_trust_rate * (r - g1c_trust);\n'
        '        if (++fb_n % 25 == 0)\n'
        '          std::fprintf(stderr, "[NavCore] G1c trust %.3f after %d updates\\n", g1c_trust, fb_n);\n'
        '      }\n'
        '      fb_flag_e2.clear();\n'
        '      fb_flag_boost.clear();\n'
        '      fb_rest_e2.clear();\n'
        '    }\n'
        '  }\n', 'private')
# 6  the feedback rides on the gate logger, which OpenVINS calls for every MSCKF feature (kind 0), logged or not
s = rep(s, '  void row(double t, int kind, size_t featid, double nominal_sq, int dof, double chi2, double threshold, bool accepted) {\n'
           '    if (log == nullptr)\n      return;\n',
        '  void row(double t, int kind, size_t featid, double nominal_sq, int dof, double chi2, double threshold, bool accepted) {\n'
        '    if (kind == 0) // improved version: residual feedback for every MSCKF feature, logged or not (no-op when off)\n'
        '      NavcoreNoise::get().g1c_feedback(featid, dof, chi2, nominal_sq);\n'
        '    if (log == nullptr)\n      return;\n', 'row')
open(P, 'w').write(s)
print(subprocess.run(['git', 'diff', '--stat', P], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf')
