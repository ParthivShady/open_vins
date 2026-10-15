#!/usr/bin/env python3
"""NavCore T.4d G1 patch. Run from ~/navcore_ws/src/open_vins on branch navcore_t4:  python3 navcore_g1_patch.py

Adds, without changing anything in the default (stock) path:
  - NAVCORE_R_MODE=3: per-feature sigma from the stereo epipolar (Sampson) residual, computed once per frame in
    VioManager before the updates and shrunk toward the frame mean with NAVCORE_EPI_NU0 pseudo-samples (default 5);
  - NAVCORE_ORACLE_LOGSD (mode 1): noisy oracle, true sigma times one log-normal factor per feature,
    seeded by NAVCORE_NOISE_SEED.
Both updaters read sigma through NavcoreNoise::sigma_sq, so UpdaterMSCKF.cpp and UpdaterSLAM.cpp are not touched.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import os, re, subprocess, sys

NN = 'ov_msckf/src/update/NavcoreNoise.h'
VM = 'ov_msckf/src/core/VioManager.cpp'
CB = 'ov_core/src/cam/CamBase.h'
for p in (NN, VM, CB):
    if not os.path.isfile(p):
        sys.exit(f'not found: {p}  (run this from ~/navcore_ws/src/open_vins)')
nn, vm, cb = (open(p).read() for p in (NN, VM, CB))
if 'T.4d G1' in nn or 'T.4d G1' in vm:
    sys.exit('already patched (T.4d G1 found); nothing changed')
if not re.search(r'compute_distort_jacobian\(\s*const Eigen::Vector2d &\s*\w+,\s*Eigen::MatrixXd &\s*\w+,\s*Eigen::MatrixXd &\s*\w+\)', cb):
    sys.exit('CamBase::compute_distort_jacobian has an unexpected signature; paste: grep -n compute_distort_jacobian ' + CB)
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
dirty = subprocess.run(['git', 'status', '--porcelain', NN, VM], capture_output=True, text=True).stdout.strip()
if dirty:
    sys.exit('uncommitted changes in NavcoreNoise.h or VioManager.cpp; commit or stash first')

def rep(s, old, new, what):
    n = s.count(old)
    if n != 1:
        sys.exit(f'anchor for {what} found {n} times (need 1); nothing changed')
    return s.replace(old, new)

# ---------------- NavcoreNoise.h ----------------
nn = rep(nn, '//   NAVCORE_ORACLE_SCALE  beta, multiplies the oracle sigma (default 1.0)\n',
         '//   NAVCORE_ORACLE_SCALE  beta, multiplies the oracle sigma (default 1.0)\n'
         '//   T.4d G1: NAVCORE_R_MODE=3: stereo epipolar sigma estimate (computed in VioManager), shrunk toward the\n'
         '//            frame mean with NAVCORE_EPI_NU0 pseudo-samples (default 5); beta applies as in mode 1.\n'
         '//            NAVCORE_ORACLE_LOGSD (mode 1): noisy oracle, one log-normal factor per feature with this\n'
         '//            spread (default 0 = exact oracle), seeded by NAVCORE_NOISE_SEED.\n', 'header comment')
nn = rep(nn, '#include <string>\n', '#include <string>\n#include <unordered_map>\n#include <utility>\n', 'includes')
nn = rep(nn, '  double sigma_sq(size_t featid, double nominal_sq) {\n    if (mode == 2)',
         '  double sigma_sq(size_t featid, double nominal_sq) {\n'
         '    if (mode == 3) // T.4d G1: stereo epipolar estimate (estimator document, Sec. 3.2)\n'
         '      return scale * scale * epi_sigma_sq(featid, nominal_sq);\n'
         '    if (mode == 2)', 'mode 3 branch')
nn = rep(nn, '    const double s = scale * oracle_sigma(featid);\n    return s * s;\n',
         '    double s = scale * oracle_sigma(featid);\n'
         '    if (oracle_logsd > 0.0) // T.4d G1: noisy oracle, one fixed log-normal factor per feature\n'
         '      s *= std::exp(oracle_logsd * unit_normal(featid));\n'
         '    return s * s;\n', 'noisy oracle')
nn = rep(nn, '  double scale = 1.0;\n',
         '  double scale = 1.0;\n'
         '  double epi_nu0 = 5.0;              ///< T.4d G1, mode 3: prior weight in pseudo-samples\n'
         '  double oracle_logsd = 0.0;         ///< T.4d G1, mode 1: log-spread of the noisy oracle\n'
         '  unsigned long long noise_seed = 0; ///< T.4d G1: seed of that error\n'
         '  double epi_pool = -1.0;            ///< T.4d G1, mode 3: mean Sampson d^2 over the current frame (px^2)\n'
         '\n'
         '  /// T.4d G1, mode 3: called by VioManager once per frame, before the updates\n'
         '  void epi_begin_frame() {\n'
         '    epi_fsum = 0.0;\n'
         '    epi_fn = 0;\n'
         '  }\n'
         '  void epi_add(size_t featid, double d2) {\n'
         '    auto &a = epi_acc[featid];\n'
         '    a.first += d2;\n'
         '    a.second += 1.0;\n'
         '    epi_fsum += d2;\n'
         '    epi_fn++;\n'
         '  }\n'
         '  void epi_end_frame() {\n'
         '    if (epi_fn > 0)\n'
         '      epi_pool = epi_fsum / epi_fn;\n'
         '  }\n'
         '  /// (nu0 * frame mean + sum of the feature\'s d^2) / (nu0 + its number of samples), px^2, before beta\n'
         '  double epi_sigma_sq(size_t featid, double nominal_sq) const {\n'
         '    if (!(epi_pool > 0.0))\n'
         '      return nominal_sq;\n'
         '    double S = 0.0, m = 0.0;\n'
         '    auto it = epi_acc.find(featid);\n'
         '    if (it != epi_acc.end()) {\n'
         '      S = it->second.first;\n'
         '      m = it->second.second;\n'
         '    }\n'
         '    return (epi_nu0 + m > 0.0) ? (epi_nu0 * epi_pool + S) / (epi_nu0 + m) : epi_pool;\n'
         '  }\n', 'members')
nn = rep(nn, '      std::fprintf(stderr, "[NavCore] R mode %d, oracle scale %.3f\\n", mode, scale);\n  }\n',
         '      std::fprintf(stderr, "[NavCore] R mode %d, oracle scale %.3f\\n", mode, scale);\n'
         '    if (const char *v = std::getenv("NAVCORE_EPI_NU0"))\n'
         '      epi_nu0 = std::atof(v);\n'
         '    if (const char *v = std::getenv("NAVCORE_ORACLE_LOGSD"))\n'
         '      oracle_logsd = std::atof(v);\n'
         '    if (const char *v = std::getenv("NAVCORE_NOISE_SEED"))\n'
         '      noise_seed = std::strtoull(v, nullptr, 10);\n'
         '    if (mode == 3 || oracle_logsd > 0.0)\n'
         '      std::fprintf(stderr, "[NavCore] G1: epi nu0 %.2f, oracle logsd %.3f, noise seed %llu\\n", epi_nu0, oracle_logsd, noise_seed);\n'
         '  }\n', 'constructor')
nn = rep(nn, '  bool warned = false;\n};\n',
         '  bool warned = false;\n'
         '  std::unordered_map<size_t, std::pair<double, double>> epi_acc; ///< T.4d G1: featid -> (sum of d^2, count)\n'
         '  double epi_fsum = 0.0;\n'
         '  int epi_fn = 0;\n'
         '  /// T.4d G1: deterministic N(0,1) per (feature id, noise seed): splitmix64, then Box-Muller\n'
         '  double unit_normal(size_t featid) const {\n'
         '    auto mix = [](unsigned long long z) {\n'
         '      z += 0x9E3779B97F4A7C15ULL;\n'
         '      z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;\n'
         '      z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;\n'
         '      return z ^ (z >> 31);\n'
         '    };\n'
         '    const unsigned long long a = mix(mix((unsigned long long)featid) ^ mix(noise_seed + 0x5851F42D4C957F2DULL));\n'
         '    const unsigned long long b = mix(a);\n'
         '    const double u1 = ((a >> 11) + 0.5) / 9007199254740992.0, u2 = ((b >> 11) + 0.5) / 9007199254740992.0;\n'
         '    return std::sqrt(-2.0 * std::log(u1)) * std::cos(6.283185307179586 * u2);\n'
         '  }\n'
         '};\n', 'private members')

# ---------------- VioManager.cpp ----------------
if vm.count('NavcoreNoise.h') == 0:
    vm = rep(vm, '#include "track/TrackSIM.h"\n', '#include "track/TrackSIM.h"\n#include "update/NavcoreNoise.h"\n', 'VioManager include')
HOOK = r'''  // NavCore T.4d G1 (NAVCORE_R_MODE=3 only; skipped otherwise, so the stock path is unchanged).
  // One noise sample per stereo observation of this frame: the Sampson distance to the epipolar line, with the
  // distortion Jacobian, so that E[d2] = sigma_px^2 to first order for noise added to distorted pixels.
  // Uses only the camera calibration, not the filter's motion estimate. NavcoreNoise::sigma_sq then serves both updaters.
  if (NavcoreNoise::get().mode == 3 && state->_calib_IMUtoCAM.count(0) && state->_calib_IMUtoCAM.count(1)) {
    const Eigen::Matrix3d R01 = state->_calib_IMUtoCAM.at(1)->Rot() * state->_calib_IMUtoCAM.at(0)->Rot().transpose();
    const Eigen::Vector3d t01 = state->_calib_IMUtoCAM.at(1)->pos() - R01 * state->_calib_IMUtoCAM.at(0)->pos();
    Eigen::Matrix3d t01x;
    t01x << 0, -t01(2), t01(1), t01(2), 0, -t01(0), -t01(1), t01(0), 0;
    const Eigen::Matrix3d E01 = t01x * R01; // x1^T E01 x0 = 0 for a point seen at x0 in cam 0 and x1 in cam 1
    auto navcore_obs = [&](const std::shared_ptr<Feature> &f, size_t cam, Eigen::Vector2d &uvn) {
      auto it = f->timestamps.find(cam);
      if (it == f->timestamps.end())
        return false;
      for (size_t k = 0; k < it->second.size(); k++) {
        if (it->second.at(k) == state->_timestamp) {
          uvn = f->uvs_norm.at(cam).at(k).cast<double>();
          return true;
        }
      }
      return false;
    };
    NavcoreNoise &navcore_nn = NavcoreNoise::get();
    navcore_nn.epi_begin_frame();
    for (const auto &f : trackFEATS->get_feature_database()->features_containing(state->_timestamp, false, true)) {
      Eigen::Vector2d n0, n1;
      if (!navcore_obs(f, 0, n0) || !navcore_obs(f, 1, n1))
        continue;
      const Eigen::Vector3d x0(n0(0), n0(1), 1.0), x1(n1(0), n1(1), 1.0);
      const Eigen::Vector3d l1 = E01 * x0, l0 = E01.transpose() * x1;
      Eigen::MatrixXd J0, J1, Jzeta;
      state->_cam_intrinsics_cameras.at(0)->compute_distort_jacobian(n0, J0, Jzeta);
      state->_cam_intrinsics_cameras.at(1)->compute_distort_jacobian(n1, J1, Jzeta);
      const Eigen::Matrix2d J0t = J0.topLeftCorner<2, 2>().transpose(), J1t = J1.topLeftCorner<2, 2>().transpose();
      const Eigen::Vector2d g0 = J0t.inverse() * l0.head<2>(), g1 = J1t.inverse() * l1.head<2>(); // d eps / d pixel
      const double den = g0.squaredNorm() + g1.squaredNorm();
      const double eps = x1.dot(l1);
      if (den > 0.0 && std::isfinite(eps))
        navcore_nn.epi_add(f->featid, eps * eps / den);
    }
    navcore_nn.epi_end_frame();
  }

'''
vm = rep(vm, '  feats_lost = trackFEATS->get_feature_database()->features_not_containing_newer(state->_timestamp, false, true);\n',
         HOOK + '  feats_lost = trackFEATS->get_feature_database()->features_not_containing_newer(state->_timestamp, false, true);\n',
         'VioManager hook')

open(NN, 'w').write(nn)
open(VM, 'w').write(vm)
print(subprocess.run(['git', 'diff', '--stat', NN, VM], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf, then scripts/run_t4d_g1_batch.sh 0 (controls)')
