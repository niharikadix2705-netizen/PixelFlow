import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worker  # noqa: E402


def make_image(width=200, height=100, color=(200, 50, 50)):
    return Image.new("RGB", (width, height), color)


def test_crop_gives_requested_size():
    img = make_image(200, 100)
    out = worker.apply_operations(img, {
        "crop_x": 10, "crop_y": 10, "crop_width": 50, "crop_height": 40
    })
    assert out.size == (50, 40)


def test_crop_outside_image_raises():
    img = make_image(200, 100)
    with pytest.raises(ValueError):
        worker.apply_operations(img, {
            "crop_x": 0, "crop_y": 0, "crop_width": 900, "crop_height": 900
        })


def test_resize_gives_requested_size():
    img = make_image(200, 100)
    out = worker.apply_operations(img, {"resize_width": 80, "resize_height": 60})
    assert out.size == (80, 60)


def test_resize_over_limit_raises():
    img = make_image(200, 100)
    with pytest.raises(ValueError):
        worker.apply_operations(img, {"resize_width": 6000, "resize_height": 6000})


def test_rotate_90_swaps_width_and_height():
    img = make_image(200, 100)
    out = worker.apply_operations(img, {"rotation": 90})
    assert out.size == (100, 200)


def test_rotate_180_keeps_size():
    img = make_image(200, 100)
    out = worker.apply_operations(img, {"rotation": 180})
    assert out.size == (200, 100)


def test_invalid_rotation_raises():
    img = make_image()
    with pytest.raises(ValueError):
        worker.apply_operations(img, {"rotation": 45})


def test_flip_horizontal_mirrors_pixels():
    img = make_image(100, 50)
    img.putpixel((0, 0), (0, 0, 255))
    out = worker.apply_operations(img, {"flip_horizontal": True})
    assert out.getpixel((99, 0)) == (0, 0, 255)


def test_flip_vertical_mirrors_pixels():
    img = make_image(100, 50)
    img.putpixel((0, 0), (0, 0, 255))
    out = worker.apply_operations(img, {"flip_vertical": True})
    assert out.getpixel((0, 49)) == (0, 0, 255)


def test_grayscale_makes_single_channel():
    img = make_image()
    out = worker.apply_operations(img, {"filter_name": "grayscale"})
    assert out.mode == "L"


def test_sepia_keeps_size_and_is_rgb():
    img = make_image()
    out = worker.apply_operations(img, {"filter_name": "sepia"})
    assert out.size == img.size
    assert out.mode == "RGB"


def test_blur_and_sharpen_keep_size():
    img = make_image()
    for name in ("blur", "sharpen"):
        out = worker.apply_operations(img, {"filter_name": name})
        assert out.size == img.size


def test_unknown_filter_raises():
    img = make_image()
    with pytest.raises(ValueError):
        worker.apply_operations(img, {"filter_name": "nonsense"})


def test_brightness_makes_image_brighter():
    img = make_image(color=(100, 100, 100))
    out = worker.apply_operations(img, {"brightness": 1.5})
    assert out.getpixel((0, 0))[0] > 100


def test_brightness_zero_makes_image_black():
    img = make_image(color=(100, 100, 100))
    out = worker.apply_operations(img, {"brightness": 0.0})
    assert out.getpixel((0, 0)) == (0, 0, 0)


def test_default_options_leave_image_unchanged():
    img = make_image(120, 80)
    out = worker.apply_operations(img, {})
    assert out.size == (120, 80)
    assert out.tobytes() == img.tobytes()

def test_normalize_mode_converts_palette_images():
    img = Image.new("P", (10, 10))
    out = worker.normalize_mode(img)
    assert out.mode == "RGBA"