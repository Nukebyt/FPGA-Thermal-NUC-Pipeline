# Bug log

Format (checklist 7.3): Symptom / Root cause / Fix / Lesson. Exact numbers. Wrong hypotheses are recorded too.
"Algorithm" entries are findings that changed the design, not coding slips.

### 1. (algorithm) Fixed absolute edge-stop threshold deadlocks learning

**Symptom:** `lms+edge` with threshold 400 counts: RMSE stayed at the raw level (230 vs 233 raw, `typical` noise) and 212 vs 297 raw on `severe`; the unguarded LMS reached 54 / 24.
**Root cause:** the edge test (max-min of the 8 neighbours of the *corrected* image > T) was evaluated while the fixed-pattern noise was still large (sigma ~270 counts, neighbour spread ~800 counts), so every pixel looked like an edge and no pixel ever learned.
**Fix:** dropped the absolute edge-stop. Replaced by an error limit that adapts to the frame: `lim = clamp(3 * mean|e| of the previous frame, EMIN, EMAX)` (one accumulator and a multiply per frame).
**Lesson:** a threshold that depends on the quantity being estimated needs to be relative to it. Also tried "skip instead of clip beyond the limit" (`adapt-skip`): it collapses (RMSE 188-324) because skipping shrinks mean|e|, which shrinks the limit, which skips more. Clip, never skip.

### 2. (algorithm) Conservative background update keeps start-up ghosts alive

**Symptom:** clean-data detector F1 only 0.39-0.65, false-alarm rate ~2 %; `alpha_fast` changed nothing at all.
**Root cause:** foreground pixels used the slow rate (1/256) so the footprint of each blob that was baked into the first-frame background stayed flagged for hundreds of frames.
**Fix:** blind update (one rate for every pixel) plus a warm-start schedule `sh = min(KB, ceil(log2(n+1)))` that averages the first frames. Clean F1 0.975, FAR 0.0009.
**Lesson:** when a parameter has exactly zero effect on the metric, the metric is dominated by something else; look at the images.

### 3. (algorithm) NUC does not improve a per-pixel temporal motion detector on a static camera

**Symptom:** roadmap task 2.8 expected "a clear NUC benefit on motion detection". Measured F1 at T=400 counts: clean 0.975, noisy 0.977, noisy+NUC 0.978 (typical); severe 0.975 / 0.980 / 0.980.
**Root cause:** the per-pixel background model absorbs the fixed pattern. FPN is static, so `y - B` cancels it.
**Fix / consequence:** the benefit exists where there is no per-pixel memory. A single-frame hot-spot detector (`y - box21(y) > T`, moving camera) gets F1 0.13 -> 0.80 (typical) and 0.06 -> 0.78 (severe), false alarms 13 % -> 0 (`scripts/study_spatial.py`). The roadmap's claim was rewritten accordingly; the hot-spot detector is Python-only so far.
**Lesson:** test the premise of a planned result before building hardware for it.

### 4. Gain/offset clamps in the sweep script were absolute integers

**Symptom:** `GF=8` row of the word-length sweep: RMSE 471 (worse than raw 250).
**Root cause:** `GMIN = 2048`, `GMAX = 8191` hard-coded; at GF=8 the lower clamp is 8.0x gain.
**Fix:** `GMIN = 1 << (GF-1)`, `GMAX = (2 << GF) - 1` as properties of Cfg. **Lesson:** every clamp derived from a Q format must be derived, not typed.

### 5. Regression harness reported mutants as "caught" for the wrong reason

**Symptom:** self-test showed 15 of 15 mutants CAUGHT while the vector-generation step printed `'.venv' is not recognized as an internal or external command` for every case.
**Root cause:** `subprocess.run(..., shell=True)` goes through `cmd.exe`, which cannot run `.venv/Scripts/python.exe` with a forward slash; every testbench "failed" before it ever ran.
**Fix:** run generators without a shell, using `sys.executable`; the self-test now counts a mutant as caught only if the *testbench* printed a functional failure (compile error, generation failure and timeout are reported as INVALID).
**Lesson:** checklist 3.9 exactly. A harness fix must be validated against a known-bad input, and "FAIL" has to mean the right failure.

