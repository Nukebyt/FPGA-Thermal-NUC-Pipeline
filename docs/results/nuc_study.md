# NUC variant study (float models)

T = 300 frames, 240x320, seed 3. Metric: global-affine-aligned RMSE vs clean (counts, mean of last 20 frames), roughness of the last frame (clean scene ~0.0085), frames to reach RMSE < raw/4.

## moving camera, mild (raw RMSE 125, bad pixels 0.01 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 122.3 | 0.0489 | None |
| const-stat | 253.1 | 0.0090 | None |
| lms fixed-clip | 15.1 | 0.0086 | 16 |
| lms adapt-clip | 10.8 | 0.0086 | 16 |
| lms adapt-skip | 32.4 | 0.0095 | 26 |
| lms offs-only | 12.0 | 0.0086 | 40 |
| lms +gate(cam) | 10.7 | 0.0086 | 18 |

## moving camera, typical (raw RMSE 257, bad pixels 0.08 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 249.6 | 0.1279 | None |
| const-stat | 253.2 | 0.0098 | None |
| lms fixed-clip | 24.5 | 0.0095 | 26 |
| lms adapt-clip | 24.3 | 0.0094 | 30 |
| lms adapt-skip | 187.7 | 0.0424 | None |
| lms offs-only | 30.3 | 0.0100 | 62 |
| lms +gate(cam) | 23.7 | 0.0094 | 30 |

## moving camera, severe (raw RMSE 319, bad pixels 0.38 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 308.1 | 0.2775 | None |
| const-stat | 253.5 | 0.0118 | None |
| lms fixed-clip | 47.1 | 0.0117 | 84 |
| lms adapt-clip | 50.1 | 0.0118 | 102 |
| lms adapt-skip | 267.7 | 0.1396 | None |
| lms offs-only | 65.2 | 0.0135 | 174 |
| lms +gate(cam) | 49.1 | 0.0117 | 96 |

## static camera, mild (raw RMSE 128, bad pixels 0.01 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 127.4 | 0.0488 | None |
| const-stat | 436.9 | 0.0175 | None |
| lms fixed-clip | 52.4 | 0.0040 | 20 |
| lms adapt-clip | 48.3 | 0.0039 | 20 |
| lms adapt-skip | 56.1 | 0.0059 | None |
| lms offs-only | 39.2 | 0.0043 | 46 |
| lms +gate(cam) | 103.7 | 0.0482 | None |

## static camera, typical (raw RMSE 288, bad pixels 0.08 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 289.7 | 0.1271 | None |
| const-stat | 436.9 | 0.0191 | None |
| lms fixed-clip | 56.1 | 0.0057 | 22 |
| lms adapt-clip | 53.9 | 0.0056 | 24 |
| lms adapt-skip | 210.8 | 0.0408 | None |
| lms offs-only | 49.1 | 0.0063 | 50 |
| lms +gate(cam) | 53.5 | 0.0056 | 24 |

## static camera, severe (raw RMSE 385, bad pixels 0.38 %)

| variant | final RMSE | roughness | conv frame |
|---|---|---|---|
| none | 387.7 | 0.2747 | None |
| const-stat | 437.0 | 0.0213 | None |
| lms fixed-clip | 70.2 | 0.0087 | 66 |
| lms adapt-clip | 70.7 | 0.0088 | 84 |
| lms adapt-skip | 323.5 | 0.1511 | None |
| lms offs-only | 77.3 | 0.0101 | 146 |
| lms +gate(cam) | 69.9 | 0.0087 | 78 |

## Ghosting: stationary hot object starts moving at frame 120 (typical noise)

Ghost = mean(output - clean) over the object's initial footprint (eroded), frames 200..end; burn-in shows as a negative value. Object contrast is +1500 counts.

| variant | static camera | moving camera |
|---|---|---|
| none | 34.6 | n/a |
| const-stat | -37.1 | n/a |
| lms fixed-clip | -94.6 | n/a |
| lms adapt-clip | -105.9 | n/a |
| lms adapt-skip | -12.5 | n/a |
| lms offs-only | 3.3 | n/a |
| lms +gate(cam) | -105.0 | n/a |
