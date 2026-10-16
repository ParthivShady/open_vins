#ifndef NAVCORE_NOISE_H
#define NAVCORE_NOISE_H

// NavCore T.4: per-feature measurement noise, simulation-oracle test path.
//   NAVCORE_R_MODE        unset or 0: stock filter (bit-identical); 1: oracle per-feature sigma
//   NAVCORE_ORACLE_SCALE  beta, multiplies the oracle sigma (default 1.0)
//   T.4d G1: NAVCORE_R_MODE=3: stereo epipolar sigma estimate (computed in VioManager), shrunk toward the
//            frame mean with NAVCORE_EPI_NU0 pseudo-samples (default 5); beta applies as in mode 1.
//            NAVCORE_ORACLE_LOGSD (mode 1): noisy oracle, one log-normal factor per feature with this
//            spread (default 0 = exact oracle), seeded by NAVCORE_NOISE_SEED.
//   T.4d G1b: NAVCORE_R_MODE=4: robust frame level L (25th percentile of per-feature means); a feature gets
//            its own value only if clearly noisier than L (chi-square test, 1%); otherwise L. Beta applies.
// The oracle is connected only in run_simulation.cpp. Without it, mode 1 falls back to nominal noise.

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <string>
#include <unordered_map>
#include <utility>
#include <algorithm>
#include <vector>

namespace ov_msckf {

class NavcoreNoise {
public:
  static NavcoreNoise &get() {
    static NavcoreNoise instance;
    return instance;
  }

  /// True pixel sigma of a feature id (connected by the simulator)
  std::function<double(size_t)> oracle_sigma;

  /// Pixel variance to use for this feature; nominal_sq unless mode 1 with an oracle connected
  double sigma_sq(size_t featid, double nominal_sq) {
    if (mode == 3) // T.4d G1: stereo epipolar estimate (estimator document, Sec. 3.2)
      return scale * scale * epi_sigma_sq(featid, nominal_sq);
    if (mode == 4) // T.4d G1b: robust frame level; own value only if clearly noisier
      return scale * scale * g1b_sigma_sq(featid, nominal_sq);
    if (mode == 2) // T.4b: one pooled value for every feature in the frame (set by the simulator loop)
      return (pool_sigma_sq > 0.0) ? scale * scale * pool_sigma_sq : nominal_sq;
    if (mode != 1)
      return nominal_sq;
    if (!oracle_sigma) {
      if (!warned) {
        std::fprintf(stderr, "[NavCore] NAVCORE_R_MODE=1 but no oracle connected; using nominal noise\n");
        warned = true;
      }
      return nominal_sq;
    }
    double s = scale * oracle_sigma(featid);
    if (oracle_logsd > 0.0) // T.4d G1: noisy oracle, one fixed log-normal factor per feature
      s *= std::exp(oracle_logsd * unit_normal(featid));
    return s * s;
  }

  int mode = 0;
  double pool_sigma_sq = -1.0; ///< T.4b: mean true sigma^2 over the current frame (mode 2)
  double scale = 1.0;
  double epi_nu0 = 5.0;              ///< T.4d G1, mode 3: prior weight in pseudo-samples
  double oracle_logsd = 0.0;         ///< T.4d G1, mode 1: log-spread of the noisy oracle
  unsigned long long noise_seed = 0; ///< T.4d G1: seed of that error
  double epi_pool = -1.0;            ///< T.4d G1, mode 3: mean Sampson d^2 over the current frame (px^2)