### 6. Mutation testing found 15 blind spots in the first set of tests

Found by the self-test after the harness was fixed (each is a mutant that survived):
* offset/gain clamps, `GMIN`/`GMAX`: 10-16 frame tests never reach saturation. The LMS *solves* a 6000-count checkerboard with `o` and `g`, so nothing saturates; only 1 vs 16382 (beyond the coefficient ranges) does, and only after ~400 frames.
* error-limit clamps: `KLIM = 41` is tuned for 76,800 pixels; on a 1,728-pixel test frame the statistic is 44x smaller so neither clamp is reached. `KLIM` became a parameter and tests scale it.
* `d = yc` when all four neighbours are bad, `anyv` when all eight are bad: needs clustered bad pixels (added `cluster` mode with a ring of eight around a healthy pixel).
* bypass mux: with `nuc_en=0` from reset the coefficients stay at identity, so bypass == correction. Needs a runtime toggle after learning (`--toggle`).
* stale-label hazard in the box extractor (see 9): no random mask triggers it; a hand-built mask does.
* first-row / first-column gating of neighbours, `ovf` set by label-slot exhaustion alone, `n_obj` saturation at 255: directed masks added.
**Lesson:** a passing testbench says nothing until the mutants die. Equivalent mutants (two of mine) must be recognised and dropped, not "fixed" by weakening the check.

### 7. `emin`/`emax` ports were wider than the register they feed

**Symptom:** `quartus_map` warning 10230: "truncated value with size 13 to match size of target (12)" at nuc_core.v:427. No simulation ever failed.
**Root cause:** ports were 11 bits (counts) but the limit register is U12.2, i.e. at most 1023 counts. An `emax` above 1023 silently wrapped.
**Fix:** ports narrowed to 10 bits, documented in the CSR map. **Lesson:** read every synthesis warning once; this one was a real bug.

### 8. First-frame background load propagated X through the whole simulation

**Symptom:** chain test: `det stats act got x`, mask never set, 170,999 errors.
**Root cause:** frame 0 computed `B_new = B + (y - B)` on an uninitialised RAM. Algebraically `y`; in simulation `X`.
**Fix:** frame 0 writes `y` explicitly. **Lesson:** do not rely on cancellation of an undefined value; hardware happens to hide it, simulation does not.

### 9. Box extractor saw mask rows without the idle gap it needs (architecture)

**Symptom:** whole-chain test (`chain_pan_severe`, frame 14): the final mask matched the model pixel for pixel but the box list differed (3 boxes vs 4). The stand-alone box-extractor testbench passed on the same masks.
**Root cause:** the mask leaves the five-window chain offset by `5*(W+2)` flat ticks. The big idle gap of the tick grid therefore falls in the *middle* of a mask row, and the real row boundary is only two ticks (4 clocks) wide, so the extractor's 17-clock end-of-line scan overlapped the next row's first pixels. The unit test's own stimulus had the gaps in the "right" place, so it could not see this.
**Fix:** `row_retimer`: store each mask row and replay it in its own burst (one pixel per 2 clocks, gap guaranteed). This also makes the end-of-frame latency independent of tick timing. First version was off by one column (registered read address -> data one clock later than the valid pipeline assumed); fixed with a second stage.
**Lesson:** unit testbenches inherit the timing assumptions of their author. Test the composition with the timing the composition really produces (checklist 1.7).

### 10. CSR box read-back used the wrong bit slices

**Symptom:** `csr_tb`: 32 mismatches reading box words. **Root cause:** record layout is `{area, ymax, xmax, ymin, xmin}` but the read mux took `brec[26:18]` as ymin. **Fix:** slices corrected. **Lesson:** the testbench built the records from the documented layout, independent of the RTL.

### 11. Small test frames contained no objects

**Symptom:** chain vectors with "frames with a mask: 0, boxes: 0" (TB reports FAIL: vacuous). **Root cause:** `scenes.make_scene` scaled blob radius with frame size; at 48x36 the blobs were sub-pixel and the 3x3 opening removes them. **Fix:** minimum radius 4 px / speed 0.5 px per frame on small frames. **Lesson:** every testbench has a "did anything actually happen" check; keep it.

