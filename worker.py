import json
import os
import signal
import socket
import time
import redis

from io import BytesIO
from pathlib import Path
from PIL import (
    Image,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError
)

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")

r = redis.Redis(
    host=REDIS_HOST,
    port=6379,
    decode_responses=True,
    socket_timeout=15,
    socket_connect_timeout=5,
    health_check_interval=30
)

# Separate connection for binary image data
rb = redis.Redis(
    host=REDIS_HOST,
    port=6379,
    decode_responses=False,
    socket_timeout=15,
    socket_connect_timeout=5,
    health_check_interval=30
)

OUTPUT_DIR = Path("processed_images")
OUTPUT_DIR.mkdir(exist_ok=True)

QUEUE = "pixelflow_jobs"
PROCESSING = "pixelflow_processing"
DEAD = "pixelflow_dead"

WORKER_NAME = socket.gethostname()
VISIBILITY_TIMEOUT = int(os.environ.get("VISIBILITY_TIMEOUT", "60"))
TEST_DELAY_SECONDS = float(os.environ.get("TEST_DELAY_SECONDS", "0"))
MAX_ATTEMPTS = 3
MAX_PIXELS = 40_000_000
JOB_TTL = 86400

Image.MAX_IMAGE_PIXELS = MAX_PIXELS

OUTPUT_FORMATS = {"png": ("PNG", "png"), "jpeg": ("JPEG", "jpg"), "webp": ("WEBP", "webp")}

running = True


def request_stop(signum, frame):
    global running
    running = False
    print("Shutdown requested. Finishing current job...")


signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)


def normalize_mode(image):
    if image.mode in ("RGB", "RGBA", "L"):
        return image
    if image.mode in ("P", "LA", "PA"):
        return image.convert("RGBA")
    return image.convert("RGB")


def adjust(image, brightness, contrast, saturation):
    if brightness == 1.0 and contrast == 1.0 and saturation == 1.0:
        return image

    alpha = None
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        image = image.convert("RGB")

    if brightness != 1.0:
        image = ImageEnhance.Brightness(image).enhance(brightness)
    if contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast)
    if saturation != 1.0 and image.mode == "RGB":
        image = ImageEnhance.Color(image).enhance(saturation)

    if alpha is not None:
        image.putalpha(alpha)

    return image


def apply_operations(image, options):
    # 1. Crop
    crop_width = int(options.get("crop_width", 0))
    crop_height = int(options.get("crop_height", 0))

    if crop_width > 0 and crop_height > 0:
        x = int(options.get("crop_x", 0))
        y = int(options.get("crop_y", 0))

        if x + crop_width > image.width or y + crop_height > image.height:
            raise ValueError("Crop area extends beyond image boundaries")

        image = image.crop((x, y, x + crop_width, y + crop_height))

    # 2. Resize
    resize_width = int(options.get("resize_width", 0))
    resize_height = int(options.get("resize_height", 0))

    if resize_width > 0 and resize_height > 0:
        if resize_width > 5000 or resize_height > 5000:
            raise ValueError("Resize dimensions cannot exceed 5000 pixels")
        image = image.resize((resize_width, resize_height), Image.Resampling.LANCZOS)

    # 3. Rotate clockwise
    rotation = int(options.get("rotation", 0))
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("Unsupported rotation")
    if rotation:
        image = image.rotate(-rotation, expand=True)

    # 4. Flip
    if options.get("flip_horizontal"):
        image = ImageOps.mirror(image)
    if options.get("flip_vertical"):
        image = ImageOps.flip(image)

    # 5. Brightness / contrast / saturation
    image = adjust(
        image,
        float(options.get("brightness", 1.0)),
        float(options.get("contrast", 1.0)),
        float(options.get("saturation", 1.0))
    )

    # 6. Filter
    filter_name = options.get("filter_name", "none")

    if filter_name == "grayscale":
        image = ImageOps.grayscale(image)
    elif filter_name == "sepia":
        gray = ImageOps.grayscale(image)
        image = ImageOps.colorize(gray, black="#3b2416", white="#f5deb3")
    elif filter_name == "blur":
        image = image.filter(ImageFilter.GaussianBlur(radius=2))
    elif filter_name == "sharpen":
        image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150))
    elif filter_name != "none":
        raise ValueError("Unsupported filter")

    return image


def finish(job_key, input_key, started, status, extra):
    # A finished job must never be overwritten by a late duplicate
    if status == "failed" and r.hget(job_key, "status") == "completed":
        print(f"Ignoring late failure for {job_key}: already completed")
        return

    finished = time.time()
    data = {
        "status": status,
        "finished_at": finished,
        "updated_at": finished,
        "duration_ms": round((finished - started) * 1000, 1)
    }
    data.update(extra)
    r.hset(job_key, mapping=data)
    r.expire(job_key, JOB_TTL)
    rb.delete(input_key)
