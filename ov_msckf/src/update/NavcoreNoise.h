#ifndef NAVCORE_NOISE_H
#define NAVCORE_NOISE_H

// NavCore T.4: per-feature measurement noise, simulation-oracle test path.
//   NAVCORE_R_MODE        unset or 0: stock filter (bit-identical); 1: oracle per-feature sigma
//   NAVCORE_ORACLE_SCALE  beta, multiplies the oracle sigma (default 1.0)
// The oracle is connected only in run_simulation.cpp. Without it, mode 1 falls back to nominal noise.

#include <cstdio>
#include <cstdlib>
#include <functional>

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

} // namespace ov_msckf

#endif // NAVCORE_NOISE_H
