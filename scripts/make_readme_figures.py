r"""Figures for the README (docs/img/fig_*.png), made from the project's own result files and the board captures.

  .venv\Scripts\python.exe scripts\make_readme_figures.py            # everything that has its inputs
  .venv\Scripts\python.exe scripts\make_readme_figures.py --only warmup,tmask

Inputs: docs/results/{nuc_study,tmask_sweep,cdnet_eval,resources,resources_soc}.md (written by the study scripts), the board
captures work/<clip>.grab.npz (scripts/capture_gifs.py) with the clips and ground truth in data/clips, and a run of the bit-accurate
system model for the warm-up figure. Numbers that are measured on the board are labelled as such in the figure titles."""
import argparse
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "host"))
OUT = os.path.join(ROOT, "docs", "img")
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, GREEN, PURPLE, RED, GREY = "#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626", "#6b7280"
SEQ_COL = {"corridor": BLUE, "diningRoom": ORANGE, "lakeSide": PURPLE, "library": GREEN, "park": RED}
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "font.size": 10.5, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelcolor": "#111827", "text.color": "#111827",
    "axes.edgecolor": "#9ca3af", "xtick.color": "#374151", "ytick.color": "#374151", "axes.grid": True, "grid.color": "#e5e7eb",
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
})


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.relpath(p, ROOT))


def md_rows(path, header_start):
    """Rows (list of cell lists) of the first markdown table whose header row starts with header_start."""
    lines = open(os.path.join(ROOT, path), encoding="utf-8").read().splitlines()
    for i, l in enumerate(lines):
        if l.startswith("|") and l.strip("| ").startswith(header_start):
            hdr = [c.strip() for c in l.strip().strip("|").split("|")]
            rows = []
            for r in lines[i + 2:]:
                if not r.startswith("|"):
                    break
                rows.append([c.strip() for c in r.strip().strip("|").split("|")])
            return hdr, rows
    raise KeyError(header_start)


# ------------------------------------------------------------------------------------------------ NUC error (float model study)
def fig_nuc():
    txt = open(os.path.join(ROOT, "docs/results/nuc_study.md"), encoding="utf-8").read()
    secs = re.split(r"\n## ", txt)[1:]
    conds, none, nuc = [], [], []
    for s in secs:
        head = s.splitlines()[0]
        m = re.match(r"(moving camera|static camera), (\w+) \(raw RMSE (\d+)", head)
        if not m:
            continue
        vals = {}
        for l in s.splitlines():
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            if len(c) >= 2 and c[0] in ("none", "lms adapt-clip"):
                vals[c[0]] = float(c[1])
        if len(vals) == 2:
            conds.append((m.group(1).split()[0], m.group(2)))
            none.append(vals["none"]); nuc.append(vals["lms adapt-clip"])
    fig, ax = plt.subplots(figsize=(9, 3.9))
    x = np.arange(len(conds))
    ax.bar(x - 0.2, none, 0.4, color="#9ca3af", label="no correction")
    ax.bar(x + 0.2, nuc, 0.4, color=ORANGE, label="scene-based NUC (as built in the FPGA)")
    for xi, a, b in zip(x, none, nuc):
        ax.text(xi - 0.2, a + 4, "%d" % a, ha="center", fontsize=9, color="#374151")
        ax.text(xi + 0.2, b + 4, "%d" % b, ha="center", fontsize=9, color="#9a3412", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(["%s camera\n%s sensor" % (c, l) for c, l in conds], fontsize=9.5)
    ax.set_ylabel("error vs clean picture, counts (lower is better)")
    ax.set_title("Fixed-pattern noise removed without a shutter (float model, 300 frames)")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    save(fig, "fig_nuc_rmse.png")


# ------------------------------------------------------------------------------------------------ detector threshold sweep
def fig_tmask():
    hdr, rows = md_rows("docs/results/tmask_sweep.md", "sequence | 32") if False else md_rows("docs/results/tmask_sweep.md", "sequence")
    ts = [int(h) for h in hdr[1:13]]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    for r in rows:
        name = r[0]
        f1 = [float(v) for v in r[1:13]]
        ax.plot(ts, f1, "-o", ms=4, lw=2, color=SEQ_COL[name], label=name)
        k = int(np.argmax(f1))
        ax.plot([ts[k]], [f1[k]], "o", ms=11, mfc="none", mec=SEQ_COL[name], mew=2)
        off = {"corridor": (22, -16), "park": (-22, -16)}.get(name, (0, 10))
        ax.annotate("%.2f" % f1[k], (ts[k], f1[k]), textcoords="offset points", xytext=off, ha="center", fontsize=9, color=SEQ_COL[name], fontweight="bold")
    ax.axvline(400, color=GREY, ls="--", lw=1.2)
    ax.text(405, 0.04, "default\nT_MASK = 400", color=GREY, fontsize=9)
    ax.set_xscale("log")
    ax.set_xticks(ts)
    ax.set_xticklabels([str(t) for t in ts], fontsize=9)
    ax.minorticks_off()
    ax.set_xlabel("detector threshold T_MASK (counts, a run-time register)")
    ax.set_ylabel("F1 vs CDnet ground truth")
    ax.set_ylim(0, 0.95)
    ax.set_title("One threshold does not fit every scene (circles = best value per sequence)")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.17))
    save(fig, "fig_tmask.png")


