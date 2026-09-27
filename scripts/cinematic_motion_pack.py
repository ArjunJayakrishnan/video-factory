#!/usr/bin/env python3
"""
CINEMATIC MOTION TEST PACK
--------------------------
Creates separate 10-second previews so you can compare:

A = Cinematic diagonal drift
B = Slow vertical pan
C = Static hold for detailed images
D = Subtle parallax-style movement
E = Crossfade-focused sequence
F = MIXED CINEMATIC (automatically alternates A/B/C/D + crossfades)

IMPORTANT:
- No zoom animation.
- No continuous resizing of the source image.
- Motion is based on integer-pixel cropping/translation where possible.
- This is designed specifically to avoid the shivering seen with zoom.

Put this file in the same folder as your existing make_video.py.

Run:
    python cinematic_motion_pack.py

Outputs:
    output/cinematic_tests/A_diagonal_drift.mp4
    output/cinematic_tests/B_vertical_pan.mp4
    output/cinematic_tests/C_static_hold.mp4
    output/cinematic_tests/D_subtle_parallax.mp4
    output/cinematic_tests/E_crossfade.mp4
    output/cinematic_tests/F_mixed_cinematic.mp4
"""

import os
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

# ============================================================
# SETTINGS
# ============================================================

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

PREVIEW_SECONDS = 5
FPS = 60
BITRATE = "18M"

IMAGE_DIR = Path("images")
AUDIO_PATH = Path("output/narration.mp3")

OUTPUT_DIR = Path("output/cinematic_tests")

# Extra canvas around the image.
# This gives us room to pan without scaling the visible frame.
OVERSIZE_FACTOR = 1.20

# Crossfade duration between scenes.
CROSSFADE_DURATION = 0.6

# How much of the oversized canvas can be travelled.
PAN_MARGIN_FACTOR = OVERSIZE_FACTOR - 1.0

# ============================================================
# HELPERS
# ============================================================

