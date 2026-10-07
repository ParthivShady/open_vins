#ifndef NAVCORE_NOISE_H
#define NAVCORE_NOISE_H

// NavCore T.4: per-feature measurement noise, simulation-oracle test path.
//   NAVCORE_R_MODE        unset or 0: stock filter (bit-identical); 1: oracle per-feature sigma
//   NAVCORE_ORACLE_SCALE  beta, multiplies the oracle sigma (default 1.0)
// The oracle is connected only in run_simulation.cpp. Without it, mode 1 falls back to nominal noise.

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <string>

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
    const double s = scale * oracle_sigma(featid);
    return s * s;
  }

  int mode = 0;
  double pool_sigma_sq = -1.0; ///< T.4b: mean true sigma^2 over the current frame (mode 2)
  double scale = 1.0;

private:
  NavcoreNoise() {
    if (const char *m = std::getenv("NAVCORE_R_MODE"))
      mode = std::atoi(m);
    if (const char *b = std::getenv("NAVCORE_ORACLE_SCALE"))
      scale = std::atof(b);
    if (mode != 0)
      std::fprintf(stderr, "[NavCore] R mode %d, oracle scale %.3f\n", mode, scale);
  }
  bool warned = false;
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