# ------------------------------------------------------------------------------------------------ detector scores per sequence / noise condition
def fig_cdnet():
    hdr, rows = md_rows("docs/results/cdnet_eval.md", "sequence")
    seqs = ["library", "diningRoom", "corridor", "park", "lakeSide"]
    conds = [("clean", "-", "clean footage"), ("noisy", "typical", "+ simulated sensor noise"), ("noisy+NUC", "typical", "+ noise + NUC")]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    w = 0.26
    for j, (cname, noise, lab) in enumerate(conds):
        vals = []
        for s in seqs:
            v = [float(r[3]) for r in rows if r[0] == s and r[2] == cname and r[1] == noise][0]
            vals.append(v)
        b = ax.bar(np.arange(len(seqs)) + (j - 1) * w, vals, w, color=["#9ca3af", "#fdba74", ORANGE][j], label=lab)
        for xi, v in zip(np.arange(len(seqs)) + (j - 1) * w, vals):
            ax.text(xi, v + 0.012, "%.2f" % v, ha="center", fontsize=8.5)
    ax.set_xticks(np.arange(len(seqs)))
    ax.set_xticklabels(seqs)
    ax.set_ylabel("F1 of the motion mask (T_MASK = 400)")
    ax.set_ylim(0, 0.95)
    ax.set_title("Detector score per sequence: noise and NUC leave it unchanged")
    ax.legend(loc="upper right", ncol=3, fontsize=9, bbox_to_anchor=(1.0, 1.0))
    ax.grid(axis="x", visible=False)
    save(fig, "fig_cdnet_conditions.png")


# ------------------------------------------------------------------------------------------------ FPGA resources
def fig_resources():
    def parse(path):
        t = open(os.path.join(ROOT, path), encoding="utf-8").read()
        g = lambda key: [int(x.replace(",", "")) for x in re.search(key + r" : ([\d,]+) / ([\d,]+)", t).groups()]
        return {"ALMs": g(r"Logic utilization \(in ALMs\)"), "RAM blocks (M10K)": g(r"Total RAM Blocks"), "block memory bits": g(r"Total block memory bits"),
                "DSP blocks": g(r"Total DSP Blocks"), "pins": g(r"Total pins")}
    b5, b6 = parse("docs/results/resources.md"), parse("docs/results/resources_soc.md")
    names = list(b5)
    fig, ax = plt.subplots(figsize=(9, 3.9))
    y = np.arange(len(names))
    for dy, d, col, lab in ((-0.19, b5, "#9ca3af", "build 5: design + JTAG host bus"), (0.19, b6, ORANGE, "build 6: + HPS (ARM) bridge and frame store")):
        pct = [100.0 * d[n][0] / d[n][1] for n in names]
        ax.barh(y + dy, pct, 0.36, color=col, label=lab)
        for yi, n, p in zip(y + dy, names, pct):
            ax.text(p + 1, yi, "{:,} / {:,} ({:d} %)".format(d[n][0], d[n][1], int(round(p))), va="center", fontsize=8.5)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlim(0, 150)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% of the Cyclone V 5CSXFC6D6F31C6")
    ax.axvline(100, color=RED, lw=1)
    ax.set_title("Fits in a small device, but the block RAM is full (551 of 553)")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="y", visible=False)
    save(fig, "fig_resources.png")


