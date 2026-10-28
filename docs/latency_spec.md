# Latency specification (roadmap task 6.1)

Clock: 25.000 MHz (40 ns), derived from CLOCK_50 by the PLL. All numbers are clock cycles of that clock.

## Definitions

| Symbol | Definition |
|---|---|
| **N** | First input tick of a frame (slot (0,0), the moment the first sensor sample is presented) -> corrected pixel (0,0) valid at the output of the NUC. The same for every pixel. |
| **K** | End-of-frame input tick (slot (H,0), two slots after the last real sample) -> the published box list and motion flag (`box_done`). |
| **D** | Corrected pixel `(r,c)` -> the same pixel on the VGA connector: the display pipeline is 3 clocks after the row buffer; the row buffer holds the row for 2 VGA lines by construction (the picture is therefore delayed by the 4-line lead built into `tick_gen`). |

## Values

| | Analytic | Simulated (min = max) | Board **(HW)** |
|---|---|---|---|
| N | `1600 + 2 + 9 + 11 = 1622` (one tick row of 2 VGA lines, one slot, sensor emulator 9, NUC 11) | **1622** over 5 frames (`thermal_sys_tb`) | not measured |
| K | `5*1600 + 3*2 (last mask slot) + 9 + 11 + 3 + 16 + 643 (row retimer) + 36 = 8724` | **8724** over 5 frames | not measured |

K = 8724 cycles = 349.0 us.

## When the guarantee holds (and what breaks it)

The latency is constant *because* every stage is feed-forward with fixed depth and the input is the tick grid. It holds if and only if:

1. the input is the tick grid of `tick_gen` (fixed 2-clock spacing inside a row burst, fixed row period of 1600 clocks, fixed frame period of 420,000 clocks);
2. no CSR write changes the datapath structure in the middle of a frame (controls are sampled at the first tick of a frame, so enable toggles take effect on the next frame, and are part of the regression);
3. `retime_err` stays low (the row retimer finished replaying each row before the next completed);
4. the clock is stable (PLL locked; `locked` gates the reset).

The guarantee is about the **FPGA datapath**. The conversion of the *scene* into samples (the sensor, or the HPS DMA in Phase 3b) is outside it: with the DMA, the guarantee covers "from the moment a sample is presented on the tick bus".

## How it is measured

* **Internal counters** (`csr_regs`): a free-running 32-bit cycle counter is captured at the first input tick, the end-of-frame tick, pixel (0,0) valid and `box_done`. Registers 0x18-0x22 hold the last values and min/max over all frames since the last clear. HEX page 3 shows `K_max - K_min` (zero jitter reads `000000`).
* **External check (HW):** `GPIO[0]` toggles at the first input tick and `GPIO[1]` when the box list is published; compare the edge distance on a scope/logic analyser with `K`-related counters. (`GPIO[0]` -> `GPIO[1]` per frame is the frame period plus `K - 1 frame`, so measure the delay between the *same frame's* edges.)
* **Plausibility check [CL §4.5]:** a measurement with zero variance deserves suspicion. Here zero variance is the design's property, so the discriminating test is to change the clock (PLL output frequency) and see N and K *in cycles* stay put while the time changes proportionally.

## ARM comparison (task 6.6, HW)

Per-frame latency of the same algorithm in C on the HPS under Linux (`clock_gettime`, 100,000+ frames, with and without background load; optionally `SCHED_FIFO` + isolated CPU). Report mean, p99.9, max and the histogram. Not started.
