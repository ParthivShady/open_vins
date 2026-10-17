#!/usr/bin/env python3
"""NavCore T.4d G1: verify one run from its own records (run.log [NavCore] lines and the per-feature gate logs).
Usage: verify_t4d_run.py <run_dir> <mode> <beta> <nu0> <logsd> <seed> [tuned]
("tuned": the tuned-fixed override, configured sigma 1.5; mode 0 = tuned fixed, mode 5 = G1c with that floor.)
Prints 'OK ...' and exits 0 if the run used the intended settings, otherwise prints 'FAIL ...' and exits 1.
Checks: the plain [NavCore] lines (mode, beta, nu0, log-spread, seed, simulator noise); a complete state file;
sigma_used in every MSCKF and SLAM row: stock = nominal; exact oracle = beta * sigma_true; noisy oracle = one fixed
factor per feature with log-spread close to the requested one; epipolar estimate = varies between features and is
of the right size (a units error would be off by a factor of hundreds); G1b (mode 4) the same, with its own line."""
import gzip, os, sys
import numpy as np


def read(path):
    if os.path.isfile(path):
        return open(path, errors='replace').read()
    if os.path.isfile(path + '.gz'):
        return gzip.open(path + '.gz', 'rt', errors='replace').read()
    return None


def gate(path):
    txt = read(path)
    if txt is None:
        return None, 'missing'
    lines = txt.strip().splitlines()
    if not lines or not lines[0].startswith('timestamp,kind,featid,sigma_true,sigma_used'):
        return None, 'unexpected header'
    rows = [l.split(',') for l in lines[1:] if l.count(',') >= 8]
    if not rows:
        return np.zeros((0, 3)), 'no rows'
    return np.array([[float(r[2]), float(r[3]), float(r[4])] for r in rows]), None   # featid, sigma_true, sigma_used


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def check_rows(G, mode, beta, logsd, name, tuned=False):
    """returns (error or None, short summary)"""
    fid, st, su = G[:, 0], G[:, 1], G[:, 2]
    if np.mean(np.isfinite(st)) < 0.99:
        return f'{name}: sigma_true missing in {100 * np.mean(~np.isfinite(st)):.1f}% of rows (oracle not connected?)', ''
    if mode == 0:
        want = 1.5 if tuned else su[0]
        bad = np.abs(su - want) > 1e-6 * want
        return (f'{name}: fixed run but sigma_used is not {want:g} everywhere' if bad.any() else None), f'{name} sigma_used {su[0]:g}'
    if mode == 1 and logsd == 0:
        err = np.max(np.abs(su / (beta * st) - 1))
        return (f'{name}: sigma_used != beta*sigma_true (max rel err {err:.2e})' if err > 1e-4 else None), f'{name} exact'
    if mode == 1:
        r = np.log(su / (beta * st))
        ids, inv = np.unique(fid, return_inverse=True)
        order = np.argsort(inv, kind='stable'); rs, gs = r[order], inv[order]
        starts = np.r_[0, np.flatnonzero(np.diff(gs)) + 1]
        spread_within = float(np.max(np.maximum.reduceat(rs, starts) - np.minimum.reduceat(rs, starts)))
        per = rs[starts]   # one value per feature
        sd, mu = float(np.std(per)), float(np.mean(per))
        msg = f'{name} {len(ids)} features, log-spread {sd:.3f} (requested {logsd:.3f}), mean {mu:+.3f}'
        if spread_within > 1e-4:
            return f'{name}: factor not constant within a feature ({spread_within:.2e})', msg
        if not (0.8 * logsd <= sd <= 1.2 * logsd) or abs(mu) > 0.1:
            return f'{name}: noisy-oracle spread off: ' + msg, msg
        return None, msg
    if mode in (3, 4, 5):
        q = su / (beta * st)
        clean = st <= np.min(st) + 1e-9
        qc, qn = float(np.median(q[clean])), (float(np.median(q[~clean])) if (~clean).any() else float('nan'))
        nd = len(np.unique(np.round(su, 5)))
        rho = spearman(su, st) if (~clean).any() and clean.any() else float('nan')
        msg = f'{name} {nd} distinct values; median sigma_hat/sigma_true clean {qc:.2f}, noisy {qn:.2f}; rank corr {rho:.2f}'
        if mode == 5 and tuned and np.min(su) < 1.5 * (1 - 1e-6):
            return f'{name}: G1c went below its 1.5 px floor (min {np.min(su):.4f})', msg
        if nd < 50:
            return f'{name}: estimated sigma barely varies ({nd} distinct values)', msg
        if not 0.5 <= qc <= 2.5 or (np.isfinite(qn) and not 0.3 <= qn <= 2.5):
            return f'{name}: estimated sigma has the wrong size: ' + msg, msg
        return None, msg
    return f'unknown mode {mode}', ''