# ------------------------------------------------------------------------------------------------ timing
def fig_timing():
    items = [("FPGA: end of frame -> box list\n(8,724 cycles, min = max over 69,510 frames)", 0.349, GREEN),
             ("ARM: write one frame through the HPS bridge", 10.92, BLUE),
             ("ARM: read one picture back for the viewer", 14.84, PURPLE)]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    for i, (lab, v, col) in enumerate(items):
        ax.barh(i, v, 0.55, color=col)
        ax.text(v + 0.25, i, "%.3g ms" % v, va="center", fontsize=10, fontweight="bold")
    ax.axvline(16.667, color=RED, lw=1.5, ls="--")
    ax.text(16.95, 0.45, "one 60 Hz\nframe = 16.7 ms", color=RED, fontsize=9, va="center")
    ax.set_yticks(range(3))
    ax.set_yticklabels([i[0] for i in items], fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 21)
    ax.set_xlabel("milliseconds")
    ax.set_title("Timing measured on the board (FPGA latency: build 5; ARM times: build 6)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_timing.png")


# ------------------------------------------------------------------------------------------------ the chase protocol
def fig_chase():
    fig, ax = plt.subplots(figsize=(9, 3.9))
    t = np.linspace(0, 3, 3000)
    scan = (t % 1.0) * 240
    lag = 14
    writer = np.where(scan - lag >= 0, scan - lag, np.nan)
    for k in range(3):
        sl = (t >= k) & (t < k + 1)
        ax.plot(t[sl], scan[sl], color=BLUE, lw=2.4, label="scan: row being read out" if k == 0 else None)
        ax.plot(t[sl], writer[sl], color=ORANGE, lw=2.4, label="ARM: row being rewritten with the next frame" if k == 0 else None)
        ax.fill_between(t[sl], writer[sl], 240, color="#fed7aa", alpha=0.45, lw=0)
        ax.fill_between(t[sl], 0, writer[sl], color="#dbeafe", alpha=0.7, lw=0)
    ax.text(0.64, 55, "rows already rewritten:\nnew frame (shown in k+1)", ha="center", fontsize=8.5, color="#1e3a8a")
    ax.text(0.36, 205, "rows still to be read:\nold frame (shown in k)", ha="center", fontsize=8.5, color="#9a3412")
    for k in range(1, 3):
        ax.axvline(k, color="#9ca3af", lw=1, ls=":")
    ax.set_xticks([0.5, 1.5, 2.5])
    ax.set_xticklabels(["display frame k\nshows the old frame", "display frame k+1\nshows only new rows", "display frame k+2"], fontsize=9.5)
    ax.set_ylabel("frame store row")
    ax.set_ylim(0, 240)
    ax.set_xlim(0, 3)
    ax.set_title("No second frame buffer: the writer follows the scan, so a frame is never torn (schematic)")
    ax.legend(loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.4))
    ax.grid(False)
    save(fig, "fig_chase.png")


# ------------------------------------------------------------------------------------------------ clean | raw | NUC, from the board
def fig_compare():
    import thermal_palette as tp
    name, clipf, start, step, k = "diningRoom", "diningRoom_600_400", 100, 5, 40
    z = np.load(os.path.join(ROOT, "work", name + ".grab.npz"))
    clip = np.fromfile(os.path.join(ROOT, "data", "clips", clipf + ".u8"), np.uint8).reshape(-1, 240, 320)
    clean, raw, cor = clip[start + step * k], z["raw"][k], z["cor"][k]
    boxes = [tuple(int(v) for v in b) for b in z["boxes"][k] if b[0] >= 0]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.5))
    for ax, img, ttl in zip(axs, (clean, raw, cor), ("source footage (no sensor noise)", "what the simulated sensor delivers", "after the FPGA's NUC (+ motion boxes)")):
        ax.imshow(tp.colour(img, tp.window([img[::2, ::2]])), interpolation="nearest")
        ax.set_title(ttl, fontsize=10.5)
        ax.axis("off")
    for (x0, y0, x1, y1) in boxes:
        axs[2].add_patch(plt.Rectangle((x0 - 0.5, y0 - 0.5), x1 - x0 + 1, y1 - y0 + 1, fill=False, ec="#22ff22", lw=1.4))
    fig.suptitle("Same frame of the diningRoom clip; the last two panels were read back from the board", fontsize=11, y=1.02)
    fig.tight_layout()
    save(fig, "fig_nuc_compare.png")


