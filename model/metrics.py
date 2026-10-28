"""Metrics (roadmap task 1.7).

Unobservable-affine note: scene-based NUC cannot recover the absolute gain/offset of the whole image
(any global a*y+b is equally 'uniform'), so alongside the raw RMSE we report RMSE after a per-frame
least-squares global affine alignment to the clean image ('aligned' variants). Quote the aligned numbers
for NUC quality and say so.
"""
import numpy as np


def _f(a):
    return np.asarray(a, dtype=np.float64)


def rmse(a, b, mask=None):
    d = _f(a) - _f(b)
    if mask is not None:
        d = d[mask]
    return float(np.sqrt(np.mean(d * d)))


def psnr(a, b, peak, mask=None):
    r = rmse(a, b, mask)
    return float("inf") if r == 0 else float(20 * np.log10(peak / r))


def align_affine(y, ref, mask=None):
    """Least-squares global y' = a*y + b matching ref (per frame). Returns y'."""
    y = _f(y)
    ref = _f(ref)
    ys, rs = (y[mask], ref[mask]) if mask is not None else (y.ravel(), ref.ravel())
    ym, rm = ys.mean(), rs.mean()
    var = ((ys - ym) ** 2).mean()
    a = 0.0 if var == 0 else ((ys - ym) * (rs - rm)).mean() / var
    return a * (y - ym) + rm


def rmse_aligned(y, ref, mask=None):
    return rmse(align_affine(y, ref, mask), ref, mask)


def roughness(y):
    """Cunningham roughness index rho = (|h*I|_1 + |h^T*I|_1) / |I|_1 with h = [1, -1]. Lower = smoother.
    Scale-free, so it needs no ground truth; it also rewards over-smoothing, so read it next to RMSE."""
    y = _f(y)
    num = np.abs(np.diff(y, axis=1)).sum() + np.abs(np.diff(y, axis=0)).sum()
    return float(num / np.abs(y).sum())


def sequence_curve(outputs, clean, mask_fn=None, aligned=True):
    """RMSE per frame -> np.array (T,). `mask_fn(t)` optionally gives a validity mask (e.g. exclude bad pixels)."""
    fn = rmse_aligned if aligned else rmse
    return np.array([fn(outputs[t], clean[t], None if mask_fn is None else mask_fn(t))
                     for t in range(len(outputs))])


def convergence_frame(curve, threshold, hold=10):
    """First frame index after which the curve stays <= threshold for `hold` frames; None if never."""
    ok = curve <= threshold
    for t in range(len(curve) - hold + 1):
        if ok[t:t + hold].all():
            return t
    return None


def fixed_pattern_residual(y, clean):
    """Temporal-mean of (y - clean) over the clip, then its spatial std: the residual FPN (counts)."""
    d = _f(y) - _f(clean)
    return float(d.mean(axis=0).std())


def prf(pred, gt, valid=None):
    """Precision/recall/F1/false-alarm-rate of a binary detection stack. `valid` masks pixels that count
    (CDnet: exclude outside-ROI and unknown pixels). FAR = FP/(FP+TN)."""
    pred = np.asarray(pred, bool)
    gt = np.asarray(gt, bool)
    if valid is None:
        valid = np.ones_like(gt)
    tp = int((pred & gt & valid).sum())
    fp = int((pred & ~gt & valid).sum())
    fn = int((~pred & gt & valid).sum())
    tn = int((~pred & ~gt & valid).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    re = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * re / (pr + re) if pr + re else 0.0
    far = fp / (fp + tn) if fp + tn else 0.0
    return dict(precision=pr, recall=re, f1=f1, far=far, tp=tp, fp=fp, fn=fn, tn=tn)


def ghost_amplitude(outputs, clean, footprint, frames):
    """Mean (output - clean) inside `footprint` (bool HxW, where a stationary object used to be, eroded by the
    caller) over `frames` (indices after the object left). Burn-in shows as a persistent non-zero value.
    Each frame is first aligned to the clean frame with a global affine fit so the unobservable DC does not count."""
    v = []
    for t in frames:
        a = align_affine(outputs[t], clean[t])
        v.append((a - _f(clean[t]))[footprint].mean())
    return float(np.mean(v))
