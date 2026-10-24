import time
from io import BytesIO

import requests
from PIL import Image

BASE = "http://localhost:8000"


def png_bytes(width=200, height=100):
    buf = BytesIO()
    Image.new("RGB", (width, height), (30, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def upload(data=None, content=None, name="test.png"):
    content = content if content is not None else png_bytes()
    return requests.post(
        BASE + "/upload",
        files={"file": (name, content, "application/octet-stream")},
        data=data or {},
        timeout=15,
    )


def wait_for_job(job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = requests.get(f"{BASE}/status/{job_id}", timeout=10).json()
        if info["status"] in ("completed", "failed"):
            return info
        time.sleep(0.5)
    raise AssertionError("Job did not finish in time")


def test_health():
    r = requests.get(BASE + "/health", timeout=10)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_metrics_has_expected_keys():
    r = requests.get(BASE + "/metrics", timeout=30)
    assert r.status_code == 200
    body = r.json()
    for key in ("jobs_total", "jobs_by_status", "queue_length",
                "in_processing_list", "dead_letter_length"):
        assert key in body


def test_non_image_rejected():
    r = upload(content=b"this is not an image", name="fake.jpg")
    assert r.status_code == 400
    assert "valid image" in r.json()["detail"]


def test_oversized_file_rejected():
    r = upload(content=b"0" * (10 * 1024 * 1024 + 10), name="big.png")
    assert r.status_code == 413


def test_invalid_rotation_rejected():
    assert upload({"rotation": "45"}).status_code == 400


def test_invalid_filter_rejected():
    assert upload({"filter_name": "nonsense"}).status_code == 400


def test_resize_over_limit_rejected():
    r = upload({"resize_width": "6000", "resize_height": "6000"})
    assert r.status_code == 400


def test_resize_needs_both_dimensions():
    assert upload({"resize_width": "100"}).status_code == 400


def test_invalid_output_format_rejected():
    assert upload({"output_format": "gif"}).status_code == 400


def test_valid_image_completes_and_downloads():
    r = upload({"resize_width": "100", "resize_height": "50"})
    assert r.status_code == 200
    info = wait_for_job(r.json()["job_id"])
    assert info["status"] == "completed"
    assert info["attempts"] == "1"
    assert float(info["duration_ms"]) > 0

    d = requests.get(f"{BASE}/download/{info['filename']}", timeout=10)
    assert d.status_code == 200
    assert Image.open(BytesIO(d.content)).size == (100, 50)


def test_webp_output():
    r = upload({"output_format": "webp", "quality": "80"})
    info = wait_for_job(r.json()["job_id"])
    assert info["status"] == "completed"
    assert info["filename"].endswith(".webp")


def test_bad_crop_job_fails_cleanly():
    r = upload({"crop_width": "900", "crop_height": "900"})
    info = wait_for_job(r.json()["job_id"])
    assert info["status"] == "failed"
    assert "Crop area" in info["error"]


def test_unknown_job_returns_404():
    assert requests.get(BASE + "/status/doesnotexist", timeout=10).status_code == 404


def test_download_rejects_path_tricks():
    r = requests.get(BASE + "/download/..%2Fmain.py", timeout=10)
    assert r.status_code in (400, 404)