  /// T.4d G1, mode 3: called by VioManager once per frame, before the updates
  void epi_begin_frame() {
    epi_fsum = 0.0;
    epi_fn = 0;
    epi_frame_ids.clear();
    epi_frame_d2.clear();
  }
  void epi_add(size_t featid, double d2) {
    auto &a = epi_acc[featid];
    a.first += d2;
    a.second += 1.0;
    epi_fsum += d2;
    epi_fn++;
    epi_frame_ids.push_back(featid);
    epi_frame_d2.push_back(d2);
  }
  void epi_end_frame() {
    if (epi_fn > 0)
      epi_pool = epi_fsum / epi_fn;
    if (mode == 4)
      g1b_update_level();
  }
  /// (nu0 * frame mean + sum of the feature's d^2) / (nu0 + its number of samples), px^2, before beta
  double epi_sigma_sq(size_t featid, double nominal_sq) const {
    if (!(epi_pool > 0.0))
      return nominal_sq;
    double S = 0.0, m = 0.0;
    auto it = epi_acc.find(featid);
    if (it != epi_acc.end()) {
      S = it->second.first;
      m = it->second.second;
    }
    return (epi_nu0 + m > 0.0) ? (epi_nu0 * epi_pool + S) / (epi_nu0 + m) : epi_pool;
  }

  // ---- T.4d G1b (mode 4) ----
  double g1b_level = -1.0;      ///< robust frame level L (px^2), before beta
  double g1b_z = 2.3263479;     ///< normal score of the 1% test (one-sided)
  double g1b_q = 0.25;          ///< quantile of the per-feature means used for L
  double g1b_zq = -0.6744898;   ///< its normal score
  double g1b_min_test = 3.0, g1b_min_level = 5.0;
  /// Wilson-Hilferty: the point of chi2(m) at normal score z
  static double chi2_point(double m, double z) {
    const double a = 2.0 / (9.0 * m), c = 1.0 - a + z * std::sqrt(a);
    return m * c * c * c;
  }
  void g1b_update_level() {
    std::vector<double> means, ms;
    for (size_t id : epi_frame_ids) {
      auto it = epi_acc.find(id);
      if (it != epi_acc.end() && it->second.second >= g1b_min_level) {
        means.push_back(it->second.first / it->second.second);
        ms.push_back(it->second.second);
      }
    }
    if (means.size() >= 10) {
      const size_t k = (size_t)(g1b_q * (means.size() - 1));
      std::nth_element(means.begin(), means.begin() + k, means.end());
      std::nth_element(ms.begin(), ms.begin() + ms.size() / 2, ms.end());
      const double mm = ms[ms.size() / 2];
      g1b_level = means[k] / (chi2_point(mm, g1b_zq) / mm);
    } else if (epi_frame_d2.size() >= 10 && !(g1b_level > 0.0)) {
      // start-up only: median single sample over the median of chi2(1)
      std::vector<double> d = epi_frame_d2;
      std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end());
      g1b_level = d[d.size() / 2] / 0.4549364;
    }
  }
  /// L, or the feature's own mean if S/L exceeds the 99% point of chi2(m)
  double g1b_sigma_sq(size_t featid, double nominal_sq) const {
    if (!(g1b_level > 0.0))
      return nominal_sq;
    auto it = epi_acc.find(featid);
    if (it == epi_acc.end() || it->second.second < g1b_min_test)
      return g1b_level;
    const double S = it->second.first, m = it->second.second;
    if (S / g1b_level > chi2_point(m, g1b_z))
      return std::max(g1b_level, S / m);
    return g1b_level;
  }

private:
  NavcoreNoise() {
    if (const char *m = std::getenv("NAVCORE_R_MODE"))
      mode = std::atoi(m);
    if (const char *b = std::getenv("NAVCORE_ORACLE_SCALE"))
      scale = std::atof(b);
    if (mode != 0)
      std::fprintf(stderr, "[NavCore] R mode %d, oracle scale %.3f\n", mode, scale);
    if (const char *v = std::getenv("NAVCORE_EPI_NU0"))
      epi_nu0 = std::atof(v);
    if (const char *v = std::getenv("NAVCORE_ORACLE_LOGSD"))
      oracle_logsd = std::atof(v);
    if (const char *v = std::getenv("NAVCORE_NOISE_SEED"))
      noise_seed = std::strtoull(v, nullptr, 10);
    if (mode == 3 || oracle_logsd > 0.0)
      std::fprintf(stderr, "[NavCore] G1: epi nu0 %.2f, oracle logsd %.3f, noise seed %llu\n", epi_nu0, oracle_logsd, noise_seed);
    if (mode == 4)
      std::fprintf(stderr, "[NavCore] G1b: level quantile %.2f, flag test 1%%, min samples %.0f/%.0f, noise seed %llu\n", g1b_q,
                   g1b_min_test, g1b_min_level, noise_seed);
  }
  bool warned = false;
  std::unordered_map<size_t, std::pair<double, double>> epi_acc; ///< T.4d G1: featid -> (sum of d^2, count)
  double epi_fsum = 0.0;
  int epi_fn = 0;
  std::vector<size_t> epi_frame_ids; ///< T.4d G1b: features seen in stereo this frame
  std::vector<double> epi_frame_d2;   ///< T.4d G1b: their samples this frame
  /// T.4d G1: deterministic N(0,1) per (feature id, noise seed): splitmix64, then Box-Muller
  double unit_normal(size_t featid) const {
    auto mix = [](unsigned long long z) {
      z += 0x9E3779B97F4A7C15ULL;
      z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
      z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
      return z ^ (z >> 31);
    };
    const unsigned long long a = mix(mix((unsigned long long)featid) ^ mix(noise_seed + 0x5851F42D4C957F2DULL));
    const unsigned long long b = mix(a);
    const double u1 = ((a >> 11) + 0.5) / 9007199254740992.0, u2 = ((b >> 11) + 0.5) / 9007199254740992.0;
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(6.283185307179586 * u2);
  }
};


