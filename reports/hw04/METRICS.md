# HW4 Part 3 - N+1 Measurement Results

| Page size | Version | SQL stmts/req | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| 10 | naive | 11 | 9.48 | 12.83 | 15.10 |
| 10 | fixed | 1 | 4.43 | 5.30 | 7.94 |
| 50 | naive | 51 | 30.83 | 33.69 | 34.44 |
| 50 | fixed | 1 | 5.15 | 5.81 | 6.06 |
| 200 | naive | 201 | 108.29 | 147.07 | 156.00 |
| 200 | fixed | 1 | 9.31 | 10.06 | 27.64 |

## Speed-up (naive p50 / fixed p50) at each page size

- Page size 10: naive 9.48ms vs fixed 4.43ms -> **2.14x faster**
- Page size 50: naive 30.83ms vs fixed 5.15ms -> **5.99x faster**
- Page size 200: naive 108.29ms vs fixed 9.31ms -> **11.63x faster**
