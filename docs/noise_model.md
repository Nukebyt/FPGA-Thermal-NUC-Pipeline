# Sensor non-uniformity model: parameters and their justification

Implemented in `model/noise_model.py`. This is the main risk of the project (roadmap 1.4): the noise is **simulated**, and every number below is a stated assumption unless marked otherwise. State that plainly in the README and the demo.

## Structure

`raw = clip( g*s + o + col + row + drift(t) + n(t) )`, then dead pixels forced to 0 and hot pixels to full scale. `s` is the clean scene in 14-bit counts, so the ground truth is exact. This is the standard linear per-pixel response model used throughout the scene-based NUC literature (gain and offset per detector, Gaussian temporal noise), plus the column/row pattern and slow drift that real readouts show.

## Parameters

| Parameter | mild | typical | severe | Basis |
|---|---|---|---|---|
| gain sigma_g (relative) | 0.02 | 0.05 | 0.10 | **Assumption.** Papers on scene-based NUC simulate gain spread of a few percent up to roughly 10 to 20 %. I could not open the papers during setup; **verify against Torres & Hayat 2003 and Vera & Torres 2005 before quoting a literature range.** |
| offset sigma_o (counts) | 30 | 100 | 250 | **Assumption.** Scene span in the test clips is ~4000 counts, so these are 0.75 %, 2.5 %, 6 % of span. Uncooled arrays before factory two-point correction can be much worse; this is a post-factory-calibration drift regime. |
| column sigma_col (counts) | 5 | 20 | 50 | **Assumption.** Column/row FPN comes from readout channels. |
| row sigma_row (counts) | 0 | 5 | 15 | **Assumption.** |
| temporal sigma_t (counts) | 3 | 8 | 15 | **Assumption.** Roughly 50 mK NETD at about 100-200 counts/K would give 5-10 counts; the counts-per-kelvin figure is itself device specific. |
| drift (counts/frame, random-walk step) | 0.005 | 0.02 | 0.05 | **Assumption.** After 1000 frames: sigma of 0.16 / 0.63 / 1.6 counts. Slow compared with the NUC's tracking rate (~16 frames); it exercises tracking, not the headline result. |
| dead rate | 0.01 % | 0.05 % | 0.2 % | **Assumption.** Typical sensor operability specs are 99.5 to 99.99 %; severe is deliberately worse than a normal grade. Dead = stuck at 0, hot = stuck at full scale, which is the simplest case the bad-pixel detector must handle. |
| hot rate | 0.01 % | 0.05 % | 0.2 % | as above |

The severe preset is meant to stress the algorithm, not to describe a specific camera.

## What is and is not modelled

* Not modelled: gain/offset dependence on FPA temperature, 1/f temporal noise, blinking pixels, non-linear response, optics roll-off (vignetting), and the camera's own shutter calibration events. Vignetting in particular is a smooth gain error that a neighbour-averaging NUC would partly *keep*. A real-sensor claim would need those.
* The CDnet and FLIR frames already contain a real camera's residual noise. We treat them as clean and add the simulated noise on top.
* Seeds: static maps use `seed`, temporal noise `seed+1`, drift `seed+2`. Same (preset, scene) pair always reproduces the same clip.

## References to read (details to be verified before citing)

* Scribner et al., adaptive NUC for IR focal-plane arrays using neural networks, SPIE 1991: the LMS / neural-network NUC this design is based on.
* Harris & Chiang, constant-statistics NUC, SPIE 3061 (1997) and IEEE Trans. Image Processing 8(8) (1999): the baseline used for comparison.
* Hardie et al., scene-based NUC with video sequences and registration, Applied Optics 39(8) (2000).
* Torres & Hayat, Kalman filtering for adaptive NUC in IR focal-plane arrays, JOSA A 20(3) (2003).
* Vera & Torres, fast adaptive NUC for IR focal-plane arrays, EURASIP J. Adv. Signal Process. (2005).
* Means, Von Tersch & Scribner (1999): real-time adaptive neural-network NUC on a 12-bit uncooled microbolometer camera.
