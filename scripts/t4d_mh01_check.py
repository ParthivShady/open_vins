#!/usr/bin/env python3
"""NavCore T.4d: real-image check on EuRoC MH_01. Do features differ in pixel noise by more than sampling noise?
Usage:  ~/navcore_ws/.venv/bin/python scripts/t4d_mh01_check.py [bag] [--frames N] [--calib FILE]
        ~/navcore_ws/.venv/bin/python scripts/t4d_mh01_check.py --selftest
Needs, in the venv:  pip install rosbags opencv-python-headless pyyaml     (ROS itself is not used)
Default bag: ~/euroc_data/MH_01_easy.bag. Default calibration: OpenVINS config/euroc_mav/kalibr_imucam_chain.yaml.

Tracker, close to OpenVINS TrackKLT: FAST corners spread over a 5x5 grid (200 points, at least 10 px apart),
pyramidal KLT 15x15, temporal RANSAC on undistorted points (fundamental matrix, 2 px), stereo KLT left -> right.
Per stereo observation: the Sampson distance to the calibrated epipolar line with the distortion Jacobian, one
sample of sigma^2 (estimator document, Prop. E2). Per tracked observation: the forward-backward error, a 2-dof sample
of a tracking-noise proxy (|e_FB|^2 / 4).
Heterogeneity: for features with at least 8 samples, y_j = log of the feature's noise level (bias-corrected for its
number of samples); var(y) minus the known sampling variance (trigamma) gives tau^2, the spread of the true
per-feature noise in log units. 'Within' removes the mean of each 10 s window first, so that noise changing over time
(which a per-frame method already handles) does not count. Per-feature noise beats one common value only if
tau > s, the estimator's own error spread (s = 0.16 to 0.30 in G1).
Primary measure: tau with a 0.5 px floor for error the stereo residual cannot see; 0 and 1.0 px are reported as bounds.
Writes results/t4d_mh01_check.txt and results/t4d_mh01_features.csv."""
import argparse, csv, math, os, sys, time
import numpy as np
from scipy.special import digamma, polygamma
from scipy.stats import spearmanr

RES = os.path.expanduser('~/navcore_ws/results')
WIN, LEVELS, NPTS, MINDIST, MIN_M, WINDOW_S = (15, 15), 4, 200, 10, 8, 10.0


# ---------------- camera model (radial-tangential, as OpenVINS) ----------------
def distort(n, c):
    fx, fy, cx, cy = c['K']; k1, k2, p1, p2 = c['D']
    x, y = n[:, 0], n[:, 1]
    r2 = x * x + y * y; g = 1 + k1 * r2 + k2 * r2 * r2
    return np.stack([fx * (x * g + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)) + cx,
                     fy * (y * g + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y) + cy], -1)


def undistort(z, c):
    fx, fy, cx, cy = c['K']; k1, k2, p1, p2 = c['D']
    xd, yd = (z[:, 0] - cx) / fx, (z[:, 1] - cy) / fy
    x, y = xd.copy(), yd.copy()
    for _ in range(40):
        r2 = x * x + y * y; g = 1 + k1 * r2 + k2 * r2 * r2
        x, y = (xd - (2 * p1 * x * y + p2 * (r2 + 2 * x * x))) / g, (yd - (p1 * (r2 + 2 * y * y) + 2 * p2 * x * y)) / g
    return np.stack([x, y], -1)


def jac(n, c, h=1e-7):
    J = np.zeros((len(n), 2, 2))
    for k in range(2):
        e = np.zeros(2); e[k] = h
        J[:, :, k] = (distort(n + e, c) - distort(n - e, c)) / (2 * h)
    return J


def load_calib(path):
    import yaml
    txt = ''.join(l for l in open(path) if not l.lstrip().startswith('%'))
    y = yaml.safe_load(txt)
    cams = []
    for k in ('cam0', 'cam1'):
        c = y[k]
        model = c.get('distortion_model', 'radtan')
        if model not in ('radtan', 'radial-tangential'):
            sys.exit(f'{k}: distortion model {model!r} not handled (radtan expected for EuRoC)')
        cams.append(dict(K=np.array(c['intrinsics'], float), D=np.array(c['distortion_coeffs'][:4], float),
                         T_I_C=np.array(c['T_imu_cam'], float)))
    T = np.linalg.inv(cams[1]['T_I_C']) @ cams[0]['T_I_C']          # camera 0 -> camera 1
    R01, t01 = T[:3, :3], T[:3, 3]
    tx = np.array([[0, -t01[2], t01[1]], [t01[2], 0, -t01[0]], [-t01[1], t01[0], 0]])
    return cams, tx @ R01, float(np.linalg.norm(t01))


