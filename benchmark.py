import json
import statistics
import subprocess
import time
import urllib.request

BASE = "http://localhost:8000"
JOBS = 30
WORKER_COUNTS = [1, 3]
IMAGE = "body-repair.jpg"


def sh(command):
    subprocess.run(command, shell=True, check=True, capture_output=True)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.loads(response.read())


def wait_for_api():
    for _ in range(60):
        try:
            get("/health")
            return
        except Exception:
            time.sleep(2)
    raise SystemExit("API did not start. Run: docker compose logs api --tail 20")


def upload():
    result = subprocess.run(
        ["curl", "-s",
         "-F", f"file=@{IMAGE}",
         "-F", "resize_width=3000",
         "-F", "resize_height=2000",
         "-F", "filter_name=blur",
         "-F", "output_format=jpeg",
         BASE + "/upload"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)["job_id"]


def run_once(workers):
    print(f"\n=== {workers} worker(s) ===")
    sh("docker compose up -d --scale worker=0")
    wait_for_api()

    print(f"Queueing {JOBS} jobs...")
    ids = [upload() for _ in range(JOBS)]

    print(f"Starting {workers} worker(s)...")
    sh(f"docker compose up -d --scale worker={workers}")

    jobs = {}
    deadline = time.time() + 900
    while len(jobs) < JOBS and time.time() < deadline:
        for job_id in ids:
            if job_id in jobs:
                continue
            info = get(f"/status/{job_id}")
            if info["status"] in ("completed", "failed"):
                jobs[job_id] = info
        print(f"  finished {len(jobs)}/{JOBS}", end="\r")
        time.sleep(2)
    print()

    done = [j for j in jobs.values() if j["status"] == "completed"]
    failed = len(jobs) - len(done)

    start = min(float(j["started_at"]) for j in done)
    end = max(float(j["finished_at"]) for j in done)
    elapsed = end - start
    durations = sorted(float(j["duration_ms"]) for j in done)
    p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))]

    sh("docker compose up -d --scale worker=0")

    return {
        "workers": workers,
        "completed": len(done),
        "failed": failed,
        "total_seconds": round(elapsed, 1),
        "jobs_per_second": round(len(done) / elapsed, 2),
        "median_ms": round(statistics.median(durations), 1),
        "p95_ms": round(p95, 1),
    }


results = [run_once(n) for n in WORKER_COUNTS]

print("\nRESULTS")
print("workers | completed | failed | total_s | jobs/s | median_ms | p95_ms")
for r in results:
    print(f"{r['workers']:>7} | {r['completed']:>9} | {r['failed']:>6} | "
          f"{r['total_seconds']:>7} | {r['jobs_per_second']:>6} | "
          f"{r['median_ms']:>9} | {r['p95_ms']:>6}")

if len(results) == 2 and results[0]["total_seconds"] > 0:
    speedup = results[0]["total_seconds"] / results[1]["total_seconds"]
    print(f"\nSpeedup with {results[1]['workers']} workers: {speedup:.2f}x")

with open("benchmark_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved to benchmark_results.json")