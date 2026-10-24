from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from io import BytesIO
from pathlib import Path
from PIL import Image, UnidentifiedImageError
import json
import os
import redis
import statistics
import time
import uuid

app = FastAPI(title="PixelFlow")

r = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=6379,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5
)

OUTPUT_DIR = Path("processed_images")
OUTPUT_DIR.mkdir(exist_ok=True)
WEB_DIR = Path("web")

QUEUE = "pixelflow_jobs"
PROCESSING = "pixelflow_processing"
DEAD = "pixelflow_dead"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
INPUT_TTL = 3600
JOB_TTL = 86400

ALLOWED_FILTERS = {"none", "grayscale", "sepia", "blur", "sharpen"}
ALLOWED_FORMATS = {"png", "jpeg", "webp"}
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp"
}


def bad_request(message):
    raise HTTPException(status_code=400, detail=message)


def validate_image(contents):
    try:
        with Image.open(BytesIO(contents)) as img:
            image_format = img.format
            width, height = img.size
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        bad_request("File is not a valid image")

    if image_format not in {"JPEG", "PNG", "WEBP"}:
        bad_request("Only JPEG, PNG and WebP images are supported")

    if width * height > MAX_PIXELS:
        bad_request("Image is too large (over 40 megapixels)")


@app.get("/")
def home():
    page = WEB_DIR / "index.html"

    if page.is_file():
        return FileResponse(page)

    return {"message": "PixelFlow is running!", "docs": "/docs"}


@app.get("/health")
def health():
    try:
        r.ping()
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Redis is unavailable")
    return {"status": "ok"}


@app.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    filter_name: str = Form("none"),
    crop_x: int = Form(0),
    crop_y: int = Form(0),
    crop_width: int = Form(0),
    crop_height: int = Form(0),
    resize_width: int = Form(0),
    resize_height: int = Form(0),
    rotation: int = Form(0),
    flip_horizontal: bool = Form(False),
    flip_vertical: bool = Form(False),
    brightness: float = Form(1.0),
    contrast: float = Form(1.0),
    saturation: float = Form(1.0),
    output_format: str = Form("png"),
    quality: int = Form(90)
):
    output_format = output_format.lower()

    if filter_name not in ALLOWED_FILTERS:
        bad_request("Invalid filter")

    if rotation not in {0, 90, 180, 270}:
        bad_request("Rotation must be 0, 90, 180, or 270")

    if any(v < 0 for v in [crop_x, crop_y, crop_width, crop_height]):
        bad_request("Crop values cannot be negative")

    if (crop_width == 0) != (crop_height == 0):
        bad_request("Enter both crop width and crop height")

    if resize_width < 0 or resize_height < 0:
        bad_request("Resize dimensions cannot be negative")

    if (resize_width == 0) != (resize_height == 0):
        bad_request("Enter both resize dimensions")

    if resize_width > 5000 or resize_height > 5000:
        bad_request("Resize dimensions cannot exceed 5000 pixels")

    for name, value in [("Brightness", brightness),
                        ("Contrast", contrast),
                        ("Saturation", saturation)]:
        if not 0.0 <= value <= 3.0:
            bad_request(f"{name} must be between 0 and 3")

    if output_format not in ALLOWED_FORMATS:
        bad_request("Output format must be png, jpeg or webp")

    if not 1 <= quality <= 100:
        bad_request("Quality must be between 1 and 100")

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()

    if not contents:
        bad_request("Uploaded file is empty")

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")

    validate_image(contents)

    job_id = uuid.uuid4().hex
    original_filename = file.filename or "uploaded_image"
    now = time.time()

    options = {
        "filter_name": filter_name,
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_width": crop_width,
        "crop_height": crop_height,
        "resize_width": resize_width,
        "resize_height": resize_height,
        "rotation": rotation,
        "flip_horizontal": flip_horizontal,
        "flip_vertical": flip_vertical,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "output_format": output_format,
        "quality": quality
    }

    job_key = f"pixelflow:job:{job_id}"

    try:
        pipe = r.pipeline()
        pipe.set(f"pixelflow:input:{job_id}", contents, ex=INPUT_TTL)
        pipe.hset(job_key, mapping={
            "status": "queued",
            "original_filename": original_filename,
            "filename": "",
            "error": "",
            "attempts": 0,
            "created_at": now,
            "updated_at": now
        })
        pipe.expire(job_key, JOB_TTL)
        pipe.rpush(QUEUE, json.dumps({
            "job_id": job_id,
            "filename": original_filename,
            "options": options
        }))
        pipe.execute()
    except redis.RedisError:
        raise HTTPException(
            status_code=503,
            detail="Could not connect to the job queue"
        )

    return {
        "job_id": job_id,
        "filename": original_filename,
        "status": "queued",
        "options": options,
        "message": "Image added to the processing queue."
    }


@app.get("/status/{job_id}")
def get_job_status(job_id: str):
    try:
        job = r.hgetall(f"pixelflow:job:{job_id}")
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Redis is unavailable")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"job_id": job_id, **job}


@app.get("/metrics")
def metrics():
    try:
        counts = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
        durations = []

        for key in r.scan_iter("pixelflow:job:*", count=500):
            job = r.hgetall(key)
            status = job.get("status")

            if status in counts:
                counts[status] += 1

            if status == "completed" and job.get("duration_ms"):
                durations.append(float(job["duration_ms"]))

        return {
            "jobs_total": sum(counts.values()),
            "jobs_by_status": counts,
            "queue_length": r.llen(QUEUE),
            "in_processing_list": r.llen(PROCESSING),
            "dead_letter_length": r.llen(DEAD),
            "avg_duration_ms": round(statistics.mean(durations), 2)
            if durations else None,
            "median_duration_ms": round(statistics.median(durations), 2)
            if durations else None
        }
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Redis is unavailable")


@app.get("/download/{filename}")
def download_image(filename: str):
    suffix = Path(filename).suffix.lower()

    if suffix not in MEDIA_TYPES or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = OUTPUT_DIR / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Processed image not found")

    return FileResponse(
        path=str(file_path),
        media_type=MEDIA_TYPES[suffix],
        filename=filename
    )