# ------------------------------------------------------------------------------------------------ board boxes vs ground truth
CLIPS = {"library": ("library_720_400", 130), "corridor": ("corridor_430_400", 120), "diningRoom": ("diningRoom_600_400", 100),
         "park": ("park_100_450", 40), "lakeSide": ("lakeSide_1600_400", 100)}


def board_vs_gt():
    res = {}
    for name, (clipf, start) in CLIPS.items():
        p = os.path.join(ROOT, "work", name + ".grab.npz")
        if not os.path.exists(p):
            continue
        z = np.load(p)
        step = int(z["step"])
        gt = np.fromfile(os.path.join(ROOT, "data", "clips", clipf + ".gt.u8"), np.uint8).reshape(-1, 240, 320)
        person_f = hit_f = bg_f = fa_f = 0
        inside = area = 0
        cov = []
        for k in range(len(z["raw"])):
            g = gt[start + step * k]
            valid = (g != 2).mean() > 0.9
            if not valid:
                continue
            m = np.zeros((240, 320), bool)
            nb = 0
            for b in z["boxes"][k]:
                if b[0] >= 0:
                    m[b[1]:b[3] + 1, b[0]:b[2] + 1] = True
                    nb += 1
            pp = int((g == 1).sum())
            if pp > 300:
                person_f += 1
                c = float(((g == 1) & m).sum()) / pp
                cov.append(c)
                hit_f += c > 0.2
                inside += int(((g == 1) & m).sum())
                area += int(m.sum())
            elif pp < 20:
                bg_f += 1
                fa_f += nb > 0
        res[name] = dict(person=person_f, hit=hit_f, bg=bg_f, fa=fa_f, cov=float(np.mean(cov)) if cov else float("nan"),
                         tight=100.0 * inside / max(1, area))
    return res


def fig_board_gt():
    res = board_vs_gt()
    if not res:
        print("no board captures in work/: skipped fig_board_vs_gt")
        return
    names = [n for n in ("library", "corridor", "diningRoom", "park", "lakeSide") if n in res]
    fig, axs = plt.subplots(1, 2, figsize=(10.5, 3.9))
    x = np.arange(len(names))
    cov = [100 * res[n]["cov"] for n in names]
    hit = [100.0 * res[n]["hit"] / max(1, res[n]["person"]) for n in names]
    axs[0].bar(x - 0.2, hit, 0.4, color=ORANGE, label="frames with a person that got a box on them")
    axs[0].bar(x + 0.2, cov, 0.4, color=BLUE, label="person pixels inside a box")
    for xi, a, b in zip(x, hit, cov):
        axs[0].text(xi - 0.2, a + 1.5, "%d%%" % round(a), ha="center", fontsize=8.5)
        axs[0].text(xi + 0.2, b + 1.5, "%d%%" % round(b), ha="center", fontsize=8.5)
    axs[0].set_xticks(x)
    axs[0].set_xticklabels(names, fontsize=9)
    axs[0].set_ylim(0, 112)
    axs[0].set_title("Person detected (board output)")
    axs[0].legend(fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=1)
    axs[0].grid(axis="x", visible=False)
    tight = [res[n]["tight"] for n in names]
    axs[1].bar(x, tight, 0.5, color=PURPLE)
    for xi, a_ in zip(x, tight):
        axs[1].text(xi, a_ + 1.5, "%d%%" % round(a_), ha="center", fontsize=9)
    axs[1].set_xticks(x)
    axs[1].set_xticklabels(names, fontsize=9)
    axs[1].set_ylim(0, 112)
    axs[1].set_title("How tight the boxes are")
    axs[1].set_ylabel("share of box area that is person")
    axs[1].grid(axis="x", visible=False)
    fig.suptitle("Boxes read from the board against the CDnet ground truth (50 frames per clip, every 5th source frame; boxes are rectangles)", fontsize=11, y=1.03)
    fig.tight_layout()
    save(fig, "fig_board_vs_gt.png")
    for n in names:
        r = res[n]
        print("  %-10s person frames %2d hit %2d (%.0f %%)  pixel coverage %.0f %%   no-person frames %2d with boxes %2d" %
              (n, r["person"], r["hit"], 100.0 * r["hit"] / max(1, r["person"]), 100 * r["cov"], r["bg"], r["fa"]))


