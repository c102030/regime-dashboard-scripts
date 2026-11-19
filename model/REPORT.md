# Recession models: what the checks show

Written by `model/validate.py` from the data snapshot of 2026-11-18. Rerun it to reproduce every figure.

Each model estimates the chance that at least one of the next twelve months is a recession month (NBER dates for the United States, CODACE dates for Brazil). The scores below use today's revised data, not the figures available at each date, and the inputs were chosen with the whole sample in view, so they flatter the models. AUC measures ranking, not accuracy or calibration. Brier skill is the share of the base-rate forecast's squared error that the model removes: zero or less means no better than always answering the historical share.

## United States: production

Inputs: spread, permits, nfci. Fitted on 1972-01 to 2024-10, 7 recessions. Coefficients: const -0.3058, spread -0.4781, permits -0.0222, nfci +0.9837.

| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |
|---|---|---|---|---|---|---|
| In sample, 1972-01 to 2024-10 | 634 | 0.93 (0.87 to 0.97) | 0.93 | 0.084 vs 0.181 | +0.54 (+0.35 to +0.70) | 0.268 vs 0.549 |
| Leave one recession out, 1972-01 to 2021-04 | 301 | 0.88 (0.80 to 0.94) | 0.88 | 0.170 vs 0.319 | +0.47 (+0.25 to +0.65) | 0.528 vs 0.855 |
| Walk forward, 1990-01 to 2024-10 | 418 | 0.85 (0.73 to 0.95) | 0.88 | 0.124 vs 0.165 | +0.25 (-0.17 to +0.60) | 0.381 vs 0.516 |

Calibration, walk forward: forecast 0-10% (266 months, mean 2.5%) was followed by a recession 3.0% of the time; forecast 10-25% (60 months, mean 16.3%) was followed by a recession 33.3% of the time; forecast 25-50% (31 months, mean 36.1%) was followed by a recession 61.3% of the time; forecast 50-75% (41 months, mean 64.5%) was followed by a recession 46.3% of the time; forecast 75-100% (20 months, mean 88.6%) was followed by a recession 45.0% of the time.

## United States: curve only

Inputs: spread. Fitted on 1972-01 to 2024-10, 7 recessions. Coefficients: const -0.1186, spread -0.4536.

| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |
|---|---|---|---|---|---|---|
| In sample, 1972-01 to 2024-10 | 634 | 0.77 (0.66 to 0.87) | 0.91 | 0.148 vs 0.181 | +0.18 (+0.01 to +0.32) | 0.464 vs 0.549 |
| Leave one recession out, 1972-01 to 2021-04 | 301 | 0.73 (0.64 to 0.83) | 0.89 | 0.263 vs 0.319 | +0.18 (+0.04 to +0.30) | 0.779 vs 0.855 |
| Walk forward, 1990-01 to 2024-10 | 418 | 0.67 (0.52 to 0.83) | 0.86 | 0.182 vs 0.165 | -0.10 (-0.48 to +0.19) | 0.548 vs 0.516 |

Calibration, walk forward: forecast 0-10% (108 months, mean 5.1%) was followed by a recession 11.1% of the time; forecast 10-25% (92 months, mean 17.2%) was followed by a recession 13.0% of the time; forecast 25-50% (110 months, mean 36.0%) was followed by a recession 10.9% of the time; forecast 50-75% (82 months, mean 60.7%) was followed by a recession 41.5% of the time; forecast 75-100% (26 months, mean 80.0%) was followed by a recession 19.2% of the time.

## Brazil: production

Inputs: dselic, ibc. Fitted on 2003-07 to 2024-12, 3 recessions. Coefficients: const -0.3817, dselic +0.0618, ibc -0.1015.

| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |
|---|---|---|---|---|---|---|
| In sample, 2003-07 to 2024-12 | 258 | 0.76 (0.60 to 0.87) | 0.58 | 0.171 vs 0.211 | +0.19 (+0.01 to +0.33) | 0.512 vs 0.613 |
| Leave one recession out, 2006-10 to 2021-06 | 153 | 0.70 (0.61 to 0.80) | 0.58 | 0.312 vs 0.293 | -0.07 (-0.18 to +0.06) | 0.865 vs 0.786 |
| Walk forward, 2012-01 to 2024-12 | 156 | 0.57 (0.33 to 0.81) | 0.51 | 0.288 vs 0.298 | +0.03 (-0.50 to +0.26) | 0.777 vs 0.833 |