def sampson_px2(z0, z1, cams, E):
    """one sample of sigma^2 (px^2) per stereo match, distorted pixel coordinates in"""
    n0, n1 = undistort(z0, cams[0]), undistort(z1, cams[1])
    x0, x1 = np.c_[n0, np.ones(len(n0))], np.c_[n1, np.ones(len(n1))]
    l1, l0 = x0 @ E.T, x1 @ E
    eps = np.sum(x1 * l1, 1)
    g0 = np.linalg.solve(np.transpose(jac(n0, cams[0]), (0, 2, 1)), l0[:, :2, None])[..., 0]
    g1 = np.linalg.solve(np.transpose(jac(n1, cams[1]), (0, 2, 1)), l1[:, :2, None])[..., 0]
    return eps ** 2 / (np.sum(g0 ** 2, 1) + np.sum(g1 ** 2, 1))


# ---------------- heterogeneity ----------------
def heterogeneity(t0, q, k, floor=0.0, window=WINDOW_S, nboot=500, seed=0):
    """t0: birth times; q: per-feature mean of per-sample variance estimates (px^2); k: total degrees of freedom;
    floor: noise floor F in px. Works on y_j = log sqrt(F^2 + sigma_j^2): differences well below F cannot matter.
    Returns tau, the spread of the true y_j, over the whole run and within windows, with a 95% bootstrap CI."""
    if floor == 0:
        y = 0.5 * (np.log(q) - (digamma(k / 2) - np.log(k / 2)))  # unbiased for log sigma
        v = polygamma(1, k / 2) / 4                                 # exact sampling variance
    else:
        y = 0.5 * np.log(floor ** 2 + q)
        v = q ** 2 / (2 * k * (floor ** 2 + q) ** 2)                # delta method
    w = np.floor((t0 - t0.min()) / window).astype(int)

    def within(idx):
        yy, vv, ww = y[idx], v[idx], w[idx]
        ss, dof, vs = 0.0, 0, []
        for g in np.unique(ww):
            s = ww == g
            if s.sum() >= 2:
                ss += np.sum((yy[s] - yy[s].mean()) ** 2); dof += s.sum() - 1; vs.append(vv[s])
        return ss / dof - np.concatenate(vs).mean() if dof > 0 else math.nan

    tau2_tot = np.var(y, ddof=1) - v.mean()
    tau2_w = within(np.arange(len(y)))
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(w == g) for g in np.unique(w)]
    boots = [within(np.concatenate([rng.choice(g, len(g)) for g in groups])) for _ in range(nboot)]
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    sq = lambda a: math.sqrt(a) if a > 0 else 0.0
    means = {g: y[w == g].mean() for g in np.unique(w)}
    return dict(n=len(y), tau_total=sq(tau2_tot), tau_within=sq(tau2_w), ci=(sq(lo), sq(hi)),
                yc=y - np.array([means[g] for g in w]), w=w)


def selftest():
    rng = np.random.default_rng(7)
    print('self-test: known per-feature spread, track lengths 8-40 frames, noise level drifting over time')
    for tau in (0.0, 0.1, 0.2, 0.4):
        n = 3000
        t0 = rng.uniform(0, 180, n); m = rng.integers(8, 41, n)
        logs = np.log(0.6) + 0.3 * np.sin(t0 / 30) + tau * rng.standard_normal(n)   # time drift + per-feature
        q = np.array([np.exp(2 * logs[j]) * rng.chisquare(1, m[j]).mean() for j in range(n)])
        txt = []
        for F in (0.0, 0.5):
            r = heterogeneity(t0, q, m.astype(float), floor=F, nboot=200)
            ytrue = logs if F == 0 else 0.5 * np.log(F ** 2 + np.exp(2 * logs))
            wq = np.floor(t0 / WINDOW_S).astype(int)
            truth = math.sqrt(np.sum([np.sum((ytrue[wq == g] - ytrue[wq == g].mean()) ** 2) for g in np.unique(wq)]) / (n - len(np.unique(wq))))
            txt.append(f'floor {F:.1f} px: estimated {r["tau_within"]:.3f} (CI {r["ci"][0]:.3f}-{r["ci"][1]:.3f}), true {truth:.3f}')
        print(f'  tau {tau:.2f} | ' + ' | '.join(txt))