def run(cmd):
    print("\n>", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def ease_in_out(t):
    """Smooth 0->1 movement."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def load_images():
    images = []
    for p in sorted(IMAGE_DIR.iterdir()):
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            images.append(p)

    if not images:
        raise RuntimeError(f"No images found in {IMAGE_DIR.resolve()}")

    return images


def prepare_canvas(path, blur=False):
    """
    Prepare ONE oversized raster image.

    Crucially, the image is resized only once before the video starts.
    During playback we crop/translate it rather than repeatedly resizing it.
    """
    img = Image.open(path).convert("RGB")

    # Fit image into the oversized 16:9 canvas.
    canvas_w = int(VIDEO_WIDTH * OVERSIZE_FACTOR)
    canvas_h = int(VIDEO_HEIGHT * OVERSIZE_FACTOR)

    target_ratio = canvas_w / canvas_h
    src_ratio = img.width / img.height

    if src_ratio > target_ratio:
        new_h = canvas_h
        new_w = int(img.width * new_h / img.height)
    else:
        new_w = canvas_w
        new_h = int(img.height * new_w / img.width)

    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Crop to exact oversized canvas.
    left = max(0, (new_w - canvas_w) // 2)
    top = max(0, (new_h - canvas_h) // 2)
    img = img.crop((left, top, left + canvas_w, top + canvas_h))

    if blur:
        img = img.filter(ImageFilter.GaussianBlur(8))

    return img


def save_temp_image(img, name):
    tmp = OUTPUT_DIR / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    p = tmp / name
    img.save(p, quality=96)
    return p


def make_crop_clip(canvas_path, duration, motion):
    """
    Create a video from a single oversized raster.

    motion:
      diagonal
      vertical
      static
    """
    canvas = Image.open(canvas_path).convert("RGB")
    cw, ch = canvas.size

    max_x = max(0, cw - VIDEO_WIDTH)
    max_y = max(0, ch - VIDEO_HEIGHT)

    # Use MoviePy only for integer crop extraction.
    # No animated resizing.
    def crop_frame(get_frame, t):
        frame = get_frame(t)

        progress = ease_in_out(t / duration)

        if motion == "diagonal":
            # Slow diagonal drift. Alternate diagonal direction per scene
            # outside this function by supplying start/end values.
            sx, sy, ex, ey = motion_values
        elif motion == "vertical":
            sx, sy, ex, ey = motion_values
        else:
            sx, sy, ex, ey = 0, 0, 0, 0

        x = int(round(sx + (ex - sx) * progress))
        y = int(round(sy + (ey - sy) * progress))

        x = max(0, min(max_x, x))
        y = max(0, min(max_y, y))

        return frame[y:y + VIDEO_HEIGHT, x:x + VIDEO_WIDTH]

    # Static image source. The actual crop changes, not the image scale.
    base = ImageClip(str(canvas_path)).with_duration(duration)

    # MoviePy transform returns the crop window.
    return base.transform(crop_frame)


def make_static_clip(canvas_path, duration):
    """
    Static hold. The detailed image does not move at all.
    """
    img = Image.open(canvas_path).convert("RGB")

    # Center crop once.
    cw, ch = img.size
    x = max(0, (cw - VIDEO_WIDTH) // 2)
    y = max(0, (ch - VIDEO_HEIGHT) // 2)

    img = img.crop((x, y, x + VIDEO_WIDTH, y + VIDEO_HEIGHT))

    p = save_temp_image(img, "static_hold.jpg")

    return ImageClip(str(p)).with_duration(duration)


def make_parallax_style_clip(path, duration, direction):
    """
    Subtle PARALLAX-STYLE effect.

    This is deliberately conservative:
    - no zoom
    - no animated scaling
    - the original image remains sharp
    - a very soft enlarged/blurred background moves a few pixels
      behind the sharp image

    It is not AI depth estimation; it is a safe, subtle layered-depth
    treatment intended to test whether this visual language works for you.
    """

    sharp = Image.open(path).convert("RGB")

    # Fit sharp image exactly into 1920x1080.
    ratio = max(VIDEO_WIDTH / sharp.width, VIDEO_HEIGHT / sharp.height)
    sw = int(sharp.width * ratio)
    sh = int(sharp.height * ratio)
    sharp = sharp.resize((sw, sh), Image.Resampling.LANCZOS)

    left = max(0, (sw - VIDEO_WIDTH) // 2)
    top = max(0, (sh - VIDEO_HEIGHT) // 2)
    sharp = sharp.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))

    # Create a slightly oversized soft background ONCE.
    bg_w = VIDEO_WIDTH + 40
    bg_h = VIDEO_HEIGHT + 40

    bg = Image.open(path).convert("RGB")
    ratio = max(bg_w / bg.width, bg_h / bg.height)
    bw = int(bg.width * ratio)
    bh = int(bg.height * ratio)
    bg = bg.resize((bw, bh), Image.Resampling.LANCZOS)

    l = max(0, (bw - bg_w) // 2)
    t = max(0, (bh - bg_h) // 2)
    bg = bg.crop((l, t, l + bg_w, t + bg_h))
    bg = bg.filter(ImageFilter.GaussianBlur(10))

    # Darken the background very slightly so the sharp foreground separates.
    bg = ImageEnhance.Brightness(bg).enhance(0.96)

    bg_path = save_temp_image(bg, "parallax_bg.jpg")
    fg_path = save_temp_image(sharp, "parallax_fg.jpg")

    # Use static sharp foreground.
    fg = ImageClip(str(fg_path)).with_duration(duration)

    # Move only the soft background by a few pixels.
    bg_clip = ImageClip(str(bg_path)).with_duration(duration)

    if direction == "left":
        sx, sy, ex, ey = 4, 4, 0, 0
    elif direction == "right":
        sx, sy, ex, ey = 0, 4, 4, 0
    elif direction == "up":
        sx, sy, ex, ey = 4, 4, 4, 0
    else:
        sx, sy, ex, ey = 0, 0, 4, 4

    def move_bg(get_frame, t):
        frame = get_frame(t)
        progress = ease_in_out(t / duration)

        x = int(round(sx + (ex - sx) * progress))
        y = int(round(sy + (ey - sy) * progress))

        return frame[y:y + VIDEO_HEIGHT, x:x + VIDEO_WIDTH]

    bg_clip = bg_clip.transform(move_bg)

    # Composite sharp foreground over moving soft background.
    from moviepy import CompositeVideoClip
    return CompositeVideoClip([bg_clip, fg], size=(VIDEO_WIDTH, VIDEO_HEIGHT))


def add_fade(clip, fade_in=0.0, fade_out=0.0):
    from moviepy.video.fx import FadeIn, FadeOut

    if fade_in:
        clip = clip.with_effects([FadeIn(fade_in)])
    if fade_out:
        clip = clip.with_effects([FadeOut(fade_out)])

    return clip


def render(clip, output):
    output.parent.mkdir(parents=True, exist_ok=True)

    clip.write_videofile(
        str(output),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate=BITRATE,
        preset="medium",
        threads=os.cpu_count() or 4,
        logger="bar",
    )


def add_audio(clip):
    if not AUDIO_PATH.exists():
        print(f"WARNING: {AUDIO_PATH} not found. Rendering without narration.")
        return clip

    audio = AudioFileClip(str(AUDIO_PATH))

    if audio.duration > PREVIEW_SECONDS:
        audio = audio.subclipped(0, PREVIEW_SECONDS)

    return clip.with_audio(audio)


# ============================================================
# BUILD MOTION SCENES
# ============================================================

def build_scene_canvas(path, index):
    """
    Prepare the image once.
    """
    img = prepare_canvas(path, blur=False)
    return save_temp_image(img, f"canvas_{index:03d}.jpg")


def scene_positions(index, motion_type, max_x, max_y):
    """
    Return integer crop start/end positions.
    """

    if motion_type == "diagonal":
        patterns = [
            (0, 0, max_x, max_y),
            (max_x, 0, 0, max_y),
            (0, max_y, max_x, 0),
            (max_x, max_y, 0, 0),
        ]
        return patterns[index % len(patterns)]

    if motion_type == "vertical":
        patterns = [
            (max_x // 2, 0, max_x // 2, max_y),
            (max_x // 2, max_y, max_x // 2, 0),
        ]
        return patterns[index % len(patterns)]

    return (max_x // 2, max_y // 2, max_x // 2, max_y // 2)


def make_pan_clip(canvas_path, duration, index, motion_type):
    canvas = Image.open(canvas_path)
    cw, ch = canvas.size
    max_x = max(0, cw - VIDEO_WIDTH)
    max_y = max(0, ch - VIDEO_HEIGHT)

    global motion_values
    motion_values = scene_positions(index, motion_type, max_x, max_y)

    base = ImageClip(str(canvas_path)).with_duration(duration)

    def crop_frame(get_frame, t):
        frame = get_frame(t)
        p = ease_in_out(t / duration)

        sx, sy, ex, ey = motion_values

        x = int(round(sx + (ex - sx) * p))
        y = int(round(sy + (ey - sy) * p))

        x = max(0, min(max_x, x))
        y = max(0, min(max_y, y))

        return frame[y:y + VIDEO_HEIGHT, x:x + VIDEO_WIDTH]

    return base.transform(crop_frame)


def build_sequence(images, mode):
    """
    mode:
      diagonal
      vertical
      static
      parallax
      crossfade
    """

    duration_each = PREVIEW_SECONDS / max(1, min(len(images), 3))
    selected = images[:3]

    clips = []

    for i, path in enumerate(selected):
        print(f"  scene {i+1}: {path.name}")

        if mode == "static":
            clip = make_static_clip(build_scene_canvas(path, i), duration_each)

        elif mode == "parallax":
            directions = ["left", "right", "up"]
            clip = make_parallax_style_clip(path, duration_each, directions[i % 3])

        else:
            canvas = build_scene_canvas(path, i)
            clip = make_pan_clip(canvas, duration_each, i, mode)

        # Fade the first/last scene slightly.
        if i == 0:
            clip = add_fade(clip, fade_in=0.25)

        if i == len(selected) - 1:
            clip = add_fade(clip, fade_out=0.8)

        clips.append(clip)

    # Crossfade between scenes.
    final = clips[0]

    for next_clip in clips[1:]:
        final = concatenate_videoclips(
            [final, next_clip],
            method="compose",
            padding=-CROSSFADE_DURATION,
        )

    return final


def make_crossfade_test(images):
    """
    Crossfade-focused test:
    images remain completely static.
    The visual movement comes only from transitions.
    """

    duration_each = PREVIEW_SECONDS / max(1, min(len(images), 3))
    selected = images[:3]

    clips = []

    for i, path in enumerate(selected):
        clip = make_static_clip(build_scene_canvas(path, i), duration_each)
        clips.append(clip)

    final = clips[0]

    for next_clip in clips[1:]:
        final = concatenate_videoclips(
            [final, next_clip],
            method="compose",
            padding=-CROSSFADE_DURATION,
        )

    return final


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    images = load_images()

    print("\n================================================")
    print(" CINEMATIC MOTION TEST PACK")
    print("================================================")
    print(f"Images found: {len(images)}")
    print(f"Preview length: {PREVIEW_SECONDS}s")
    print("Zoom: DISABLED")
    print("================================================")

    tests = [
        ("A_diagonal_drift", "diagonal"),
        ("B_vertical_pan", "vertical"),
        ("C_static_hold", "static"),
        ("D_subtle_parallax", "parallax"),
        ("E_crossfade", "crossfade"),
    ]

    for name, mode in tests:
        print(f"\n\n========== {name} ==========")

        if mode == "crossfade":
            clip = make_crossfade_test(images)
        else:
            clip = build_sequence(images, mode)

        clip = add_audio(clip)

        out = OUTPUT_DIR / f"{name}.mp4"
        render(clip, out)

        try:
            clip.close()
        except Exception:
            pass

        print(f"CREATED: {out}")

    # --------------------------------------------------------
    # F = mixed cinematic version
    # --------------------------------------------------------
    print("\n\n========== F_mixed_cinematic ==========")
    print("Combining diagonal drift + vertical pan + static hold +")
    print("subtle parallax-style scene + crossfades.")

    selected = images[:4]
    duration_each = PREVIEW_SECONDS / max(1, len(selected))

    clips = []

    for i, path in enumerate(selected):
        if i == 0:
            clip = make_pan_clip(
                build_scene_canvas(path, i),
                duration_each,
                i,
                "diagonal",
            )
        elif i == 1:
            clip = make_pan_clip(
                build_scene_canvas(path, i),
                duration_each,
                i,
                "vertical",
            )
        elif i == 2:
            clip = make_static_clip(
                build_scene_canvas(path, i),
                duration_each,
            )
        else:
            clip = make_parallax_style_clip(
                path,
                duration_each,
                "right",
            )

        clips.append(clip)

    final = clips[0]
    for next_clip in clips[1:]:
        final = concatenate_videoclips(
            [final, next_clip],
            method="compose",
            padding=-CROSSFADE_DURATION,
        )

    final = add_fade(final, fade_in=0.25, fade_out=0.8)
    final = add_audio(final)

    out = OUTPUT_DIR / "F_mixed_cinematic.mp4"
    render(final, out)

    try:
        final.close()
    except Exception:
        pass

    print(f"\nCREATED: {out}")

    print("\n================================================")
    print(" DONE")
    print("================================================")
    print("Watch all six files and tell me which style(s) you")
    print("want in the final YouTube generator.")
    print("")
    print("A = diagonal drift")
    print("B = slow vertical pan")
    print("C = static detailed hold")
    print("D = subtle parallax-style treatment")
    print("E = static images + crossfade emphasis")
    print("F = mixed cinematic combination")
    print("================================================")


if __name__ == "__main__":
    main()
