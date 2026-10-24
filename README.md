\# PixelFlow



An event-driven image processing pipeline. Users upload images, a queue distributes the work to a pool of workers, and results are downloaded when ready. Built to demonstrate cloud-style architecture (asynchronous jobs, horizontal scaling, fault tolerance) on a local Docker setup, with a design that maps to AWS.



!\[Tests](https://github.com/niharikadix2705-netizen/PixelFlow/actions/workflows/tests.yml/badge.svg)



\## Architecture



```mermaid

flowchart LR

&#x20;   U\[Browser] -->|upload| A\[FastAPI API]

&#x20;   A -->|job + image| R\[(Redis)]

&#x20;   R -->|queue| W1\[Worker 1]

&#x20;   R -->|queue| W2\[Worker 2]

&#x20;   R -->|queue| W3\[Worker 3]

&#x20;   W1 \& W2 \& W3 -->|result| V\[(Shared volume)]

&#x20;   W1 \& W2 \& W3 -->|status, timing| R

&#x20;   U -->|status / download| A

&#x20;   V --> A

```



1\. The API validates the upload and returns a job ID immediately.

2\. The image and job record are stored in Redis, and the job is added to a queue.

3\. Any free worker takes the job, processes the image, saves the result and updates the job record.

4\. The browser polls the job status and downloads the result.



\## Features



\*\*Image editing (done in the backend workers, not in the browser)\*\*

\- Crop, resize, rotate (90/180/270), flip horizontal and vertical

\- Brightness, contrast and saturation adjustment

\- Filters: grayscale, sepia, blur, sharpen

\- Output as PNG, JPEG or WebP, with a quality setting

\- Batch upload (up to 20 images), with Before/After preview



\*\*Reliability\*\*

\- Crash-safe queue: a job stays in a processing list until it finishes

\- Stale jobs from a crashed worker are recovered and requeued by other workers

\- Up to 3 attempts, then a dead-letter list

\- Duplicate protection: a finished job is never redone or overwritten

\- Graceful worker shutdown on `docker stop`

\- Expiry on stored inputs (1 hour) and job records (24 hours)



\*\*Validation and security\*\*

\- Real-image check (non-images are rejected at upload)

\- 10 MB file limit and 40-megapixel limit (protects against decompression bombs)

\- Allowed formats: JPEG, PNG, WebP

\- Download endpoint blocks path tricks

\- Redis is published on localhost only



\*\*Observability\*\*

\- `GET /health` for health checks

\- `GET /metrics`: job counts by status, queue length, median and average duration

\- Per-job timing, worker name and attempt count



\## Run it



Requires Docker Desktop.



```

docker compose up --build --scale worker=3

```



Open http://localhost:8000. Stop with `Ctrl + C`, then `docker compose down`.



\## Tests



```

pip install pytest pillow requests redis

python -m pytest tests -v

```



\- `tests/test\_operations.py`: 17 tests of the editing code (no Docker needed)

\- `tests/test\_api.py`: 14 tests against the running stack (start the stack first)



GitHub Actions runs the 17 operation tests and a Docker build on every push. The API tests run locally only.



\## Benchmark: 1 worker vs 3 workers



30 identical jobs (upscale a small image to 6 megapixels, blur, save as JPEG), run with `python benchmark.py`.



| Workers | Total time | Jobs/sec | Median per job | p95 per job |

|---|---|---|---|---|

| 1 | 5.9 s | 5.09 | 181.7 ms | 251.2 ms |

| 3 | 3.2 s | 9.33 | 286.5 ms | 323.5 ms |



Throughput rose 1.84x with 3 workers. Scaling is below 3x because the workers share the host's CPU, one Redis instance and one disk volume. Each configuration was run once, on one machine, so treat the numbers as indicative.



\## Crash recovery test



A worker was deliberately killed (`docker kill`) while processing a job. Another worker detected that the job had stopped updating, requeued it, and completed it. The final job record showed `status: completed` and `attempts: 2`.



This test also exposed a real bug: a late duplicate run could overwrite a completed job with `failed`. It was fixed so a completed job can no longer be overwritten.



\## How this maps to AWS (design, not deployed)



| Local component | AWS equivalent |

|---|---|

| Redis list (queue) | Amazon SQS, with a dead-letter queue |

| Processing list and recovery | SQS visibility timeout |

| Redis job hash | Amazon DynamoDB |

| Shared volume | Amazon S3 (with pre-signed URLs) |

| Worker containers | ECS on Fargate, scaled on queue depth |

| Logs and `/metrics` | CloudWatch |



Nothing in this repository is deployed to AWS.



\## Limitations



\- Delivery is at-least-once. If the visibility timeout is shorter than a job, a slow worker can be mistaken for a dead one and the job may run twice. Duplicate protection reduces the impact.

\- Output files are stored on a Docker volume and are not cleaned up automatically.

\- There is no user authentication.

\- Benchmark results depend on hardware and image size.



\## Future work



\- C++/OpenCV worker and a Python vs C++ comparison (an OpenCV build environment has been verified in Docker; the worker itself is not written)

\- Terraform for the AWS resources (validate and plan only)

\- LocalStack to rehearse S3/SQS/DynamoDB locally

\- Dashboard page, watermark and text overlay, presets

\- Deployment to AWS, after a cost estimate



\## Project layout



```

main.py             FastAPI API

worker.py           Image processing worker

web/index.html      Browser interface

tests/              Operation and API tests

benchmark.py        1 vs 3 workers benchmark

docker-compose.yml  Redis, API and workers

cpp\_worker/         OpenCV build check for the planned C++ worker

.github/workflows/  CI

```

