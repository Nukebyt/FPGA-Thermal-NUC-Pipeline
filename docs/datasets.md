# Datasets to download

Put everything under `data/` (gitignored). I could not open the download pages from this machine, so **every link below is from web search, not verified**; sizes are estimates. Read each licence before using results in anything public.

You do **not** need any of this to continue: `model/scenes.py` generates synthetic thermal clips with exact motion ground truth, and everything in the RTL phases is driven by them. The real data is for the headline numbers and the demo.

## Needed (2 downloads)

| # | Dataset | What it is used for | Where | Size (estimate) |
|---|---|---|---|---|
| 1 | **CDnet 2014, thermal category** (5 sequences: `corridor`, `diningRoom`, `lakeSide`, `library`, `park`) | Motion-detector benchmark. Pixel-level ground truth, 8-bit AGC'd frames, **static camera**. | http://changedetection.net : "Dataset" page, either the full 2014 dataset or the thermal category on its own. Paper: Wang et al., CVPRW 2014, doi:10.1109/CVPRW.2014.126 | under ~2 GB for thermal only (unverified) |
| 2 | **Teledyne FLIR ADAS thermal dataset v2** (thermal frames only; skip the RGB images) | NUC benchmark: real radiometric thermal scenes, **moving camera** (vehicle-mounted), 640x512 Tau 2. | https://www.flir.com/adasdataset (free, registration form). The v2 download guide was reported at https://adas-dataset-v2.flirconservator.com/#downloadguide | the full set is tens of GB; take only the thermal train/val sub-folders |

### Check this before relying on FLIR's "16-bit"
Search results disagree: the dataset page says "16-bit pre-AGC" while its file-format section says "14-bit TIFF (no AGC)". Open one `.tiff` after download and print `dtype` and `min/max` (`python -c "import cv2;a=cv2.imread('x.tiff',-1);print(a.dtype,a.min(),a.max())"`). `model/datasets.py` handles both (it re-centres and only ever compresses the range), so this only matters for how you describe the data.

### CDnet caveat that shapes the evaluation
Thermal frames are 8-bit JPEGs (already AGC'd and compressed), with sizes 720x480, 704x480, 704x480, 320x240, 352x288. The loader scales to height 240 and crops/pads to 320 wide. 8-bit data cannot show a 14-bit pipeline's headroom; it is used for detection scoring only. Use FLIR for NUC image-quality numbers.

## Optional (skip unless you want extra clips)

| Dataset | Why | Note |
|---|---|---|
| OTCBVS OSU Thermal Pedestrian (Dataset 01) | More static-camera thermal pedestrians | link not verified |
| A handful of FLIR ADAS frames in sequence order | Moving-camera clips. If frames are far apart in time, use `model.datasets.pan_clip` to build a panning clip from one still | |

## Folder layout the loaders expect

```
data/cdnet/thermal/<seq>/input/in000001.jpg ...
data/cdnet/thermal/<seq>/groundtruth/gt000001.png ...
data/cdnet/thermal/<seq>/temporalROI.txt          (and ROI.bmp, unused)
data/flir_adas/<anything>/*.tiff                   (searched recursively, sorted by name)
```

Usage once downloaded:

```python
from model import datasets as D
scene, gt, valid, first_eval = D.load_cdnet("data/cdnet/thermal", "library", max_frames=600)
fl = D.scene_from_flir(D.load_flir_thermal("data/flir_adas/thermal_train", max_frames=400))
```

`valid` is False for CDnet's "outside ROI" (85) and "unknown" (170) pixels and for frames outside `temporalROI`; pass it to `metrics.prf(..., valid=valid)`. `first_eval` is the index of the first scored frame; give the pipeline a warm-up (DET_WARM = 128 frames) before it.

## After download
Tell me the folder names; I will add `scripts/prepare_clips.py` (clips to the raw 16-bit frame files that the HPS feeder reads) and freeze the benchmark list with file checksums in `data/benchmark_manifest.json`. Parameters are tuned on synthetic clips only, never on the benchmark items.