### 12. (environment) Shell wrapper cannot take heredocs with unbalanced quotes

**Symptom:** `unexpected EOF while looking for matching '` from bash for scripts containing an odd number of `'` inside a heredoc body. **Fix:** write patch scripts with the editor tool and run them. Not a project bug, recorded because it cost three round trips.

### 13. 99 % of the M10K blocks used although only 76 % of the memory bits were

**Symptom:** first full fit: `Total RAM Blocks 546 / 553 (99 %)`, block memory bits 4,291,709 / 5,662,720 (76 %). Map took 52 min and fit 72 min.
**Root cause:** 76,800-deep memories do not divide into the M10K shapes Quartus picked. A 31-bit coefficient word at 1K depth needs four 10-bit slices (9 bits wasted per block row); the background ROM at full resolution used 8Kx1 shapes (76,800 / 8,192 = 9.4, rounded to 10).
**Fix:** (a) offset fractional bits 2 -> 1 (the word-length sweep showed OF = 0..6 give identical RMSE): coefficient word 30 bits = exactly 3 slices of 1Kx10; (b) `max_depth = 1024` on every inferred RAM (76,800 = 75 x 1024); (c) emulator background ROM at half resolution (160x120, shown 2x, addressed `{r>>1, c>>1}` with power-of-two padding, no multiplier).
**Lesson:** check RAM *blocks*, not bits. The sister project's 85 % rule is about blocks.

### 14. The first full bitstream was built from stale RTL

**Symptom:** the overnight build finished (STA PASS) but its `quartus_map` had elaborated the sources before the fixes for #15 and #16 were made.
**Fix:** the `.rbf` was moved to `releases/stale/..._STALE_DO_NOT_FLASH.rbf` and the design rebuilt. **Lesson:** checklist rule 2: a bitstream is a versioned artefact. Never start a long build while the RTL is still being edited, or record the source state it was built from.

### 15. Tone-window shift loop picked the smallest overflowing shift

**Symptom:** whole-system VGA comparison: frames 2-5 almost entirely mismatching (got 255 where 85 was expected). Frame 1 (initial window) matched except for #16.
**Root cause:** `for (b = 6; b >= 1; b--) if ((range >> (b-1)) > 255) sh = b;` - the last assignment wins, i.e. the smallest qualifying `b`. **Fix:** ascending loop. **Lesson:** "last assignment wins" loops encode a priority; write which one is intended next to the loop.

### 16. Emulator advanced a phantom frame before the first real one

**Symptom:** VGA frame 1: 43,668 of 307,200 pixels off by one grey level (a temporal-noise pattern).
**Root cause:** the tick grid also runs in the tail of the VGA frame in which the system leaves reset, before any `first` tick. The emulator counted that grid's end-of-frame and advanced its frame counter (temporal noise) and rectangles. Every unit test started cleanly at `first`, so only the whole-system test could see it.
**Fix:** `armed` flag: end-of-frame events count only after the first `first`.
**Lesson:** another "what does the real system do that no testbench does" (checklist 1.7): power-up is a timing case.

### 17. Making a truncation explicit introduced a sign bug

**Symptom:** after replacing `o7 <= pB6 >>> 8` (warning 10230: 22 -> 15 bit truncation) with `o7 <= pB6[21:8]`, every emulator test saturated at 3FFF; the noise-free test still passed.
**Root cause:** a 14-bit slice assigned to a 15-bit signed register is zero-extended; negative offsets became large positive ones. The original truncation was harmless.
**Fix:** `{pB6[21], pB6[21:8]}`. **Lesson:** silencing a warning is a code change; rerun the regression after it, like after any other change.

### 18. (algorithm) On a static camera the NUC erases the scene; frame-global "camera moving" gates cannot fix it

