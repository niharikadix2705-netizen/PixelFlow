# PixelFlow

An event-driven image processing pipeline. Users upload images, a Redis queue distributes the work to a pool of Docker workers, and results are downloaded when ready.

## Features

- Crop, resize, rotate, flip, brightness, contrast, saturation, filters
- PNG, JPEG and WebP output with quality setting
- Batch upload with before/after preview
- Crash-safe queue with recovery, retries and dead-letter list
- Upload validation, size limits and key expiry
- /health and /metrics endpoints
- 31 automated tests and a 1 vs 3 workers benchmark

## Run it

Requires Docker Desktop.

    docker compose up --build --scale worker=3

Open http://localhost:8000

## Benchmark: 1 worker vs 3 workers

30 identical jobs (upscale a small image to 6 megapixels, blur, save as JPEG), run with `python benchmark.py`.

| Workers | Total time | Jobs/sec | Median per job | p95 per job |
|---|---|---|---|---|
| 1 | 5.9 s | 5.09 | 181.7 ms | 251.2 ms |
| 3 | 3.2 s | 9.33 | 286.5 ms | 323.5 ms |

Throughput rose 1.84x with 3 workers. Scaling is below 3x because the workers share the host CPU, one Redis instance and one disk volume. Each configuration was run once on one machine, so treat the numbers as indicative.
