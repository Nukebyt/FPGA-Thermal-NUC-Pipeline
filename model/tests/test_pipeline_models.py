"""pipeline_int (vectorised) vs pipeline_ref (scalar loops) vs scipy labelling. Small frames: ref is slow."""
import numpy as np
import pytest

from model import pipeline_int as pi, pipeline_ref as pr, noise_model as nm, scenes


def small_cfg(**kw):
    base = dict(W=48, H=36, DET_WARM=3, MIN_AREA=4, T_MASK=300, NL=16, MAXOBJ=16)
    base.update(kw)
    return pi.Cfg(**base)


def make_frames(c, T=14, preset="severe", seed=2):
    scene, gt, _ = scenes.make_scene(T, shape=(c.H, c.W), seed=seed, n_blobs=2)
    raw, _ = nm.add_noise(scene, nm.preset(preset, dead_rate=0.01, hot_rate=0.01, seed=seed))
    return raw


@pytest.mark.parametrize("kw", [dict(), dict(nuc_en=False), dict(bp_en=False), dict(morph_en=False),
                                dict(ACT_THR=0), dict(learn_en=False), dict(LEARN_N=5)])
def test_int_equals_ref(kw):
    c = small_cfg(**kw)
    frames = make_frames(c)
    si, sr = pi.State.init(c), pi.State.init(c)
    for t, f in enumerate(frames):
        a = pi.frame_step(c, si, f)
        b = pr.frame_ref(c, sr, f)
        assert np.array_equal(a.y14, b["y14"]), f"y14 frame {t}"
        assert np.array_equal(a.raw_mask, b["raw_mask"]), f"raw mask frame {t}"
        assert np.array_equal(a.mask, b["mask"]), f"mask frame {t}"
        assert np.array_equal(a.bad, b["bad"]), f"bad frame {t}"
        for name in ("o", "g", "bpc", "B"):
            assert np.array_equal(getattr(si, name), getattr(sr, name)), f"{name} frame {t}"
        assert (si.lim_q, si.act, si.n, si.lcnt) == (sr.lim_q, sr.act, sr.n, sr.lcnt), f"ctl frame {t}"
        assert a.sum_abs_e == b["sum_abs_e"] and a.sum_act == b["sum_act"]
        assert a.learning == b["learning"], f"learning frame {t}"


def test_learning_window():
    """LEARN_N counts only frames in which learning ran; after N of them o, g stop moving (bpc keeps counting)."""
    from dataclasses import replace
    c = small_cfg(LEARN_N=4)
    frames = make_frames(c, T=12)
    s = pi.State.init(c)
    learn_pattern = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1]       # learn_en per frame (switch toggled)
    ran = []
    for f, le in zip(frames, learn_pattern):
        o_before, g_before = s.o.copy(), s.g.copy()
        out = pi.frame_step(replace(c, learn_en=bool(le)), s, f)
        ran.append(out.learning)
        if not out.learning:
            assert np.array_equal(s.o, o_before) and np.array_equal(s.g, g_before)
    # frames 0, 2, 3, 5 are the four learning frames; nothing after them learns although learn_en is set again
    assert ran == [True, False, True, True, False, True] + [False] * 6
    assert s.lcnt == 4
    # LEARN_N = 0: no limit
    s0 = pi.State.init(small_cfg(LEARN_N=0))
    assert all(pi.frame_step(small_cfg(LEARN_N=0), s0, f).learning for f in frames)


def test_models_actually_exercise_the_paths():
    """Guard against vacuous agreement: the default config must flag bad pixels, move coefficients and find a mask."""
    c = small_cfg()
    frames = make_frames(c, T=16)
    s = pi.State.init(c)
    outs = [pi.frame_step(c, s, f) for f in frames]
    assert s.o.any() and (s.g != (1 << c.GF)).any()
    assert any(o.bad.any() for o in outs)
    assert any(o.mask.any() for o in outs)


def test_ccl_vs_scipy_random():
    rng = np.random.default_rng(5)
    c = small_cfg(MIN_AREA=1, NL=64, MAXOBJ=64)
    n_checked = 0
    for _ in range(60):
        m = np.zeros((c.H, c.W), bool)
        for _k in range(rng.integers(1, 7)):             # a few random rectangles (some overlap -> merges)
            y0, x0 = rng.integers(0, c.H - 3), rng.integers(0, c.W - 3)
            m[y0:y0 + rng.integers(1, 12), x0:x0 + rng.integers(1, 15)] = True
        m &= rng.random(m.shape) < 0.85                    # ragged holes force label merges
        got, n, ovf = pi.ccl_boxes(c, m)
        if ovf:
            continue
        assert sorted(got) == pr.boxes_ref(c, m)
        assert n == len(got)
        n_checked += 1
    assert n_checked > 10


def test_ccl_shapes():
    c = small_cfg(MIN_AREA=1)
    m = np.zeros((c.H, c.W), bool)
    m[2:6, 2:6] = True                      # block
    m[10:12, 5:30] = True                   # wide bar
    m[20:30, 10] = True                     # thin vertical line
    m[20, 10:20] = True                     # joined into an L
    m[30:34, 40:48] = True                  # touches right border
    m[0, 20:22] = True                      # touches top border
    m[25:28, 30:33] = True
    m[27:30, 32:36] = True                  # overlapping pair that needs a merge
    got, n, ovf = pi.ccl_boxes(c, m)
    assert not ovf and sorted(got) == pr.boxes_ref(c, m)


def test_ccl_u_shape_merge():
    c = small_cfg(MIN_AREA=1)
    m = np.zeros((c.H, c.W), bool)
    m[5:15, 5] = True
    m[5:15, 15] = True
    m[14, 5:16] = True                      # U: two arms start separate, merge on the last row
    got, n, ovf = pi.ccl_boxes(c, m)
    assert got == [(5, 5, 15, 14, int(m.sum()))] and n == 1 and not ovf


def test_ccl_overflow_flag():
    c = small_cfg(MIN_AREA=1, NL=4, MAXOBJ=2)
    m = np.zeros((c.H, c.W), bool)
    for k in range(8):
        m[2, 4 * k:4 * k + 2] = True        # 8 separate objects on one line, only 4 label slots
    got, n, ovf = pi.ccl_boxes(c, m)
    assert ovf and len(got) <= 2


def test_ccl_slot_reuse_after_merge_is_safe():
    rng = np.random.default_rng(9)
    c = small_cfg(MIN_AREA=1, NL=16, MAXOBJ=64)
    ok = 0
    for _ in range(200):
        m = rng.random((c.H, c.W)) < 0.05
        m = m | (np.roll(m, 1, 0) & (rng.random(m.shape) < 0.7)) | np.roll(m, 1, 1)
        got, n, ovf = pi.ccl_boxes(c, m)
        if not ovf:
            assert sorted(got) == pr.boxes_ref(c, m)
            ok += 1
    assert ok > 20