# ---------------- data ----------------
def stereo_frames(bag):
    from pathlib import Path
    from rosbags.highlevel import AnyReader
    topics = ('/cam0/image_raw', '/cam1/image_raw')
    with AnyReader([Path(bag)]) as reader:
        conns = [c for c in reader.connections if c.topic in topics]
        if len(conns) < 2:
            sys.exit(f'{bag}: topics {topics} not found; topics are {sorted({c.topic for c in reader.connections})}')
        pend = {}
        for conn, _, raw in reader.messages(connections=conns):
            msg = reader.deserialize(raw, conn.msgtype)
            st = msg.header.stamp.sec + 1e-9 * msg.header.stamp.nanosec
            img = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.width)
            side = topics.index(conn.topic)
            other = pend.pop((st, 1 - side), None)
            if other is not None:
                yield (st, img, other) if side == 0 else (st, other, img)
            else:
                pend[(st, side)] = img
                if len(pend) > 50:
                    pend.pop(next(iter(pend)))


def topup(img, pts, num, grid=5):
    import cv2
    need = num - len(pts)
    if need <= 0:
        return np.zeros((0, 2), np.float32)
    mask = np.full(img.shape, 255, np.uint8)
    for x, y in pts:
        cv2.circle(mask, (int(x), int(y)), MINDIST, 0, -1)
    kps = cv2.FastFeatureDetector_create(threshold=20, nonmaxSuppression=True).detect(img, mask)
    h, w = img.shape
    cells = {}
    for k in kps:
        cells.setdefault((min(int(k.pt[0] * grid / w), grid - 1), min(int(k.pt[1] * grid / h), grid - 1)), []).append(k)
    per = max(1, int(math.ceil(need / (grid * grid))))
    new = []
    for ks in cells.values():
        taken = 0
        for k in sorted(ks, key=lambda k: -k.response):
            x, y = k.pt
            if taken >= per or len(new) >= need:
                break
            if mask[int(y), int(x)]:
                new.append((x, y)); taken += 1
                cv2.circle(mask, (int(x), int(y)), MINDIST, 0, -1)
    return np.array(new, np.float32).reshape(-1, 2)


