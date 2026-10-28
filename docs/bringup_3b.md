# Bring-up of the HPS feeder (roadmap 3b): real clips on the board

**Status: first run on the board done 2026-10-28 (SD-card route, build 6): real CDnet footage runs through the design; results at the end of this file.** Everything below the line "On the board" is the plan for the
first run; each step says what you should see, so a failure points at one layer. Nothing here touches the SD card unless you choose
the SD route.

## What was verified without the board

| layer | how | result |
|---|---|---|
| frame store, host bus, CSRs | Icarus testbenches + mutation self-test (`scene_buf`, `host_if` feed region, CSR 0x23-0x25) | pass, every mutant caught |
| emulator in FEED mode | bit-exact against `model/sensor_emu.py` with a random frame in the store each frame (3 cases incl. odd size, objects off) | pass |
| the chase protocol on the full design | `sys_feed` (`scripts/run_regression.py --slow --only sys_feed`): a TB plays the ARM, rewrites the store row by row behind the scan while the design runs, captures the frame in which the content switches | that frame is entirely the new one (0 of 76,800 pixels differ from the model; an old-only frame would differ in 73,693); 0 deadline misses |
| ARM program | `sw/frame_feeder.c` built native, as mock FPGA and as a static ARM binary; `make -C sw test` (protocol, 90 frames back to back at 60.1 frames/s, two clients, slow writer, frozen scan) | pass; the mock's own tear detector agrees with the feeder's |
| laptop tools | `host/feed_clip.py` and `host/thermal_net.py` streamed a real CDnet clip to the mock | 0 torn |
| SoC bitstream | `quartus/thermal_soc`, archived in `releases/build6/` (`thermal_soc.sof`, `.rbf`) | 8,575 ALMs (20 %), 551 / 553 RAM blocks (only two spare), 31 DSP; STA pass at all corners, worst setup +1.7 ns (HPS domain). The two critical warnings are the HPS's dedicated DDR3 pins (no user location by design) |

## What is NOT verified (first things to look at)

1. **The lightweight-bridge write/read speed.** `frame_feeder bench` measures it. The chase needs a frame (19,200 writes) well under 16.7 ms;
   if the ARM is too slow the feeder reports `torn` (and the display shows mixed frames). Mitigation if needed: feed at 30 frames/s
   (`--repeat 2` makes every source frame last 2 display frames; the chase still never tears a frame it completes in time).
2. **The HPS side after JTAG programming** (bridges enabled?), see step 3.
3. **Ethernet throughput / Linux scheduling jitter.** 76.8 KB x 60 = 4.6 MB/s needed.
4. The `hps_sys` DDR3 sequencer files come from the Weibull-CFAR project's generated output (`quartus/ip/hps_sys/ddr3_overlay/README.md`):
   the HPS configuration is unchanged from that proven system, but this exact fabric image has never booted with Linux.

## On the board (when you want to try it)

Prerequisites: the Linux SD card of the Weibull-CFAR project (Terasic image, `SW10 MSEL = 01010`), serial console (`launchfpga.txt` there),
Ethernet to the laptop with the 192.168.137.x setup that project uses (board `192.168.137.200`).

1. **Boot Linux** as in that project, log in over SSH (`ssh root@192.168.137.200`).
2. **Copy the program**: `scp sw/frame_feeder_arm root@192.168.137.200:/home/root/frame_feeder` (static ARM binary from `make -C sw arm`;
   or copy `sw/frame_feeder.c` and `gcc -std=gnu99 -O2 -Wall -o frame_feeder frame_feeder.c` on the board).
3. **Load the FPGA image** (pick one):
   * *JTAG, non-destructive* (nothing on the SD card changes): on the laptop
     `quartus_pgm -c "DE-SoC [USB-1]" -m jtag -o "p;releases/build6/thermal_soc.sof@2"`. Then on the board `./frame_feeder info`:
     it prints `ID 7a110006 CAPS 1 ...`. If the command hangs or the ID is wrong the HPS-FPGA bridges are not enabled for the new image:
     reboot with the SD card as it is (U-Boot enables them for the image it loads), reprogram over JTAG, and run `info` again. The
     reset key for the design is KEY0.
   * *SD card*: copy `releases/build6/thermal_soc.rbf` to the card's FAT partition as `soc_system.rbf` (**first rename the existing
     `soc_system.rbf`, it is the CFAR project's bitstream**) and reboot.