**Symptom:** first real-footage run (`scripts/eval_cdnet.py`, CDnet `park`, `typical` noise): after 300 frames the corrected output is a blur; tree, building and grass texture are gone (`docs/results/cdnet_park.png`). Motion F1 is unaffected (clean 0.594, noisy 0.591, noisy+NUC 0.595), because the detector works on temporal differences.
**Root cause:** the LMS target is the 4-neighbour mean. With a static camera, scene structure is indistinguishable from fixed-pattern noise, so the offsets slowly learn the scene (known limitation of scene-based NUC). The activity gate only stops *gain* learning. On synthetic static scenes this showed as "some over-smoothing" (finding in the roadmap); on real texture it is severe.
**Wrong hypotheses (measured, `bit-accurate model`, 200 frames each):**
* *Gate on the frame activity `sum|y-B|` or on the fraction of changed pixels.* Does not separate the cases: CDnet `corridor` (static camera, people close to it) median act 245 / 16 % changed, a synthetic 0.3 px/frame pan 144 / 2.5 %.
* *Global shift estimation from row/column projections.* On noisy data the static fixed pattern dominates the projections, so the best shift is always 0 (0 % detection on every pan). Differencing the projections over K frames cancels the pattern, but then only moving objects remain on a static camera and their motion is reported as camera motion (~10 % false "moving" on static clips), and slow pans (0.15-0.3 px/frame) are detected only 1-25 % of the time.
**Fix:** see the next entry (per-pixel temporal gate).
**Lesson:** test on real texture early; a synthetic background with few edges hid the size of this effect.

### 19. (algorithm) Learning window instead of a motion gate

**Measurement (bit-accurate model, `typical`, static camera; residual = aligned RMSE vs clean, detail = correlation of the 7x7 high-pass with the clean one):** library 25 / 100 / 400 / 1600 / 3200 frames: 56/0.40, 38/0.68, 33/0.75, 111/0.71, 199/0.69; corridor 66/0.55, 56/0.66, 67/0.56, 106/0.70, 123/0.63; park 106/0.81, 164/0.61, 278/0.42 (raw 305/0.39). The NUC first removes the fixed pattern quickly, then keeps absorbing the scene.
**Rejected: per-pixel temporal gate** (learn only where |y - B| > G in the previous frame). G = 32 equals no gate on CDnet; G = 64-128 destroys the correction on the synthetic static scene (53 -> 220) and on library (34 -> 198) and slows a slow pan by 4x; it helps only park (247 -> 162).
**Fix:** `LEARN_N` frames of learning after a coefficient reset (KEY1 / PULSE.coef_reset), default 256 (~4 s at 60 fps), 0 = no limit for a moving camera. One 16-bit counter. Model, scalar reference and RTL agree; 3 new tests and 5 mutants.
**Lesson:** when every automatic gate fails the measurements, a simple operator-level control with a measured default is the honest answer. Record that the limit is fundamental (a static scene and a static fixed pattern are indistinguishable), not a tuning issue.

### 20. Testbench sampled readdatavalid on the clock edge that updates it

**Symptom:** the new back-to-back read check in `host_tb` failed on the correct design (got buffer data where the CSR ID was expected), and every mutant was "caught" by that same line. **Root cause:** the TB polled `av_readdatavalid` right after `@(posedge clk)`, racing the DUT's non-blocking update. **Fix:** sample at `negedge`. **Lesson:** checklist 3.6 again; and a self-test where all mutants fail on the same line is a sign the test itself is broken.

### 21. A variable-position part-select write tripled the logic and took synthesis from 21 minutes to 3.5 hours

