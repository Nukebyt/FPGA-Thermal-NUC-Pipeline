# Word-length sweep (integer NUC)

T=250, typical noise, seed 3. 'RMSE' = aligned RMSE vs clean in counts. Float reference for the same clips is in docs/results/nuc_study.md.

| variant | bits/px (o+g+bpc) | M10K blocks @76800 px | moving/typical | moving/severe | static/typical | static/severe |
|---|---|---|---|---|---|---|
| baseline OF4 GF12 YF2 KO4 | 33 | 248 | 26.9 | 54.5 | 52.9 | 72.3 |
| OF=0 | 29 | 218 | 26.9 | 54.5 | 52.8 | 72.3 |
| OF=2 | 31 | 233 | 26.9 | 54.5 | 52.9 | 72.3 |
| OF=3 | 32 | 240 | 26.7 | 54.5 | 52.9 | 72.4 |
| OF=6 | 35 | 263 | 26.9 | 54.5 | 52.9 | 72.3 |
| GF=8 | 29 | 218 | 34.3 | 69.6 | 50.6 | 80.8 |
| GF=10 | 31 | 233 | 28.9 | 55.4 | 50.8 | 72.9 |
| GF=14 | 35 | 263 | 26.7 | 54.5 | 52.9 | 72.3 |
| YF=0 | 33 | 248 | 26.8 | 54.6 | 52.9 | 72.4 |
| YF=1 | 33 | 248 | 26.7 | 54.6 | 53.0 | 72.4 |
| YF=3 | 33 | 248 | 26.7 | 54.5 | 52.9 | 72.3 |
| KO=3 | 33 | 248 | 26.9 | 53.9 | 55.8 | 74.4 |
| KO=5 | 33 | 248 | 27.7 | 60.4 | 51.6 | 76.1 |
| MUG_EXP=27 | 33 | 248 | 27.8 | 53.7 | 57.0 | 75.9 |
| MUG_EXP=29 | 33 | 248 | 28.0 | 57.5 | 50.4 | 72.3 |
| OF3 GF10 YF1 (small) | 30 | 225 | 28.9 | 55.4 | 50.9 | 72.9 |
| OF2 GF8 YF1 (tiny) | 27 | 203 | 34.3 | 69.6 | 50.6 | 80.9 |