4. **Measure**: `./frame_feeder bench`. Expected: scan running (about 14,400 rows in 1 s, `running`), the write time per frame, the
   capture readout time (this is the viewer's speed over the network), and 20 test feeds with `torn 0`.
5. **Serve**: `./frame_feeder serve` (port 5002), leave it running (`setsid ./frame_feeder serve > feeder.log 2>&1 < /dev/null &`).
6. **On the laptop**: `.venv\Scripts\python.exe scripts\prepare_clips.py --seq park --frames 600`, then
   `.venv\Scripts\python.exe host\feed_clip.py --host 192.168.137.200 --clip data\clips\park_0_600.u8 --repeat 2 --loop` and in a second
   window `.venv\Scripts\python.exe host\viewer.py --net 192.168.137.200 --passive`. You should see the real footage, raw on the left and
   NUC-corrected on the right (sensor noise added by the emulator), with green boxes round the moving people.
7. **Standalone (no laptop)**: copy the clip to the board (`scp data\clips\park_0_600.u8 root@...:`), `./frame_feeder play park_0_600.u8 30 loop`
   (the argument is the clip's fps; the design runs at 60 Hz so each frame is shown twice).

Controls from the viewer (keys) work as before; `host/feed_clip.py` switches the emulator's own rectangles off (`FEED_CTRL`) and selects
the default control word. `T_MASK` (CSR word 0x06) is scene dependent: see `docs/results/tmask_sweep.md` (lakeSide wants about 100,
library about 640).

## Report back

Please send: the output of `info` and `bench`, the viewer's status line, and anything that hangs. The most likely first findings are
the bridge state after JTAG programming (step 3) and the write speed (step 4).

## First run on the board (2026-10-28, build 6 from the SD card)

* Boot from the SD card (`soc_system.rbf` = build 6; the CFAR bitstream was kept as `soc_system_CFAR_CURRENT_20261028.rbf`). Linux up, `ssh root@192.168.137.200` works; the four fpga bridges `br0..br3` are `enabled`. The JTAG-programming bridge question (step 3) did not arise.
* `frame_feeder info`: `ID 7a110006  CAPS 1  FEED_CTRL 1`, scan counter running.
* `frame_feeder bench`: CSR read 0.76 us, write 0.57 us per 32-bit word, **10.9 ms for a whole frame** (budget 16.7 ms), capture readout 14.8 ms (67 frames/s for the viewer), scan 1428 rows / 100 ms (expected 1440), 20 test feeds with **torn 0**.
* `feed_clip.py --clip data/clips/library_450_900.u8 --repeat 2 --loop` from the laptop, T_MASK 640: the picture on the board is the library clip with the simulated sensor noise; the NUC output is clean, the green boxes follow the person (`work/demo/board_capture.png`, captured over `viewer.py` functions). Feeder statistics after about 900 feeds: 7 torn (0.8 %), 0 errors, longest write 17.9 ms, sustained about 49 feeds/s from the laptop.
* Still open: the board-vs-model comparison of the boxes (3b.5), the cause of the few torn frames (Linux jitter or contention with the viewer's reads) and the below-60 feed rate.

## Live demo for a screen recording

```
.venv\Scripts\python.exe host\run_demo.py --list                 # the clips and what to expect
.venv\Scripts\python.exe host\run_demo.py                         # all five clips one after the other, forever (default): raw | NUC-corrected, thermal colours, boxes
.venv\Scripts\python.exe host\run_demo.py --clip library          # one clip, looped
.venv\Scripts\python.exe host\run_demo.py --clip library,park      # your own playlist
.venv\Scripts\python.exe host\run_demo.py --clip corridor --view corrected --scale 3     # one picture: smoother (about 12 fps)
.venv\Scripts\python.exe host\run_demo.py --stop                  # stop the board's playback
```

`host/run_demo.py` starts `frame_feeder serve` on the board if needed, copies the clip to the board's `/tmp` (RAM disk, gone after a power cycle; the SD card has no room), sets `T_MASK` for the scene, resets the NUC and the detector, and starts `frame_feeder play` on the board (the ARM writes the frames itself at 30 fps, nothing is streamed from the laptop). It then opens `host/viewer.py --net --palette rainbow`; closing the window or pressing `q` stops the playback. Keys in the window: `v` view, `n` NUC off/on (nice to show), `e` sensor noise off/on, `o` boxes, `r` reset the detector, `k` clear the NUC, `s` save a PNG.

* The board must be booted from the SD card with the SoC image (build 6) and reachable at 192.168.137.200 by ssh without a password (the same ssh as in step 1 above).
* Clips (`data/clips/`, made by `scripts/prepare_clips.py`; every one starts with about 150 frames of the empty scene so the detector has a background): `library`, `corridor`, `diningRoom`, `park`, `lakeSide`. A single clip loops about every 13 s and the scene jumps back at each loop. A playlist (the default) plays each clip once, then starts the next with a clean NUC and detector (so each clip begins with about 5 s of the empty scene while the detector learns its background); the clip name and `T_MASK` are drawn on the picture.
* Viewer speed: about 6 fps side by side, 12 fps for one picture (each picture is a full capture and read-out of 76,800 bytes). The board plays the clip at the full 30 fps regardless; the viewer only samples it. While the viewer reads, about 1.5 % of the played frames are flagged torn by the feeder (ARM bus contention); one may show for a frame as a torn picture.
* Recording: Win+G (Game Bar), OBS, or ShareX on the viewer window; a scale of 2 gives 1280 pixels wide for both pictures.