**Symptom:** build 4 (build 3 + host bus + frame capture + JTAG master): `quartus_map` 3 h 25 min instead of ~21 min, logic 25,873 ALMs (62 %) instead of 8,252 (20 %), STA still PASS, RAM blocks 506 / 553 (92 %, as expected: +76 for the capture buffer). Fitter ~9 h of wall clock (the PC slept for most of it; ~3 h of CPU).
**Where:** the Fitter's per-entity table put 19,561 ALMs in `ccl_boxes` (594 in the JTAG master, 282 in `frame_cap`). `ccl_boxes.v` was byte-identical to build 3's.
**Root cause:** `res_flat[res_cnt[3:0]*53 +: 53] <= scan_box;` writes one 53-bit record at a run-time position of an 848-bit register. Quartus builds it as a barrel shifter over the whole vector. In build 3 most of those bits had no consumer (the CSR bus was tied off, so the record read-back and the area fields were removed), which hid the cost; build 4 made them all live.
**Evidence:** `ccl_boxes` alone, every output used (`work/exp_ccl`, 3.5 min per run): 5,763 ALMs before, **2,147 after**.
**Fix:** a loop with constant offsets and one enable per slot (`for rk .. if (res_cnt[3:0] == rk) res_flat[rk*53 +: 53] <= scan_box;`). Same logic: 8 box-extractor tests, 8 chain tests unchanged; new mutant (wrong slot) caught; 19 older ones still caught.
**Lesson:** read the per-entity utilisation table after every build, not only the totals; and a quick stand-alone synthesis of the suspect module (minutes) beats guessing in a multi-hour build. A good resource number in a build can be an accident of unused logic being removed.

### 22. The JTAG master hung every read at the USB-Blaster's default 24 MHz TCK

**Symptom (first hardware run of the viewer, build 5):** `master_read_32: This transaction did not complete in 60 seconds`; writes returned at once but had no effect (LEDR9 did not light after a coefficient reset with LEARN_N = 0). `jtag_debug_sense_clock` = 1, `jtag_debug_loop` returned the data, reset was not asserted, the design ran (HEX counting, LEDR0-6 on). After one hung read the master stayed wedged (even writes timed out) until the next successful run.
**Not the logic:** a simulation of the generated `jtag_host` (real master, bridge and interconnect, stand-in for the JTAG pins) plus `host_if` returns the read data and the correct response bytes (`work/jtagsim`). Synthesis kept `host_if`; the stuck `wr_reg_*` registers in the bridge are its unused wait-request buffer.
**Root cause:** the cable's JTAG clock was 24 MHz (`jtagconfig --getparam 1 JtagClock`), while the master runs on clk25. The master's clock-crossing between TCK and its clock assumes the system clock is well above TCK.
**Fix:** `jtagconfig --setparam 1 JtagClock 6M` (host/viewer.py now sets it before starting System Console). Result: ID 0x7A110005, capture of frame 7730 identical to the model (0 of 76,800 pixels differ).
**Lesson:** a design that simulates and times correctly can still fail on the board through a host-side setting; separate the layers (JTAG loopback, clock sense, logic simulation) before touching the RTL, and make the tool set the setting itself.

### 23. `qsys-generate` of an HPS system fails in the DDR3 sequencer step and silently leaves modules out

