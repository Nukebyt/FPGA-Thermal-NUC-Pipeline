# Design document

Everything below is implemented in `rtl/` and has a bit-exact Python twin in `model/`. Numbers marked **(measured)** come from simulation logs in this repository; **(HW)** items are not measured yet because the board has not been connected.

## 1. Block diagram and clocking

```
 CLOCK_50 -> pll25 (25.000 MHz, locked) -> reset_sync (KEY0 & locked) -> everything below, one clock domain
 vga_timing (800x525, 59.5 Hz) --x,y--> tick_gen --tick/first/eof--> sensor_emu --tick/first/x--> thermal_core
                                                                                          |
   thermal_core = nuc_core -> bg_detect -> morph3 x4 -> row_retimer -> ccl_boxes          | y14, x14, bad
   disp_path (tone_win x2, row buffer, views/palette, box overlay) <----------------------+  boxes (previous frame)
   csr_regs: control, status, boxes, hardware latency counters           thermal_top: pads, buttons, LEDs, HEX, GPIO markers
```
One clock (the VGA pixel clock, 40 ns). There is no clock-domain crossing in the design. Phase 3b adds the DDR3 DMA, which is the only place a crossing will appear.

## 2. The tick grid (why every stage works the same way)

`tick_gen` turns the VGA counters into a grid of `(W+1) x (H+1+EXTRA)` slots per frame (EXTRA = 8): the W x H image, one dummy column and dummy rows. A slot ("tick") occurs on every second clock of every second VGA line, starting 4 VGA lines before the first active line. Consequences:

* A tick is always >= 2 clocks after the previous one, in bursts of `W+1` ticks (642 clocks) followed by ~960 idle clocks until the next row. Every module is tested with random spacing >= 2 (`GAPMAX`).
* A 3x3 window stage (`win3x3`) needs the tick of the pixel to the bottom right of its centre; the dummy column and rows provide those ticks at the right and bottom border, so edge replication is exact and there is no special "flush" state. A cascade of window stages starts each stage's own grid `(W+2)` ticks later than the previous one (`ORG = k*(W+2)`).
* Processed row `r` is complete 2 VGA lines before it is displayed, so the display row buffer is a plain 2-bank ping-pong.

## 3. Datapath and Q formats

Defined once in `model/pipeline_int.py` (the RTL ports copy this table).

| Signal | Format | Notes |
|---|---|---|
| x raw sample | U14.0 | |
| offset `o` | S14 = S12.2 | counts, +-2047; stored |
| gain `g` | U13 = U2.12 | 1.0 = 4096, range 0.5 .. 2.0; stored |
| `xo = (x<<2) - o` | S18.2 | |
| corrected `y` | U16 = U14.2 | `(xo*g + 2^11) >>> 12`, clamped |
| `d` | U16.2 | mean of the valid 4-neighbours via `sum * RECIP[n] + 2^15 >> 16`, `RECIP = {65536, 32768, 21845, 16384}` |
| `e = y - d` | S17.2 | clipped to `+-lim` |
| `lim` | U12.2 | `clamp((sum|e| * 41) >> 20, EMIN*4, EMAX*4)`, from the previous frame |
| offset step | | `o += (ec + 8) >>> 4` (= 2^-4 per frame) |
| gain step | | `g -= (ec*xo + 2^19) >>> 20` (= 2^-28 per count^2), only if gain learning is on this frame |
| bad-pixel counter | U4 | +1 if `y` outside `[min8 - T, max8 + T]` of the valid neighbours or `x` at a rail, else -1 |
| output | U14 | `bad ? d : y`, rounded |
| background `B` | U14.2 (16 bit) | `B += round((y<<2 - B) >> sh)`, `sh = min(7, ceil(log2(n+1)))` |
| mask | 1 bit | `|y<<2 - B| > T<<2` and detection valid (`n >= DET_WARM`) |
| activity | U32 | `sum(|y - B|)`; gain learning on if `(sum >> 16) > ACT_THR` (always on while `n <= 4`) |
| coefficient word | 31 bit | `{bpc[3:0], g[12:0], o[13:0]}`, 76,800 words in one M10K RAM |

One stage = at most one significant arithmetic operation (a multiply, a rounding shift plus clamp, an adder tree): checklist 1.10. The widest chain is 18x13 multiply -> round/clamp (two registers).

## 4. Latency ledger

Clocks of the 25 MHz clock. `T` = tick spacing inside a burst = 2.

| Stage | Latency | Where |
|---|---|---|
| sensor_emu (hash 5 + scale 1 + g,o,col,n 1 + g*S 1 + sum/clamp 1) | 9 | `sensor_emu.v` `LAT_TICK` |
| nuc_core: coefficient read, subtract, multiply, round (4) + win3x3 (3) + neighbour sums, reciprocal multiply, d/e, clip/output (4) | 11 per tick | `nuc_core.v` `LAT_TICK` |
| window-centre delay | `W+2` ticks | the result for pixel `(r,c)` exists when the tick of `(r+1,c+1)` has arrived |
| bg_detect | 3 | |
| morph3 x 4 (win3x3 3 + 1 each) | 16 | |
| row_retimer | pixel `c` of a row replays `6 + 2c` clocks after the row's last pixel | `row_retimer.v` |
| ccl_boxes | 36 cycles from the last mask pixel to `fdone` | `ccl_boxes.v` `LAT_EOF` |

