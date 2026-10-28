# Roadmap 2: Self-Calibrating Thermal NUC + Deterministic-Latency Motion Detection (rev 2)

**Board:** Terasic DE10-Standard (Cyclone V SoC `5CSXFC6D6F31C6`: 41,910 ALMs, 112 DSP, 557 M10K = 5,570 Kb, dual-core ARM HPS, 1 GB HPS DDR3, ADV7123 VGA DAC)
**Toolchain (as installed):** Windows 11, Quartus Prime Lite **21.1** (`C:\intelFPGA_lite\21.1`), Icarus Verilog 14, Python 3.13 venv (`.venv/`), Questa available (unused so far).
**Rulebook:** `fpga_checklist_updated.md`. Where a task says **[CL §x]** it is there because of that checklist section.
**Status key:** `[x]` done and verified | `[~]` partly done (see note) | `[ ]` not started | **(HW)** needs the physical board | **(DATA)** needs your downloads.
Every phase ends with an **Exit gate**; do not start the next phase until it passes.

## What changed from rev 1, and why

| Change | Reason |
|---|---|
| Fedora/cocotb -> Windows toolchain, vector-driven self-checking Icarus testbenches | Matches the machine and the sister project (`FPGA-Adaptive-Night-Vision`) that already works; cocotb on the Windows Icarus build is fragile. [CL §3.2] |
| Working resolution **320x240** (was 320x256) | Exactly half of 640x480 VGA (integer 2x scaling, no scaler); CDnet `library` is natively 320x240. Width/height are parameters; 320x256 is a parameter change. |
| Whole design on the **25 MHz VGA pixel clock**, "tick grid" lockstep with the VGA timing | No pipeline/VGA clock crossing, 40 ns per cycle (timing closure is easy), and the latency becomes a counted number of cycles. A tick is >= 2 clocks apart, so every stage must tolerate gaps. [CL §1.7] |
| NUC algorithm: **LMS with adaptive error limit, gain learning gated by frame activity**; constant-statistics NUC kept as a baseline only | Study results in `docs/results/nuc_study.md` (below). The per-pixel temporal "motion gate" and the fixed edge-stop in rev 1 were tested and rejected. |
| Task 2.8 premise rewritten | Measured: a per-pixel temporal background detector on a static camera gets **no** benefit from NUC (it absorbs the fixed pattern). The benefit shows for a detector without per-pixel memory. See "Findings". |
| Added `row_retimer` between the morphology chain and the box extractor | Found by the whole-chain test (bug log #9). |
| Phase 3 split: **3a on-chip sensor emulator + VGA** (no HPS, no downloads, runs on the board) and **3b HPS DDR3 feeder** | Gets the pipeline on the board with exact ground truth before the riskiest block (HPS F2H SDRAM port). The emulator is also the source for the hardware latency demo. |
| Bit-accurate model written twice: `pipeline_int.py` (vectorised) and `pipeline_ref.py` (scalar loops); boxes cross-checked against `scipy.ndimage.label` | A golden model is as likely to be wrong as the RTL. [CL §3.2] |
| Regression harness with a **mutation self-test** (110+ injected RTL faults must each fail a testbench for a functional reason) | [CL §3.9]. It found 15 test blind spots and a real architecture bug (bug log #5, #6, #9). |

## Findings that shaped the design (all reproducible: `scripts/study_*.py`, results in `docs/results/`)

1. **Static camera: spatial LMS works, constant-statistics fails.** Aligned RMSE vs clean after 300 frames (counts; raw is 257 `typical`, 319 `severe`): LMS 24 / 48 on a moving camera, 54 / 70 on a static one; constant-statistics 253 (no gain; it needs scene motion and a long clip). 
2. **Static camera pays with burn-in.** LMS over-smooths static scenes (roughness 0.0056 vs 0.0085 clean) and leaves a ghost of the object that later moves away: -106 counts on a +1500-count object. Learning the **gain** is what burns structure in (offset-only ghost: +3).
3. **Gate the gain, not the offset.** `mean|y - B|` (activity, which the detector already computes) is ~103 for a moving camera and ~25 for a static one. Gain learning only above a threshold (64) cuts the ghost to -24 counts with unchanged moving-camera RMSE (22.8 vs 23.2). The threshold is scene/speed dependent: a CSR.
4. **Fixed edge-stop deadlocks; "skip" collapses; clip works** (bug log #1).
5. **Word lengths:** offset fractional bits and output fractional bits do not matter (OF=0..6, YF=0..3 give the same RMSE); gain needs 12 fractional bits (10 costs 7 %, 14 gains nothing). `docs/results/width_sweep.md`.
6. **Motion detection vs NUC:** temporal per-pixel background: clean 0.975 / noisy 0.977 / NUC 0.978 F1 (no benefit). Single-frame hot-spot detector: F1 0.13 -> 0.80 (typical), 0.06 -> 0.78 (severe). The hot-spot detector is **not in hardware yet** (task S.5).
7. **Detector start-up:** conservative update keeps ghosts of frame-0 objects alive; blind update with a warm-start averaging schedule fixes it (bug log #2).

## Architecture (frozen for rev 2; reopen only with a written reason)

```
vga_timing -> tick_gen --tick bus--> sensor_emu (3a) | HPS DMA (3b)
                                          |
                    nuc_core: coef RAM -> correct -> win3x3 -> d,e -> clip -> LMS update/write-back, bad-pixel counters
                                          |  y14, x14                          |
                     disp_path <----------+                          bg_detect (B RAM, threshold, activity)
                     (tone map, 2x, views, boxes)                              |
                                                          morph x4 (erode, dilate, dilate, erode) -> row_retimer -> ccl_boxes
csr_regs  <- status, latency counters, boxes            (activity -> gain_en feedback closes inside thermal_core)
```
Details, Q formats, latency ledger, hazards and assumptions: `docs/design.md`.

## Standing rules (from the checklist; every phase)

* **S1 Timing from day one.** `scripts/build_quartus.sh` runs map -> fit -> sta -> asm -> compressed rbf; `scripts/check_sta.py` fails if the PLL clock is absent from the slack tables. [CL §0.1, §0.6, §2.2, §2.6]
* **S2** One pipeline stage = one significant arithmetic operation; every module exports/ledgers its latency. [CL §1.10]
* **S3** Memories are standalone modules with registered reads; check the map report for inferred M10K. [CL §1.1]
* **S4** Portable Verilog-2005 only (no hierarchical refs in RTL, no inline `genvar`, no `localparam` in port lists). [CL §1.9]
* **S5** Q format in every port comment; precision constants change in RTL and `pipeline_int.py` in the same commit; swept in Python first. [CL §1.4]
* **S6** Every streaming module is tested with random tick gaps (`GAPMAX` swept); only the box extractor's row-gap assumption needed the retimer. [CL §1.7]
* **S7** Acceptance stimulus has entropy (random + natural + noisy + moving objects); directed hand-built masks for hazards. [CL §3.1]
* **S8** Two golden models agree before either judges RTL; latency ledger at the top of every testbench. [CL §3.2, §3.3]
* **S9** `scripts/run_regression.py` parses the testbench verdict (never the exit code), treats "no verdict" as FAIL, and `--selftest` proves it fails on injected faults. [CL §3.8, §3.9]
* **S10** Per-frame state has a soft reset (`frame_reset`, `coef_reset`). [CL §1.8]
* **S11** Hardware gates in order: Gate 0 (same input 4x -> bit-identical, from a fresh configuration), Gate 1 (matches the model), Gate 2 (then measure). [CL §4]
* **S12** `.rbf` built with compression, size compared with the last good one, old one backed up, JTAG programming with an explicit `@N` from `jtagconfig`. [CL §2.4, §2.4a]
* **S13** Everything synthesis reads is committed (`rom_bg.hex` names its generator). [CL §7.1]
* **S14** `docs/bug_log.md`. [CL §7.3]

---

## Phase 0: Environment and board bring-up

- [x] **0.1** Repo layout: `rtl/ tb/ model/ sw/ quartus/ docs/ data/(gitignored) scripts/ work/(gitignored)`. (`git init` not done: the folder is not a repository yet.)
- [x] **0.2** Quartus Prime Lite 21.1 runs from the shell (`quartus_map` verified); Icarus 14.
- [x] **0.3** Python 3.13 venv: numpy scipy scikit-image opencv-python matplotlib pytest. cocotb dropped (see above).
- [x] **0.4 (HW)** `jtagconfig`: `DE-SoC [USB-1]`, HPS DAP @1, FPGA @2 (2026-10-26, `docs/board_notes.md`). [CL §2.4a]
- [~] **0.5 (HW)** Build 2 loaded and running: LEDs, HEX frame counter, latency pages as designed (`docs/board_notes.md`). **No VGA monitor available**: the picture goes to the laptop through the JTAG viewer instead (3c).
- [ ] **0.6 (HW)** Boot the Linux SD image over UART (check `SW10 MSEL = 01010`), confirm SSH, record which OS image is on the card and which compilers exist (needed only for Phase 3b / 6.6).
- [~] **0.7** Pins done (`quartus/pins/de10_pins.tcl` copied from the sister project, generated from the Terasic golden top, plus `gpio_pins.tcl` for two scope markers). Still to collect: DE10-Standard manual, HPS bridge map, GHRD Qsys (Phase 3b).

**Exit gate (HW):** a bitstream loads with the right `@N`, the picture appears, STA slack is positive with the PLL clock in the tables, Linux boots.

## Phase 1: Datasets and sensor-noise model

- [x] **1.1 (DATA)** CDnet 2014 thermal category in `data/cdnet/thermal/` (5 sequences, 21,100 frames, all with ground truth).
- [ ] **1.2 (DATA)** FLIR ADAS thermal frames (check the bit depth after download: sources disagree between 14 and 16 bit).
- [x] **1.3** `model/noise_model.py` (gain, offset, column/row, drift, temporal, dead/hot; presets; seeds).
- [x] **1.4** `docs/noise_model.md`: every parameter is marked **assumption** or literature-backed; **literature ranges are not verified yet** (could not open papers; verify before quoting).
- [x] **1.5** mild / typical / severe presets, fixed seeds.
- [~] **1.6** Synthetic clip pairs with exact ground truth: done (`model/scenes.py`, `model/sensor_emu.py`). Real-data pairs: **(DATA)**; loaders are written and tested on fabricated files (`model/datasets.py`).
- [x] **1.7** `model/metrics.py`: RMSE, PSNR, global-affine-aligned RMSE (absolute gain/offset is unobservable), roughness, convergence frame, ghost amplitude, precision/recall/F1/false-alarm rate with CDnet `valid` masks.

**Exit gate:** reproducible noisy/clean pairs and a metrics script. Met for synthetic data; real clips pending.

## Phase 2: Algorithm exploration in Python

- [x] **2.1** Constant-statistics NUC (`model/nuc_float.py`).
- [x] **2.2** LMS NUC.
- [x] **2.3** Gating: tested per-pixel temporal gate (rejected), fixed edge-stop (rejected), skip (rejected), adaptive clip (kept), frame-activity gain gate (kept). `scripts/study_nuc.py`, `study_nuc2.py`.
- [x] **2.4** Bad-pixel detection: outside the neighbour range by more than T (robust to real edges) or at a rail, 4-bit persistence counter with decay (hysteresis); replacement by the mean of the valid 4-neighbours (deviation from "median": cheaper, same job).
- [x] **2.5** Comparison on all presets, static and moving camera, plus the ghosting test (`docs/results/nuc_study.md`).
- [x] **2.6** Fixed-point choices and word-length sweep (`docs/results/width_sweep.md`).
- [x] **2.7** Motion detector: running average, blind update with warm start, 3x3 open+close, 4-connected boxes (`model/motion_float.py`, `scripts/tune_detector.py`).
- [x] **2.8** Evaluation (with the corrected premise): `scripts/study_motion.py` (temporal, no benefit) and `scripts/study_spatial.py` (hot-spot, large benefit). **Real-data numbers: (DATA).**
- [x] **2.9** Frozen `model/pipeline_int.py` + `model/pipeline_ref.py`; 23 Python tests including int == scalar reference bit for bit and boxes == scipy labelling.
- [x] **2.10** Real footage (`scripts/eval_cdnet.py`, `docs/results/cdnet_eval.md`): detector F1 0.68-0.76 on corridor / diningRoom / library, 0.65 park, 0.22 lakeSide (low contrast, T_MASK too high); NUC changes detection by < 0.015 F1 on a static camera, as predicted. Static camera: the NUC slowly absorbs the scene (bug log 18-19): residual / detail peaks after 25-400 frames, then degrades. Frame-global camera-motion gates and a per-pixel temporal gate were measured and rejected; **learning window `LEARN_N`** (default 256 frames, 0 = forever) adopted.
- [x] **2.11** T_MASK study (`scripts/study_tmask.py`, `docs/results/tmask_sweep.md`): the threshold is scene dependent and a run-time CSR. lakeSide 0.22 -> **0.57 at T_MASK = 96**, diningRoom 0.69 -> 0.75 at 200, park 0.65 -> 0.70 at 256, library 0.76 -> 0.83 at 640, corridor best at 400; no single value beats 400 by more than 0.01 mean F1 (best 320: 0.614 vs 0.606). An adaptive threshold (from the background noise) would be the next step, not done.

**Exit gate:** met, with the finding that NUC benefits detection only for detectors without per-pixel memory.

## Phase 3: Video input

### 3a: On-chip sensor emulator + VGA (no HPS)
- [x] **3a.1** `rtl/sensor_emu.v` + `model/sensor_emu.py`: ROM background + 3 moving rectangles + per-pixel gain/offset/column/temporal noise + dead/hot pixels from a stateless integer hash; exact ground truth. Bit-exact over 7 scenarios incl. full size (`emu_*` tests).
- [x] **3a.2** `rtl/tick_gen.v` tick grid locked to `vga_timing` (4-line lead so processed rows are ready before they are displayed).
- [~] **3a.3** `rtl/disp_path.v`: auto tone map, 2x scale, raw / corrected / split views, gray or iron palette, box overlay. Simulation compared with the Python model at the VGA pixel level: see the status note under the exit gate.
- [x] **3a.4** `rtl/csr_regs.v` (bus-slave map in the file header).
- [x] **3a.5** Switch/key/LED/HEX user interface in `rtl/thermal_top.v`.

### 3c: JTAG viewer (no VGA monitor)
- [x] **3c.1** `quartus/ip/jtag_host` (Platform Designer: JTAG-to-Avalon master + MM bridge, `scripts/gen_jtag_host.sh`), `rtl/host_if.v` (CSRs at 0x00000, capture buffer at 0x20000), `rtl/frame_cap.v` (one tone-mapped frame on request, 75 M10K).
- [x] **3c.2** `tb/host_tb.v` (8 captures, pipelined reads, re-arm at 4 phases; 9 mutants caught); full-size capture vs system model in the slow tests (`scripts/check_capture.py`).
- [x] **3c.3** `host/viewer.py` + `host/jtag_server.tcl` (System Console): live picture, boxes, latency, keys for every switch. Error path tested without a board.
- [x] **3c.4 (HW)** Build 5 on the board (2026-10-27): capture of frame 7730 (corrected) identical to the model, 0 of 76,800 pixels differ (Gate 1 on hardware). Viewer needs the JTAG clock at 6 MHz (bug log 22); frame rate 0.2 fps in side-by-side view (about 2.5 s per 76,800-byte readout over JTAG), twice that with one view.

### 3b: HPS feeder (real clips)  **(HW)**
Design change vs the first plan: no DDR3 ring / F2H SDRAM reader. The frame store is a host-written one-frame buffer in the FPGA (rtl/scene_buf.v, replaces the emulator's ROM in the FEED build) and the writer (ARM or any host) "chases" the scan row by row (FEED_ROW counter), which never tears a frame and needs no second buffer (RAM is the limit: 506 of 553 blocks used by build 5). The path HPS -> lightweight bridge -> same host bus as the JTAG viewer is the one the Weibull-CFAR project already proved on this board.
- [x] **3b.1** `sw/frame_feeder.c` (TCP server, clip player, bench; static ARM build; mock FPGA + `make -C sw test`), `host/feed_clip.py`, `host/thermal_net.py`, `scripts/prepare_clips.py` (CDnet -> raw clips). Verified against the mock, not on the board.
- [x] **3b.2** Platform Designer `quartus/ip/hps_sys` (the proven GHRD HPS + JTAG master -> one host bus), `quartus/thermal_soc`, `rtl/thermal_soc_top.v`. Generation needs the DDR3 overlay (bug log 23). Build 6 (`releases/build6/`, 2026-10-27): 8,575 ALMs (20 %), 551 / 553 RAM blocks (100 %: two spare), 31 DSP, STA PASS at all corners (worst setup +1.7 ns in the HPS domain, +15 ns JTAG clock). Not loaded on a board yet.
- [x] **3b.3** (design changed, see above) frame store + chase: `scene_buf`, `host_if` feed region, CSRs 0x23-0x25; unit tests, mutants, bit-exact emulator tests, full-size system test `sys_feed`.
- [ ] **3b.4 (HW)** 10,000-frame pass-through test: zero dropped or duplicated frames (`frame_feeder bench`, `feed_clip.py --loop`, then compare the feed count with the design's FRAMES counter). Procedure: `docs/bringup_3b.md`.
- [ ] **3b.5 (HW)** Real clip on the board: boxes round the people in `viewer.py --net`; board box list equals the model's for the same clip (needs a per-frame box log on the ARM, not written yet).

**Exit gate:** 3a: the emulator drives the full pipeline and the VGA picture matches the model (simulation), then on the board **(HW)**. 3b: real clips stream reliably **(HW)**.

## Phase 4: NUC and bad-pixel RTL

- [x] **4.1** Coefficient RAM: one 76,800 x 31-bit simple-dual-port M10K RAM `{bpc[3:0], g[12:0], o[13:0]}`, cleared by a state machine (power-up and `coef_reset`).
- [x] **4.2** Correction datapath (one DSP multiply, rounding, saturation, bypass).
- [x] **4.3** `win3x3` with exact edge replication (documented in the file header; tested on random data, random gaps).
- [x] **4.4** Neighbour mean via reciprocal table (`65536/n`, exact for n = 1,2,4; rounding checked for n = 3), error.
- [x] **4.5** Update stage: shift-based offset step, gain step with `2^-28` per count^2, adaptive clip, write-back one frame apart. Hazard analysis in `docs/design.md`.
- [x] **4.6** Bad-pixel counter, outlier test on valid neighbours, replacement.
- [x] **4.7** Controls as CSRs (`nuc_en`, `learn_en`, `bp_en`, thresholds, `coef_reset`, `frame_reset`).
- [x] **4.8** Bit-exact testbenches (12 scenarios incl. random saturating data, odd sizes, bypass, learning off, runtime toggles, clamp saturation, bad-pixel clusters, flat scene).
- [~] **4.9** Properties: protocol and latency are checked in simulation (latency ledger in every testbench). SymbiYosys is not installed; formal proofs moved to stretch S.4.
- [~] **4.10** Synthesis: probe of `nuc_core` at production size: coefficient RAM inferred as M10K (2.38 Mb), 5 DSP. Full-design numbers: see the status note under the exit gate.
- [~] **4.11 (HW)** Noisy vs corrected live: through the JTAG viewer (3c.4); convergence plot from captured frames.
- [x] **4.12** Learning window: `LEARN_N` CSR (0x0D), counter of learning frames reset by `coef_reset`, LEDR9 = learning runs; `nuc_window`, `nuc_window_reset`, `chain_window` tests and 5 mutants.

**Exit gate:** RTL bit-exact vs the model (met in simulation); visible convergence on the board **(HW)**.

## Phase 5: Motion detection RTL

- [x] **5.1** `bg_detect`: B RAM (16 bit), warm-start schedule, blind update, activity sum, gain-gate feedback.
- [x] **5.2** Threshold and mask; detection reported only after `DET_WARM` frames.
- [x] **5.3** Four cascaded `morph3` stages (erode, dilate, dilate, erode) on the shared window engine.
- [x] **5.4** `ccl_boxes`: single-pass 4-connected labelling, 16 label slots, 16 result slots, overflow flags (never stalls), delayed slot reuse to avoid stale-label aliasing, fixed end-of-frame latency. Plus `row_retimer`.
- [x] **5.5** Box overlay in `disp_path` (boxes belong to the previous frame: one-frame lag).
- [x] **5.6** Box count and list at a fixed point after the end of the frame (`fdone`).
- [x] **5.7** Testbenches: box extractor vs the specification (8 scenarios incl. slot exhaustion, comb merges, borders, >255 objects); whole chain vs `frame_step` (7 scenarios, closed-loop activity gate).
- [~] **5.8** Whole-design synthesis: see status note.
- [ ] **5.9 (HW/DATA)** Hardware test with and without NUC (emulator now; CDnet via 3b).

**Exit gate:** full pipeline bit-exact in simulation (met); detects motion on the board **(HW)**.

## Phase 6: Deterministic-latency engineering

- [~] **6.1** `docs/latency_spec.md` (pixel-in -> pixel-out N, end-of-frame -> flag K, assumptions).
- [x] **6.2** N and K derived analytically and confirmed in simulation (ledgers in the testbenches).
- [x] **6.3** Hardware timestamp counters and min/max latency statistics in `csr_regs` (RTL done, simulated).
- [x] **6.4 (HW)** Build 2 on the board: HEX page 3 (max - min) = 000000 after minutes of running with every switch setting tried; K = 0x2214 = 8,724 cycles as simulated. Exact frame count via the viewer (2026-10-27, build 5): min = max = 8,724 cycles (349.0 us), jitter 0, over 69,510 frames.
- [ ] **6.5 (HW)** `GPIO[0]` (first input tick) and `GPIO[1]` (box list published) on a scope; compare with the counters.
- [ ] **6.6 (HW)** ARM C implementation (NUC + motion) and its per-frame latency under Linux (needs 0.6).
- [ ] **6.7 (HW)** Optional PREEMPT_RT / `SCHED_FIFO`.
- [ ] **6.8 (HW)** Histograms FPGA vs ARM, worst case and 99.9th percentile.
- [~] **6.9** Stress: runtime CSR toggles are in the regression (`nuc_toggle*`); 100 % HPS load **(HW)**.

**Caveat to state with the result:** with the pipeline locked to the VGA clock, zero jitter in cycles is true *by construction* as long as the input is the tick grid. The measurement still matters (it checks the assumptions), and the comparison with Linux is the point of the demo.

## Phase 7: Evaluation and benchmarking
- [ ] **7.1** NUC convergence curves per preset on the hardware output; **7.2** detector F1/FAR on CDnet **(DATA)**; **7.3** ghosting clip; **7.4** resources/Fmax (from the final build); **7.5** throughput; **7.6** power (Quartus Power Analyzer); **7.7** ablations; **7.8** results folder with scripts.
  Python-side versions of 7.1-7.3 already exist (`docs/results/`).

## Phase 8: Documentation and demo
- [~] **8.1** README, **8.2** block diagram, **8.3** design doc (`docs/design.md`), **8.4** video, **8.5** NUC as reusable IP, **8.6** release, **8.7** résumé page.

## Stretch goals
- [ ] **S.1** 640x512. **S.2** tracking. **S.3** temporal denoiser. **S.4** formal proof of constant latency.
- [ ] **S.5** Hot-spot (spatial-contrast) detector in RTL: the mode where NUC visibly matters for detection (Findings 6).
- [ ] **S.6** Verify the noise-model literature ranges and cite them.

## Risks and fallbacks
| Risk | Fallback |
|---|---|
| Reviewers question the simulated noise | `docs/noise_model.md` states which parameters are assumptions; three severities; say "simulated" everywhere. |
| Coefficient + background memory does not fit | Shrink gain to 11 bits (-0.2 Mb), background to 14 bits, or run at 320x180. Current estimate: ~70 % of M10K. |
| NUC ghosting on static scenes | Offset-only mode (gain gate threshold high) leaves ghost +3 counts. |
| Static camera makes NUC pointless for temporal detection | Say so (Finding 6); demonstrate NUC on image quality and on the hot-spot detector. |
| Timing closure fails | Not expected at 40 ns/cycle; add pipeline stages and update the latency ledgers. |
| ARM latency looks "too good" | Add background load; report the tail (99.9th percentile, max), not the mean. |