**Symptom:** `quartus/ip/hps_sys` (the proven HPS + a JTAG master + the host bus) generated with 66 errors in `generate_hps_sdram.tcl` ("Nios II Command Shell.bat make all ... child process exited abnormally"), same from Git Bash and from a clean PowerShell PATH. The output looked complete, but `quartus_map` then failed: first the memory-controller sources and the two sequencer ROMs (`altera_mem_if_*_cyclonev.sv`, `hps_AC_ROM.hex`, `hps_inst_ROM.hex`, three `sequencer_auto*.pre` files) were missing from the `.qip`, then, after adding them, the interconnect's Avalon-ST error adapter module was never generated at all.
**Not new:** the Weibull-CFAR project (`matlab/de10_ghrd`, its bug #21) hit the same crash and re-added the lines by hand after every run.
**Fix:** `quartus/ip/hps_sys/ddr3_overlay/` vendors the files from that project's generated output (they depend only on the HPS DDR3 configuration, which is taken over unchanged) and `scripts/fix_hps_sys.py` applies them after `qsys-generate`, then checks that every file named in the `.qip` exists and that every instantiated `hps_sys_*` module is defined (that check is what found the error adapter). `scripts/gen_hps_sys.sh` runs both.
**Lesson:** a generator that exits with errors can still leave a tree that looks complete; verify the result by what the next tool needs (every referenced file, every instantiated module), not by the exit code. Also: a shell whose working directory is inside a directory the script deletes keeps it locked on Windows (the `rm -rf` failed silently and a stale tree was reused once).

### 24. Feeder server: a client accepted during a poll round was served with stale poll state

**Symptom:** `sw/test_feeder.py` (two clients at once) failed with "connection closed by the board" for the second client, only after a few seconds. **Root cause:** `serve()` accepted a new client after `poll()` returned and then looped over all clients, including the new one, using `revents` values that were never set for it (stale from an earlier round); `serve_one()` then blocked on a client with no data until its 5 s receive timeout and the connection was dropped. **Fix:** only the clients that were polled this round are served; a client accepted in the round waits for the next poll. **Lesson:** the test with two simultaneous clients was written before the first run on any hardware and found this; keep the mock.

### 25. The first version of the chase test did not test the switch frame

**Symptom:** `sys_feed` "failed" on its own verdict line (`capture frame index 2 expected 3`) while the pixel comparison printed 0 differences. **Root cause:** the capture follows the display path, which trails the scan by more than a row, so a capture armed right after the scan read row 0 of frame k0 took frame k0 itself (still the old content), not k0+1; and the check could not tell, because both models agreed. The `an A-only frame would differ in N` line was 0, which is what exposed it. **Fix:** the TB arms the capture 6 rows into the chase; the result is the switch frame (3 = k0+1), 0 of 76,800 pixels differ from the model and an old-only frame would differ in 73,693. **Lesson:** a check that cannot fail proves nothing; the "would the wrong answer differ?" number in the checker's output is part of the test.

### 26. Full mutation self-test (2026-10-27): 117 of 121 mutants caught, 4 missed -> closed the same day

**Symptom:** `run_regression.py --selftest --skip-python` ended `OVERALL: FAIL`. The four misses reproduced when run alone, so they were test gaps, not flakiness (mutants run on a copy of `rtl/`). **Causes and fixes:** (1) `bg_detect.v` `absd > T` -> `>=`: no pixel sat exactly on the threshold. New case `chain_thr_edge`: `gen_chain_vectors.py --t_mask_edge_frame 12` picks the T_MASK at which pixels have |y-B| == T_MASK and the `>` / `>=` difference survives the 3x3 open/close (52 pixels); the regression passes the value it prints (20) as `TMASK`. (2) `sensor_emu.v` `DEADT = 130`: the mutant sits in the severe preset but was filed under `emu_fullsize` (typical preset), so it could never be caught there. Retargeted to `emu_severe`, whose frame contains pixel 1161, the one pixel with hash low16 == 130 (the hash depends on the pixel index only). (3) `hot6 ... && !dead`: an equivalent mutant (`x_out` already gives `dead8` priority over `hot8` and `hot7`/`hot8` feed nothing else): removed from the list with a comment. (4) `row_retimer.v` overrun flag: no test ever made a row finish during a replay. New unit test `tb/row_retimer_tb.v` (labels, bits, 5 + 2c clock latency, err stays low with spaced rows, err latches when a row completes during a replay, reset clears it). **Lesson:** a MISSED mutant can be a test gap, a mis-filed mutant or an equivalent mutant; check which before writing a test. Re-run of the three affected tests: all caught.

### 27. Feeder server: 40 ms per register read over Ethernet (Nagle + delayed ACK)

**Symptom:** while recording GIFs, `NetBoard.rd()` took 40 ms, `capture()` 135 ms and `read_boxes()` 200 ms; a lock-step step took about 1 s instead of 0.15 s. `PING` and `WR` (single small reply) took 2-3 ms, `RD` and `STAT` (header, then payload) 40 ms. **Root cause:** `reply()` sent the 16-byte header and the payload as two small `send()` calls; the second one waited for the ACK of the first (delayed ACK, 40 ms) even with `TCP_NODELAY` on the accepted socket. The mock tests ran on loopback where this does not happen. **Fix:** the header goes out with `MSG_MORE`, so header and payload leave as one stream. Register read 1.1 ms, capture 49 ms, box list 1 ms. **Lesson:** loopback tests cannot see Nagle/ACK interactions; time every request type on the real network.