**N, pixel-in -> pixel-out:** the first input tick (slot (0,0)) to the corrected pixel (0,0) is `1600 (one tick row = 2 VGA lines) + 2 + 9 (emulator) + 11 = 1622` clocks. **(measured, min = max over 5 frames)**. The same number for any pixel `(r,c)` is `1600 + 2 + 9 + 11`: it does not depend on the picture.

**K, end of frame -> motion flag:** from the end-of-frame input tick (slot (H,0)) to the published box list: the last mask pixel leaves the chain at slot `(H+5, 3)` = `5*1600 + 3*2 = 8006` clocks, plus 9 + 11 + 3 + 16 pipeline, plus the retimer replay of the last row (~643) plus 36 = **8724 clocks = 349 us** **(measured, min = max over 5 frames; analytic 8006 + 39 + 643 + 36 = 8724)**.

Both are fixed numbers of clock cycles because (a) the datapath has no data-dependent control flow in time and (b) its input is the tick grid. They are *not* a property of an arbitrary input: with the Phase 3b DMA the guarantee holds only if the DMA also presents ticks on a fixed schedule (see assumptions).

## 5. Hazards and why they cannot occur

* **Coefficient RAM read-after-write.** The word of pixel `p` is read at its tick and written back `(W+2)` ticks + ~8 clocks later; the next read of `p` is one frame later. Required: >= `(W+2)*T + 16` clocks between the last pixel of a frame and the first tick of the next (vertical blanking gives ~40,000).
* **Background RAM** likewise (written 2 clocks after the read).
* **Display row buffer.** Row `r` is written during VGA line `2r-2`, shown on lines `2r` and `2r+1`; the bank is rewritten for row `r+2` from line `2r+2` on.
* **Label line buffer / stale labels** (box extractor): a slot freed by a merge becomes reusable only after two line ends, so a stale reference in the label buffer can never point at a re-allocated slot. A hand-built mask exercises exactly this (`ccl_directed`).
* **Box list stability.** Published during vertical blanking (VGA line ~490); read by the overlay only in the active area of the next frame.

## 6. Assumptions (all checked by a flag or a test, none silent)

1. Tick spacing >= 2 clocks (all stages). Bursts of ticks separated by >= 60 idle clocks (row retimer replay finishes before the next row completes: `retime_err` sticky flag).
2. Box extractor: >= 40 idle clocks after each row and >= 80 after the last row (guaranteed by the retimer).
3. Frame gap >= `(W+2)*T + 16` clocks.
4. `EMIN, EMAX <= 1023` counts (limit register U12.2).
5. `W <= 511`, `H + EXTRA <= 511`, `W*H <= 2^17`.
6. Gain learning threshold (`ACT_THR`) is scene dependent: ~54 counts mean activity separates a panning camera (~100) from a static one (~25) in the synthetic scenes; real scenes need tuning (CSR).

## 7. Resource and timing budget

Numbers from the Quartus 21.1 runs are recorded in `docs/results/resources.md` (written by `scripts/make_resources.py` from the report files). Probe of `nuc_core` at production size (before integration): coefficient RAM inferred as M10K 76,800 x 31 = 2,380,800 bits, line buffers 34,304 + 8,704 bits, 5 DSP blocks, 1,835 registers.

## 8. Constants that exist in more than one place (checklist 1.11)

When one changes, change all.

| Constant | Places |
|---|---|
| Q formats, OF/GF/YF/KO/MUG_EXP, GMIN/GMAX, OLIM, RECIP table, BP_ON, KLIM, BP_T, EMIN/EMAX, T_MASK, KB, ACT_WARM, ACT_THR, DET_WARM, MIN_AREA | `model/pipeline_int.py` `Cfg`; `rtl/nuc_core.v` localparams/ports; `rtl/bg_detect.v`; `rtl/csr_regs.v` reset values; test benches (`bp_t 800, emin 16, emax 512`); `scripts/gen_*_vectors.py` use `Cfg` defaults |
| Emulator presets, rectangle table, seeds, FRAME_MUL | `model/sensor_emu.py`; `rtl/sensor_emu.v`, `rtl/hash32.v` (checked by `model/tests/test_sensor_emu.py`) |
| Tone window rule, palette, view logic, overlay colour | `model/display_model.py`; `rtl/tone_win.v`, `rtl/disp_path.v` (checked at pixel level by `scripts/check_vga.py`) |
| Latency constants (11, 9, 36, 3, 4) | RTL `LAT_*` localparams; the testbenches' latency ledgers |
| Box record layout `{area, ymax, xmax, ymin, xmin}` (53 bit) | `rtl/ccl_boxes.v`, `csr_regs.v`, `disp_path.v`, `tb/*`, `scripts/gen_*` |
| Background ROM | `quartus/thermal/rom_bg.hex` (generated by `scripts/make_rom.py`) |

## 9. How to run everything

```
.venv\Scripts\python.exe -m pytest -q                          # 21 Python tests
.venv\Scripts\python.exe scripts\run_regression.py              # all RTL testbenches + pytest
.venv\Scripts\python.exe scripts\run_regression.py --selftest   # proves the regression fails on injected RTL faults (slow)
bash scripts/build_quartus.sh quartus/thermal thermal CLOCK_50 divclk   # map, fit, sta, asm, compressed rbf, STA check
```