def process_job(job):
    job_id = job["job_id"]
    input_key = f"pixelflow:input:{job_id}"
    job_key = f"pixelflow:job:{job_id}"

    # Duplicate protection: never redo a finished job
    if r.hget(job_key, "status") in ("completed", "failed"):
        print(f"Job {job_id} already finished, skipping duplicate")
        return

    started = time.time()
    r.hincrby(job_key, "attempts", 1)
    r.hset(job_key, mapping={
        "status": "processing",
        "worker": WORKER_NAME,
        "started_at": started,
        "updated_at": started
    })

    try:
        if TEST_DELAY_SECONDS > 0:
            time.sleep(TEST_DELAY_SECONDS)

        contents = rb.get(input_key)
        if contents is None:
            raise ValueError("Uploaded image data was not found")

        with Image.open(BytesIO(contents)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Image is too large")
            source.load()
            image = ImageOps.exif_transpose(source).copy()

        image = normalize_mode(image)
        options = job.get("options", {})
        image = apply_operations(image, options)

        output_format = options.get("output_format", "png")
        if output_format not in OUTPUT_FORMATS:
            raise ValueError("Unsupported output format")

        pil_format, extension = OUTPUT_FORMATS[output_format]
        quality = int(options.get("quality", 90))

        if pil_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        output_filename = f"{job_id}.{extension}"
        output_path = OUTPUT_DIR / output_filename

        if pil_format == "PNG":
            image.save(output_path, format=pil_format)
        else:
            image.save(output_path, format=pil_format, quality=quality)

        finish(job_key, input_key, started, "completed", {
            "filename": output_filename,
            "output_format": output_format,
            "output_width": str(image.width),
            "output_height": str(image.height),
            # Legacy keys kept so the current web page keeps working
            "original_width": str(image.width),
            "original_height": str(image.height),
            "error": ""
        })
        print(f"Job {job_id} completed: {output_filename}")

    except redis.exceptions.RedisError:
        # Leave the job in the processing list so recovery can retry it
        raise

    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError) as exc:
        finish(job_key, input_key, started, "failed", {"error": str(exc)})
        print(f"Job {job_id} failed: {exc}")

    except Exception as exc:
        finish(job_key, input_key, started, "failed",
               {"error": "Image processing failed"})
        print(f"Job {job_id} failed unexpectedly: {exc}")


def recover_stale_jobs():
    now = time.time()

    for job_data in r.lrange(PROCESSING, 0, -1):
        try:
            job = json.loads(job_data)
            job_id = job["job_id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            r.lrem(PROCESSING, 1, job_data)
            continue

        job_key = f"pixelflow:job:{job_id}"
        info = r.hgetall(job_key)

        if not info or info.get("status") in ("completed", "failed"):
            r.lrem(PROCESSING, 1, job_data)
            continue

        if info.get("status") != "processing":
            continue

        if now - float(info.get("updated_at", 0)) < VISIBILITY_TIMEOUT:
            continue

        # Only one worker wins this claim
        if r.lrem(PROCESSING, 1, job_data) != 1:
            continue

        attempts = int(info.get("attempts", 0))

        if attempts >= MAX_ATTEMPTS:
            r.hset(job_key, mapping={
                "status": "failed",
                "error": "Job failed after repeated worker crashes",
                "updated_at": now
            })
            r.rpush(DEAD, job_data)
            rb.delete(f"pixelflow:input:{job_id}")
            print(f"Job {job_id} moved to dead-letter list")
        else:
            r.hset(job_key, mapping={"status": "queued", "updated_at": now})
            r.rpush(QUEUE, job_data)
            print(f"Job {job_id} recovered and requeued (attempt {attempts})")


def worker_loop():
    print(f"PixelFlow worker {WORKER_NAME} started. Waiting for jobs...")
    last_recovery = 0

    while running:
        try:
            if time.time() - last_recovery > 10:
                recover_stale_jobs()
                last_recovery = time.time()

            job_data = r.blmove(QUEUE, PROCESSING, 5, "LEFT", "RIGHT")

            if not job_data:
                continue

            try:
                job = json.loads(job_data)
            except json.JSONDecodeError:
                print("Skipping malformed job message")
                r.lrem(PROCESSING, 1, job_data)
                continue

            process_job(job)
            r.lrem(PROCESSING, 1, job_data)

        except redis.exceptions.RedisError as exc:
            print(f"Redis problem: {exc}. Retrying in 2 seconds...")
            time.sleep(2)

    print("Worker stopped cleanly.")


if __name__ == "__main__":
    worker_loop()