/// NavCore T.4: per-feature gate log (diagnostics only; never changes the filter).
/// Active only when NAVCORE_GATE_LOG is set; writes <that path without .csv><suffix>.
/// kind: 0 = MSCKF, 1 = SLAM update, 2 = SLAM initialisation (gate inside StateHelper; chi2 n/a).
class NavcoreFeatLog {
public:
  explicit NavcoreFeatLog(const char *suffix) {
    const char *p = std::getenv("NAVCORE_GATE_LOG");
    if (p == nullptr || p[0] == '\0')
      return;
    std::string path(p);
    if (path.size() > 4 && path.compare(path.size() - 4, 4, ".csv") == 0)
      path.resize(path.size() - 4);
    path += suffix;
    log = new std::ofstream(path, std::ios::out | std::ios::trunc);
    if (log->is_open()) {
      *log << "timestamp,kind,featid,sigma_true,sigma_used,dof,chi2,threshold,accepted\n" << std::flush;
    } else {
      delete log;
      log = nullptr;
    }
  }
  bool active() const { return log != nullptr; }
  void row(double t, int kind, size_t featid, double nominal_sq, int dof, double chi2, double threshold, bool accepted) {
    if (log == nullptr)
      return;
    NavcoreNoise &nn = NavcoreNoise::get();
    const double s_true = nn.oracle_sigma ? nn.oracle_sigma(featid) : std::nan("");
    const double s_used = std::sqrt(nn.sigma_sq(featid, nominal_sq));
    *log << std::setprecision(17) << t << "," << kind << "," << featid << "," << std::setprecision(6) << s_true << "," << s_used << ","
         << dof << "," << chi2 << "," << threshold << "," << (accepted ? 1 : 0) << "\n"
         << std::flush;
  }

private:
  std::ofstream *log = nullptr;
};

inline NavcoreFeatLog &navcore_msckf_feat_log() {
  static NavcoreFeatLog l("_feat.csv");
  return l;
}

inline NavcoreFeatLog &navcore_slam_feat_log() {
  static NavcoreFeatLog l("_slam.csv");
  return l;
}

} // namespace ov_msckf

#endif // NAVCORE_NOISE_H