Calibration, walk forward: forecast 0-10% (7 months, mean 3.4%) was followed by a recession 0.0% of the time; forecast 10-25% (58 months, mean 18.0%) was followed by a recession 31.0% of the time; forecast 25-50% (64 months, mean 35.7%) was followed by a recession 60.9% of the time; forecast 50-75% (13 months, mean 63.3%) was followed by a recession 15.4% of the time; forecast 75-100% (14 months, mean 83.3%) was followed by a recession 14.3% of the time.

## Brazil: activity as published

Inputs: dselic, ibc_known. Fitted on 2003-09 to 2024-12, 3 recessions. Coefficients: const -0.4303, dselic +0.0893, ibc_known -0.0469.

| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |
|---|---|---|---|---|---|---|
| In sample, 2003-09 to 2024-12 | 256 | 0.70 (0.52 to 0.84) | 0.57 | 0.193 vs 0.212 | +0.09 (-0.13 to +0.23) | 0.561 vs 0.615 |
| Leave one recession out, 2006-10 to 2021-06 | 153 | 0.72 (0.59 to 0.81) | 0.66 | 0.350 vs 0.292 | -0.20 (-0.29 to -0.07) | 0.948 vs 0.784 |
| Walk forward, 2012-01 to 2024-12 | 156 | 0.55 (0.29 to 0.81) | 0.56 | 0.340 vs 0.298 | -0.14 (-0.90 to +0.18) | 0.940 vs 0.830 |

Calibration, walk forward: forecast 0-10% (19 months, mean 6.2%) was followed by a recession 0.0% of the time; forecast 10-25% (54 months, mean 18.7%) was followed by a recession 44.4% of the time; forecast 25-50% (58 months, mean 32.6%) was followed by a recession 63.8% of the time; forecast 50-75% (7 months, mean 64.7%) was followed by a recession 0.0% of the time; forecast 75-100% (18 months, mean 89.2%) was followed by a recession 0.0% of the time.

## Brazil: policy rate only

Inputs: dselic. Fitted on 2003-07 to 2024-12, 3 recessions. Coefficients: const -0.5045, dselic +0.0895.

| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |
|---|---|---|---|---|---|---|
| In sample, 2003-07 to 2024-12 | 258 | 0.69 (0.52 to 0.83) | 0.64 | 0.203 vs 0.211 | +0.04 (-0.16 to +0.14) | 0.584 vs 0.613 |
| Leave one recession out, 2006-10 to 2021-06 | 153 | 0.76 (0.63 to 0.88) | 0.83 | 0.331 vs 0.293 | -0.13 (-0.24 to +0.04) | 0.891 vs 0.786 |
| Walk forward, 2012-01 to 2024-12 | 156 | 0.54 (0.29 to 0.83) | 0.55 | 0.337 vs 0.298 | -0.13 (-0.83 to +0.17) | 0.933 vs 0.833 |

Calibration, walk forward: forecast 0-10% (11 months, mean 6.3%) was followed by a recession 0.0% of the time; forecast 10-25% (69 months, mean 18.3%) was followed by a recession 42.0% of the time; forecast 25-50% (53 months, mean 31.5%) was followed by a recession 60.4% of the time; forecast 50-75% (7 months, mean 61.6%) was followed by a recession 0.0% of the time; forecast 75-100% (16 months, mean 89.5%) was followed by a recession 0.0% of the time.

## Limits

- No real-time vintages: building permits, the Chicago Fed index and Brazil's activity index are all revised after first publication.
- Brazil's activity index is published about two months late. The dashboard therefore dates Brazil's reading by the newest month with both inputs.
- The last two years (United States) are outside the fit because recessions are dated with a delay.
- Intervals come from a moving-block bootstrap (24-month blocks, 1,000 draws): with so few recessions they are wide and themselves uncertain.
