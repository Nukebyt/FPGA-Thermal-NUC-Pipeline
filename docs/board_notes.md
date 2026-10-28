# Board notes (DE10-Standard, Cyclone V 5CSXFC6D6F31C6)

Facts with their source. "TBD (HW)" needs the physical board. Most of this is inherited from `FPGA-Adaptive-Night-Vision/docs/board_notes.md`, which in turn cites the earlier CFAR project; I did not re-verify the inherited items on a board.

## Verified on this machine
* Quartus Prime Lite 21.1 at `C:\intelFPGA_lite\21.1\quartus\bin64` (not on the PowerShell PATH; `scripts/build_quartus.sh` adds it). `quartus_map` of `nuc_core` at production size succeeds (M10K inference, 5 DSP).
* Icarus Verilog 14 at `C:\iverilog\bin`. Python 3.13 venv in `.venv/`.
* `jtagconfig` (2026-10-26, board on USB): `1) DE-SoC [USB-1]`: device 1 `4BA00477 SOCVHPS` (ARM DAP), device 2 `02D020DD 5CSEBA6(.|ES)/5CSEMA6/..` (the FPGA; the same IDCODE covers 5CSXFC6). **FPGA = `@2`.** Program with `quartus_pgm -c "DE-SoC [USB-1]" -m jtag -o "p;<file>.sof@2"` (checklist 2.4a). Build 2 configured this way: "Configuration succeeded", checksum 0x0A3E5873.
* **First bring-up, build 2 (2026-10-26, all switches down = NUC, learning, bad-pixel repair, overlay, noise off):** LEDR0-1 blinking, LEDR2-5 on (PLL locked, out of reset, ready, motion), LEDR6-8 off (no bad pixels expected with noise off; no box overflow; no retimer overrun), LEDR9 flickering (gain gate). HEX page 1 `xx2214`, page 2 `002214`, page 3 `000000`: **end-of-frame -> box list latency 8,724 cycles = 349 us at 25 MHz, min = max on hardware, identical to simulation.**
* Same session, demo switches (SW0-5 up, SW6-7 down, SW8 up, SW9 down): LEDR6 on (bad pixels found; the model flags 90 from frame 8); page 3 stays `000000` with every setting tried; KEY1 (coefficient clear) keeps the frame counter running, LEDR4 on, LEDR7/8 off; preset `severe` (SW5 down, SW6 up) the same.
* **Build 5 and the laptop viewer (2026-10-27):** with the JTAG clock at the cable's default 24 MHz every host-bus read hangs (bug log 22); `jtagconfig --setparam 1 JtagClock 6M` fixes it (`host/viewer.py` sets it). Then: ID `7A110005`, a captured frame (number 7,730 after reset, corrected) identical to the model in all 76,800 pixels (Gate 1 on hardware), latency end-of-frame -> boxes **min = max = 8,724 cycles (349.0 us), jitter 0 over 69,510 frames** (roadmap 6.4). Viewer speed over JTAG: 0.2 frames/s side by side, 0.4 with one view. With the NUC on and learning frozen (window 256) a static scene is visibly smoothed (the over-smoothing limit of bug log 18/19).
* **HPS / Linux (3b):** nothing about the HPS has been verified on this design yet: `docs/bringup_3b.md` is the plan. The Linux SD card and the Ethernet / console setup are the Weibull-CFAR project's (its `launchfpga.txt`); this project's `quartus/ip/hps_sys` reuses that project's HPS configuration.
* No VGA monitor available at the first bring-up: the picture is checked through a JTAG viewer instead (roadmap, Phase 3c).

## Pins
* `quartus/pins/de10_pins.tcl` is a copy of the sister project's file, which is generated from the Terasic golden top (`FPGA-Adaptive-Night-Vision/scripts/gen_pins.sh`): CLOCK_50, KEY[3:0], SW[9:0], LEDR[9:0], HEX0-5, VGA (ADV7123, 8 bit per channel). The CLOCK_50/LEDR/HEX groups match the CFAR project's board_check pins (proven on a board there).
* `quartus/pins/gpio_pins.tcl`: `GPIO[0]` = PIN_W15, `GPIO[1]` = PIN_AK2, 3.3-V LVTTL, read from the same golden top. Scope markers (roadmap 6.5). **Not yet verified on a board.**
* `SW[*]` are 2.5 V in the golden top; VGA_SYNC_N tied low (separate HS/VS).

## Design decisions affecting the board
* One 25.000 MHz PLL output drives the whole design and `VGA_CLK`; `locked` gates the reset (no exposure window, checklist 2.6). `derive_pll_clocks` is in the SDC; `scripts/check_sta.py` requires the PLL clock name in the slack tables.
* VGA output timing against the ADV7123 is not constrained (same clock for data and DAC clock, 40 ns period). Revisit with `set_output_delay` if the picture shows edge artefacts.
* Fitter warning 15714 "Missing drive strength and slew rate" is expected and accepted (same as the Terasic golden top).

## From the earlier projects (not re-verified here)
* Boot-mode switch `SW10 MSEL[4:0]` must be `01010` (FPPx32) for the HPS to load the FPGA image; the factory default `10010` silently boots in AS mode.
* Linux login `root`, empty password; UART J4 (FT232R, 115200 8N1).
* **OS image conflict to resolve in task 0.6:** the checklist says Angstrom 2014 (Python 2.7 only, ~51 MB free); the CFAR notes say Terasic Ubuntu 16.04 console. Write down what is actually on the SD card and which compilers exist. The plan assumes C only on the HPS.
* The sister project points at a proven HPS/DDR3 Qsys base (`de10_ghrd/soc_system.qsys`, `hps_common_board_info.xml` in the CFAR folder) for the Phase 3b starting point. Lightweight bridge at `0xFF200000`, span `0x200000`; **read the offset of `csr_regs` from the generated `.sopcinfo`, not from this file** (checklist 5).

## Switch / key / LED map of this design
See the header comment of `rtl/thermal_board.v` (SW0 NUC, SW1 learning, SW2 bad-pixel replace, SW3 boxes, SW4 sensor non-uniformity, SW6:5 preset, SW8:7 view, SW9 iron palette; KEY1 clear coefficients, KEY2 reset detector, KEY3 HEX page).

## Bring-up order on the board (checklist 4)
1. Program the sister project's `bringup` design first if there is any doubt about the board, cable or monitor (known-good calibration design, checklist 4.5).
2. Program `thermal.sof` with the explicit `@N`. Expect: LEDR2/3/4 on, picture appears, frame counter on HEX increments.
3. **Gate 0:** press KEY1 (clear coefficients) four times with identical settings; the emulator is deterministic, so frames after the same number of frames since the clear must look identical; with the CSR bus (3b) read back coefficients and compare.
4. **Gate 1:** against the model (`scripts/check_vga.py` equivalent on captured frames, or SignalTap).
5. Only then measure latency (HEX page 3 = 000000) and quote it.