def main():
    if len(sys.argv) not in (7, 8) or (len(sys.argv) == 8 and sys.argv[7] != 'tuned'):
        sys.exit(__doc__)
    d, mode, beta, nu0, logsd, seed = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), int(sys.argv[6])
    tuned = len(sys.argv) == 8
    if tuned and mode not in (0, 5):
        sys.exit('tuned runs must be mode 0 or 5')
    fail = []
    log = read(d + '/run.log')
    if log is None:
        print(f'FAIL {d}: no run.log'); sys.exit(1)
    if '[NavCore] sim noise:' not in log:
        fail.append('no [NavCore] sim noise line')
    if tuned and '[NavCore-wrapper] filter sigma override 1.500' not in log:
        fail.append('tuned run without the override line (NAVCORE_FILTER_SIGMA=1.5 not passed)')
    if not tuned and '[NavCore-wrapper] filter sigma override' in log:
        fail.append('tuned-fixed override was active (NAVCORE_FILTER_SIGMA set)')
    want = f'[NavCore] R mode {mode}, oracle scale {beta:.3f}'
    if mode == 0 and '[NavCore] R mode' in log:
        fail.append('stock run printed an R mode line')
    if mode != 0 and want not in log:
        fail.append(f'missing line: {want}')
    g1 = f'[NavCore] G1: epi nu0 {nu0:.2f}, oracle logsd {logsd:.3f}, noise seed {seed}'
    if (mode == 3 or (mode == 1 and logsd > 0)) and g1 not in log:
        fail.append(f'missing line: {g1}')
    g1b = f'[NavCore] G1b: level quantile 0.25, flag test 1%, min samples 3/5, noise seed {seed}'
    if mode == 4 and g1b not in log:
        fail.append(f'missing line: {g1b}')
    g1c = f'[NavCore] G1c: floor = configured sigma, level quantile 0.25 per-feature normalised, flag test 1%, noise seed {seed}'
    if mode == 5 and g1c not in log:
        fail.append(f'missing line: {g1c}')
    if mode == 5 and not tuned:
        fail.append('G1c runs are checked with the tuned floor (pass tuned)')
    est = read(d + '/state_estimate.txt')
    if est is None or sum(1 for l in est.splitlines() if l and not l.startswith('#')) < 100:
        fail.append('state_estimate.txt missing or short')
    notes = []
    for fn, name, need in (('gate_feat.csv', 'MSCKF', 200), ('gate_slam.csv', 'SLAM', 50)):
        G, err = gate(d + '/' + fn)
        if err or G is None or len(G) < need:
            fail.append(f'{fn}: {err or "too few rows (%d)" % (0 if G is None else len(G))}')
            continue
        e, msg = check_rows(G, mode, beta, logsd, name, tuned)
        notes.append(msg)
        if e:
            fail.append(e)
    if fail:
        print(f'FAIL {d}: ' + ' | '.join(fail)); sys.exit(1)
    print(f'OK {os.path.relpath(d, os.path.expanduser("~/navcore_ws/results"))}: ' + ' | '.join(notes))


if __name__ == '__main__':
    main()