# ------------------------------------------------------------------------------------------------ warm-up (bit-accurate model)
def fig_warmup():
    from model import display_model as dm, pipeline_int as pi, sensor_emu as se
    clip = np.fromfile(os.path.join(ROOT, "data", "clips", "library_720_400.u8"), np.uint8).reshape(-1, 240, 320)
    gt = (np.fromfile(os.path.join(ROOT, "data", "clips", "library_720_400.gt.u8"), np.uint8).reshape(-1, 240, 320) == 1)
    S = len(clip) * 2
    emu = se.SensorEmu(None, "typical", scene8=clip[0], obj_en=False)
    m = dm.SystemModel(emu, pi.Cfg(T_MASK=640))
    m.scene_fn = lambda f: clip[min(f // 2, len(clip) - 1)]
    print("running the model for %d display frames ..." % S, flush=True)
    m.run_source(S)

    def aligned_rmse(a, b):
        a, b = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
        A = np.stack([a, np.ones_like(a)], 1)
        coef = np.linalg.lstsq(A, b, rcond=None)[0]
        return float(np.sqrt(np.mean((A @ coef - b) ** 2)))
    f = np.arange(S)
    t = f / 60.0
    r_raw = np.array([aligned_rmse(d["raw"], d["clean"]) for d in m.src])
    r_cor = np.array([aligned_rmse(d["y14"], d["clean"]) for d in m.src])
    nbox = np.array([len(d["boxes"]) for d in m.src])
    person = np.array([gt[min(i // 2, len(gt) - 1)].sum() for i in f])

    fig, axs = plt.subplots(3, 1, figsize=(9.5, 7.2), sharex=True, gridspec_kw={"height_ratios": [1.2, 0.8, 1.0]})
    ax = axs[0]
    ax.plot(t, r_raw, color="#9ca3af", lw=2, label="raw sensor")
    ax.plot(t, r_cor, color=ORANGE, lw=2.2, label="after NUC")
    ax.set_ylabel("error vs source\n(counts)")
    ax.set_title("What happens in the first seconds of a clip (bit-accurate model, library clip)")
    ax.legend(loc="center right")
    ax.annotate("the NUC learns the sensor's fixed pattern\nfrom the moving scene, no shutter", (1.0, float(r_cor[60])), xytext=(2.4, 200), fontsize=9,
                arrowprops=dict(arrowstyle="->", color="#9a3412"), color="#9a3412")
    axs[1].fill_between(t, 0, person / 1000.0, color="#bbf7d0", step="mid")
    axs[1].plot(t, person / 1000.0, color=GREEN, lw=1.6)
    axs[1].set_ylabel("person pixels\n(ground truth, x1000)")
    axs[2].step(t, nbox, color=BLUE, lw=1.8, where="mid")
    axs[2].set_ylabel("boxes reported")
    axs[2].set_xlabel("time since the clip started (s)")
    warm_s = 128 / 60.0
    for a in axs:
        a.axvspan(0, warm_s, color="#fee2e2", alpha=0.8, lw=0)
        a.axvline(5.0, color=GREY, ls="--", lw=1.2)
    axs[2].text(warm_s / 2, max(1, nbox.max()) * 0.5, "no boxes\nreported\n(128 frames)", ha="center", va="center", fontsize=8.5, color="#991b1b")
    axs[2].text(5.1, max(1, nbox.max()) * 0.85, "empty scene ends (5 s):\nthe person walks in", fontsize=9, color="#374151", va="center")
    axs[0].set_xlim(0, S / 60.0)
    save(fig, "fig_warmup.png")
    first = int(np.argmax(nbox > 0)) if (nbox > 0).any() else -1
    print("  first box at display frame %d (%.1f s); person first in the ground truth at %.1f s" % (first, first / 60.0, np.argmax(person > 300) / 60.0))
    print("  NUC error: raw %.0f -> after 1 s %.0f, 3 s %.0f, end %.0f counts" % (np.median(r_raw), r_cor[60], r_cor[180], np.median(r_cor[-120:])))


ALL = {"nuc": fig_nuc, "tmask": fig_tmask, "cdnet": fig_cdnet, "resources": fig_resources, "timing": fig_timing, "chase": fig_chase,
       "compare": fig_compare, "boardgt": fig_board_gt, "warmup": fig_warmup}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma separated subset of: " + ",".join(ALL))
    a = ap.parse_args()
    for k in (a.only.split(",") if a.only else ALL):
        ALL[k]()


if __name__ == "__main__":
    main()
