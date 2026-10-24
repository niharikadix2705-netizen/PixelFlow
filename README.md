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