def run(bag, calib, frames):
    import cv2
    cams, E, base = load_calib(calib)
    fmax = max(cams[0]['K'][:2].max(), cams[1]['K'][:2].max())
    lk = dict(winSize=WIN, maxLevel=LEVELS, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    feats, pts, ids, nid = {}, np.zeros((0, 2), np.float32), np.zeros(0, int), 0
    prev, nfr, t_first = None, 0, None
    stats = dict(stereo=0, d_over2=0, d_over10=0, temporal=0, ransac_drop=0)
    t_start = time.time()
    for st, L, R in stereo_frames(bag):
        t_first = st if t_first is None else t_first
        t = st - t_first
        if prev is not None and len(pts):
            p1, s1, _ = cv2.calcOpticalFlowPyrLK(prev, L, pts, None, **lk)
            pb, sb, _ = cv2.calcOpticalFlowPyrLK(L, prev, p1, None, **lk)
            h, w = L.shape
            ok = (s1[:, 0] == 1) & (sb[:, 0] == 1) & (p1[:, 0] >= 0) & (p1[:, 0] < w) & (p1[:, 1] >= 0) & (p1[:, 1] < h)
            if ok.sum() >= 8:
                n0, n1 = undistort(pts[ok].astype(float), cams[0]), undistort(p1[ok].astype(float), cams[0])
                F, inl = cv2.findFundamentalMat(n0, n1, cv2.FM_RANSAC, 2.0 / fmax, 0.999)
                if inl is not None:
                    keep = np.flatnonzero(ok)
                    stats['ransac_drop'] += int((inl[:, 0] == 0).sum())
                    ok[keep[inl[:, 0] == 0]] = False
            fb = np.linalg.norm(pb - pts, axis=1)
            for j in np.flatnonzero(ok):
                if fb[j] <= 10:
                    feats[ids[j]]['fb'].append(fb[j] ** 2 / 4)
            stats['temporal'] += int(ok.sum())
            pts, ids = p1[ok], ids[ok]
        new = topup(L, pts, NPTS)
        if len(new):
            eig = cv2.cornerMinEigenVal(L, 3)
            for x, y in new:
                feats[nid] = dict(t0=t, epi=[], epi2=[], fb=[], eig=float(eig[int(y), int(x)]), xy=[])
                nid += 1
            pts = np.vstack([pts, new]); ids = np.concatenate([ids, np.arange(nid - len(new), nid)])
        if len(pts):
            pr, sr, _ = cv2.calcOpticalFlowPyrLK(L, R, pts, pts.copy(), flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **lk)
            h, w = R.shape
            ok = (sr[:, 0] == 1) & (pr[:, 0] >= 0) & (pr[:, 0] < w) & (pr[:, 1] >= 0) & (pr[:, 1] < h)
            if ok.any():
                d2 = sampson_px2(pts[ok].astype(float), pr[ok].astype(float), cams, E)
                stats['stereo'] += len(d2); stats['d_over2'] += int((d2 > 4).sum()); stats['d_over10'] += int((d2 > 100).sum())
                for j, v in zip(np.flatnonzero(ok), d2):
                    f = feats[ids[j]]
                    if v <= 100:
                        f['epi'].append(v)
                    if v <= 4:
                        f['epi2'].append(v)
                    f['xy'].append(pts[j])
        prev = L
        nfr += 1
        if nfr % 500 == 0:
            print(f'  {nfr} frames, {t:.0f} s of data, {time.time() - t_start:.0f} s elapsed', flush=True)
        if frames and nfr >= frames:
            break
    return feats, stats, nfr, base, cams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bag', nargs='?', default=os.path.expanduser('~/euroc_data/MH_01_easy.bag'))
    ap.add_argument('--calib', default=os.path.expanduser('~/navcore_ws/src/open_vins/config/euroc_mav/kalibr_imucam_chain.yaml'))
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--out', default=RES)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    t_start = time.time()
    feats, st, nfr, base, cams = run(a.bag, a.calib, a.frames)
    lines = []
    out = lambda s='': (lines.append(s), print(s))
    out(f'T.4d MH_01 check: {os.path.basename(a.bag)}, {nfr} stereo frames, {len(feats)} features, baseline {base:.3f} m')
    out(f'Stereo matches: {st["stereo"]}; Sampson distance above 2 px (what OpenVINS RANSAC would drop): '
        f'{100 * st["d_over2"] / max(st["stereo"], 1):.1f}%; above 10 px (gross mismatches, excluded): {100 * st["d_over10"] / max(st["stereo"], 1):.2f}%')
    out(f'Temporal tracks kept: {st["temporal"]}; dropped by temporal RANSAC: {st["ransac_drop"]}')
    out()
    res = {}
    out('Per-feature spread tau within 10 s windows (95% CI), by assumed noise floor F (error not seen by the stereo residual).')
    out('Primary: F = 0.5 px. For comparison, tau in G1 was 0.11 / 0.20 / 0.46 at bad 1.25 / 1.5 / 2.5 px (half the features noisier).')
    for key, dof, lab in (('epi', 1, 'epipolar, matches up to 10 px (primary)'), ('epi2', 1, 'epipolar, matches up to 2 px (after RANSAC)'),
                          ('fb', 2, 'forward-backward tracking error')):
        sel = [f for f in feats.values() if len(f[key]) >= MIN_M]
        if len(sel) < 50:
            out(f'  {lab}: only {len(sel)} features with >= {MIN_M} samples'); continue
        t0 = np.array([f['t0'] for f in sel]); q = np.array([np.mean(f[key]) for f in sel])
        k = dof * np.array([len(f[key]) for f in sel], float)
        rr = {F: heterogeneity(t0, q, k, floor=F) for F in (0.0, 0.5, 1.0)}
        res[key] = (sel, rr, q, k, t0)
        sig = np.sqrt(q)
        out(f'  {lab}: {len(sel)} features; per-feature noise median {np.median(sig):.2f} px (10-90%: {np.percentile(sig, 10):.2f}-{np.percentile(sig, 90):.2f})')
        out('      ' + ' | '.join(f'floor {F:.1f}: {r["tau_within"]:.3f} ({r["ci"][0]:.3f}-{r["ci"][1]:.3f})' for F, r in rr.items()))
    out()
    if 'epi' in res:
        sel, rr, q, k, t0 = res['epi']
        sig = np.sqrt(q)
        rng = np.random.default_rng(1)
        w = rr[0.0]['w']
        med = {g: np.median(sig[w == g]) for g in np.unique(w)}
        for thr in (1.0, 2.0):
            exp = np.mean([np.mean(np.array([med[g] for g in w]) * np.sqrt(rng.chisquare(k) / k) > thr) for _ in range(20)])
            out(f'Features with epipolar noise above {thr:.0f} px: {100 * np.mean(sig > thr):.1f}% (if all features in a window shared its median level: {100 * exp:.1f}%)')
    if 'epi' in res and 'fb' in res:
        a_ids = {id(f): i for i, f in enumerate(res['epi'][0])}
        ye, yf = res['epi'][1][0.0]['yc'], res['fb'][1][0.0]['yc']
        pairs = [(ye[a_ids[id(f)]], yf[j]) for j, f in enumerate(res['fb'][0]) if id(f) in a_ids]
        if len(pairs) >= 30:
            rho, p = spearmanr([x for x, _ in pairs], [y for _, y in pairs])
            out(f'Agreement of the two signals per feature (within-window ranks): Spearman {rho:.2f} (p {p:.2g}, {len(pairs)} features)')
        eig = np.array([f['eig'] for f in res['epi'][0]])
        rho2, p2 = spearmanr(eig, ye)
        c0 = cams[0]['K'][2:4]
        rad = np.array([np.linalg.norm(np.mean(f['xy'], 0) - c0) for f in res['epi'][0]])
        rho3, p3 = spearmanr(rad, ye)
        out(f'Epipolar noise against corner strength at birth: Spearman {rho2:.2f} (p {p2:.2g}); against distance from the image centre: {rho3:.2f} (p {p3:.2g})')
    if 'epi' in res:
        tau = res['epi'][1][0.5]['tau_within']
        out()
        out(f'Expected effect of per-feature noise against one common value at tau = {tau:.3f} (static least squares, negative = gain):')
        for s_ in (0.16, 0.30):
            out(f'    estimator spread s {s_:.2f}: {100 * (math.exp(2 * (s_ * s_ - tau * tau)) - 1):+.1f}%')
        verdict = ('room for per-feature gains (tau >= 0.2): G1b is worth running' if tau >= 0.2 else
                   'little room on MH_01 (tau < 0.1): check V1_03 / V2_03 before concluding; lead with robustness' if tau < 0.1 else
                   'marginal room (0.1 <= tau < 0.2): G1b must above all avoid losing at low contrast')
        out(f'Rule fixed before running (epipolar, floor 0.5 px): {verdict}')
    out(f'({time.time() - t_start:.0f} s)')
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, 't4d_mh01_check.txt'), 'w').write('\n'.join(lines) + '\n')
    with open(os.path.join(a.out, 't4d_mh01_features.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['feature', 't0', 'n_epi', 'sigma_epi_px', 'n_fb', 'sigma_fb_px', 'min_eig', 'mean_x', 'mean_y'])
        for i, f in feats.items():
            if len(f['epi']) >= 2 or len(f['fb']) >= 2:
                xy = np.mean(f['xy'], 0) if f['xy'] else (math.nan, math.nan)
                wr.writerow([i, f'{f["t0"]:.3f}', len(f['epi']), f'{math.sqrt(np.mean(f["epi"])):.4f}' if f['epi'] else '',
                             len(f['fb']), f'{math.sqrt(np.mean(f["fb"])):.4f}' if f['fb'] else '', f'{f["eig"]:.5f}', f'{xy[0]:.1f}', f'{xy[1]:.1f}'])



if __name__ == '__main__':
    main()
