#!/usr/bin/env python3
"""
make_video.py
============

YouTube cinematic video generator.

IMPORTANT DESIGN CHANGE
-----------------------
Animated ZOOM has been intentionally removed because it caused visible
shivering/flickering in the source images.

Instead, the video uses cinematic effects based on CROPPING / STATIC
IMAGES / TRANSITIONS.

The main control is:

    EFFECTS_NEEDED = [
        "horizontal_pan",
        "vertical_pan",
        "diagonal_drift",
        "static_hold",
        "subtle_parallax",
        "crossfade",
    ]

You can add/remove effects from that list.

The same EFFECTS_NEEDED setting is used by:
    1. the 10-second preview
    2. the full video

So the preview is a real test of the motion system used by the final video.

AVAILABLE EFFECTS
-----------------
"horizontal_pan"
    Slow left <-> right camera movement.

"vertical_pan"
    Slow up/down camera movement.

"diagonal_drift"
    Slow diagonal camera movement.

"static_hold"
    Completely static image.
    Recommended for images containing lots of small details or text.

"subtle_parallax"
    Very subtle layered-depth treatment.
    This is deliberately conservative and does NOT use animated zoom.

"crossfade"
    Smooth transition between scenes.

Example:

    EFFECTS_NEEDED = [
        "horizontal_pan",
        "vertical_pan",
        "diagonal_drift",
        "static_hold",
        "subtle_parallax",
        "crossfade",
    ]

The script automatically cycles through the selected effects.

PREVIEW
-------
Set:

    PREVIEW_MODE = True

to create only a 10-second test:

    output/preview_TEST.mp4

When ready for the full video:

    PREVIEW_MODE = False

The full output is:

    output/final_video.mp4

CAPTIONS
--------
After the base video is rendered, narration.mp3 is transcribed with
Whisper (word-level timestamps), a styled .ass karaoke-highlight
subtitle file is generated, and it's burned into the video with ffmpeg
as a final pass. If narration.mp3 is missing, captions are skipped and
the uncaptioned render is used as the final output.

REQUIREMENTS
------------
pip install moviepy pillow elevenlabs openai-whisper

FFmpeg must also be installed and available on PATH.
"""

import os
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance

import whisper

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
)

# ============================================================
# USER SETTINGS
# ============================================================

# ------------------------------------------------------------
# PREVIEW
# ------------------------------------------------------------

# True  = render only a 10-second test
# False = render the complete video
PREVIEW_MODE = False

PREVIEW_SECONDS = 10

# ------------------------------------------------------------
# CINEMATIC EFFECTS
# ------------------------------------------------------------

# Choose the effects you want available to the video.
#
# The video will cycle through these effects as it moves from
# image to image.
#
# You can use one effect:
#
# EFFECTS_NEEDED = ["horizontal_pan"]
#
# Or several:
#
# EFFECTS_NEEDED = [
#     "horizontal_pan",
#     "vertical_pan",
#     "diagonal_drift",
#     "static_hold",
#     "subtle_parallax",
#     "crossfade",
# ]
#
# Recommended starting setup:
# EFFECTS_NEEDED = ["static_hold", "static_hold", "horizontal_pan", "static_hold", "crossfade"]
EFFECTS_NEEDED = ["static_hold", "static_hold", "static_hold", "horizontal_pan", "static_hold", "crossfade"]

# ------------------------------------------------------------
# VIDEO
# ------------------------------------------------------------

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

FPS = 60
BITRATE = "18M"

# Extra image area used for camera movement.
#
# IMPORTANT:
# This is NOT an animated zoom.
#
# Each source image is resized ONCE before playback and then
# the video simply moves a 1920x1080 crop window over that
# oversized static image.
OVERSIZE_FACTOR = 1.20
PAN_RANGE_FRACTION = 0.4   # lower = slower pan (e.g. 0.2 for very slow, 1.0 for original full-range speed)

# Length of the transition between images.
CROSSFADE_DURATION = 0.6

# Fade at the very beginning/end of the complete video.
START_FADE = 0.25
END_FADE = 1.0

# ------------------------------------------------------------
# CAPTIONS
# ------------------------------------------------------------

WHISPER_MODEL_SIZE = "small"   # tiny / base / small / medium / large -- bigger = more accurate but slower

CAPTION_FONT_NAME = "DejaVu Sans Bold"   # available by default on the Linux GitHub runner
CAPTION_FONT_SIZE = 56
CAPTION_HIGHLIGHT_COLOR = "&H0000D7FF"   # gold -- shown on a word once it's been spoken
CAPTION_DEFAULT_COLOR = "&H00FFFFFF"     # white -- default/unspoken text color
CAPTION_OUTLINE_COLOR = "&H00000000"     # black outline
CAPTION_MARGIN_V = 80
WORDS_PER_CAPTION_LINE = 6

# ------------------------------------------------------------
# INPUT / OUTPUT
# ------------------------------------------------------------

# IMAGE_DIR = Path("images")
# OUTPUT_DIR = Path("output")

# # Audio files live in the current week folder.
# # The GitHub workflow runs this script from weeks/<week-date>, so these
# # resolve to weeks/<week-date>/narration.mp3 and music.mp3.
# NARRATION_PATH = Path("narration.mp3")
# MUSIC_PATH = Path("music.mp3")

# # Background music volume relative to the original music file.
# MUSIC_VOLUME = 0.15

# PREVIEW_OUTPUT = OUTPUT_DIR / "preview_TEST.mp4"
# FINAL_OUTPUT = OUTPUT_DIR / "final_video.mp4"


# ------------------------------------------------------------
# INPUT / OUTPUT for testing
# ------------------------------------------------------------
#
# WEEK_DIR lets you point this script at a specific week folder
# without needing to `cd` into it first (useful when testing locally
# in VS Code). GitHub Actions already `cd`s into the right week
# folder before running this script via `working-directory`, so if
# you commit this file, switch WEEK_DIR back to the env-var version
# below -- otherwise build-video.yml will break looking for this
# Windows path on the Linux runner.
#
# Local-only hardcoded path (DO NOT COMMIT AS-IS):
# WEEK_DIR = Path(r"D:\Coding\video-factory\weeks\03-10-2026")
WEEK_DIR = Path(os.environ.get("WEEK_DIR", "."))
#
# Safe-to-commit alternative (defaults to "." so GitHub Actions is
# unaffected, override locally with an env var instead):
#   WEEK_DIR = Path(os.environ.get("WEEK_DIR", "."))

IMAGE_DIR = WEEK_DIR / "images"
OUTPUT_DIR = WEEK_DIR / "output"

NARRATION_PATH = WEEK_DIR / "narration.mp3"
MUSIC_PATH = WEEK_DIR / "music.mp3"

# Background music volume relative to the original music file.
MUSIC_VOLUME = 0.15

PREVIEW_OUTPUT = OUTPUT_DIR / "preview_TEST.mp4"
FINAL_OUTPUT = OUTPUT_DIR / "final_video.mp4"

# ============================================================
# OPTIONAL AUDIO / CAPTION SETTINGS
# ============================================================

# Audio files expected in the current week folder:
#     narration.mp3
#     music.mp3

# ============================================================
# EFFECT VALIDATION
# ============================================================

VALID_EFFECTS = {
    "horizontal_pan",
    "diagonal_drift",
    "static_hold",
    "subtle_parallax",
    "crossfade",
    "vertical_pan"
}

if not EFFECTS_NEEDED:
    raise ValueError(
        "EFFECTS_NEEDED cannot be empty. "
        "Choose at least one cinematic effect."
    )

unknown_effects = set(EFFECTS_NEEDED) - VALID_EFFECTS

if unknown_effects:
    raise ValueError(
        f"Unknown effect(s): {sorted(unknown_effects)}\n"
        f"Valid effects: {sorted(VALID_EFFECTS)}"
    )

# ============================================================
# GENERAL HELPERS
# ============================================================


def run_command(command):
    print("\n>", " ".join(str(x) for x in command))
    subprocess.run(command, check=True)


def ease_in_out(t):
    """Smooth camera movement instead of constant linear movement."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def get_images():
    """Return supported images in deterministic order."""
    if not IMAGE_DIR.exists():
        raise RuntimeError(
            f"Image directory does not exist: {IMAGE_DIR.resolve()}"
        )

    images = [
        p
        for p in sorted(IMAGE_DIR.iterdir())
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]

    if not images:
        raise RuntimeError(
            f"No images found in {IMAGE_DIR.resolve()}"
        )

    return images


def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# IMAGE PREPARATION
# ============================================================


def prepare_oversized_image(image_path):
    """
    Prepare the source image ONCE.

    The resulting image is larger than 1920x1080.

    During video playback we crop from this static image.

    This is intentionally different from:
        clip.resized(lambda t: ...)

    because continuous raster resizing was the source of the
    shivering seen in the earlier versions.
    """

    image = Image.open(image_path).convert("RGB")

    canvas_width = int(VIDEO_WIDTH * OVERSIZE_FACTOR)
    canvas_height = int(VIDEO_HEIGHT * OVERSIZE_FACTOR)

    target_ratio = canvas_width / canvas_height
    source_ratio = image.width / image.height

    # Fit image inside the oversized 16:9 canvas.
    if source_ratio > target_ratio:
        new_height = canvas_height
        new_width = int(
            image.width * new_height / image.height
        )
    else:
        new_width = canvas_width
        new_height = int(
            image.height * new_width / image.width
        )

    image = image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    # Center crop to exact oversized canvas size.
    left = max(0, (new_width - canvas_width) // 2)
    top = max(0, (new_height - canvas_height) // 2)

    image = image.crop(
        (
            left,
            top,
            left + canvas_width,
            top + canvas_height,
        )
    )

    return image


def prepare_exact_frame(image_path):
    """
    Prepare a 1920x1080 static frame.

    Used for STATIC_HOLD and CROSSFADE.
    """

    image = Image.open(image_path).convert("RGB")

    source_ratio = image.width / image.height
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT

    if source_ratio > target_ratio:
        new_height = VIDEO_HEIGHT
        new_width = int(
            image.width * new_height / image.height
        )
    else:
        new_width = VIDEO_WIDTH
        new_height = int(
            image.height * new_width / image.width
        )

    image = image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    left = max(0, (new_width - VIDEO_WIDTH) // 2)
    top = max(0, (new_height - VIDEO_HEIGHT) // 2)

    image = image.crop(
        (
            left,
            top,
            left + VIDEO_WIDTH,
            top + VIDEO_HEIGHT,
        )
    )

    return image


def save_temp_image(image, name):
    temp_dir = OUTPUT_DIR / "_cinematic_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    path = temp_dir / name
    image.save(path, quality=96)

    return path


# ============================================================
# CAMERA POSITIONS
# ============================================================


def get_motion_positions(effect, index, max_x, max_y):
    range_x = max_x * PAN_RANGE_FRACTION
    range_y = max_y * PAN_RANGE_FRACTION
    start_offset_x = (max_x - range_x) / 2
    start_offset_y = (max_y - range_y) / 2

    center_x = max_x // 2
    center_y = max_y // 2

    if effect == "horizontal_pan":
        if index % 2 == 0:
            return (start_offset_x, center_y, start_offset_x + range_x, center_y)
        return (start_offset_x + range_x, center_y, start_offset_x, center_y)

    if effect == "vertical_pan":
        if index % 2 == 0:
            return (center_x, start_offset_y, center_x, start_offset_y + range_y)
        return (center_x, start_offset_y + range_y, center_x, start_offset_y)

    if effect == "diagonal_drift":
        patterns = [
            (start_offset_x, start_offset_y, start_offset_x + range_x, start_offset_y + range_y),
            (start_offset_x + range_x, start_offset_y, start_offset_x, start_offset_y + range_y),
            (start_offset_x, start_offset_y + range_y, start_offset_x + range_x, start_offset_y),
            (start_offset_x + range_x, start_offset_y + range_y, start_offset_x, start_offset_y),
        ]
        return patterns[index % len(patterns)]

    return (center_x, center_y, center_x, center_y)

# ============================================================
# PAN / DRIFT CLIPS
# ============================================================


def make_pan_clip(image_path, duration, effect, index):
    """
    Creates horizontal pan, vertical pan, or diagonal drift.

    The image is resized ONCE.

    During playback only the crop window moves.
    """

    oversized = prepare_oversized_image(image_path)

    temp_path = save_temp_image(
        oversized,
        f"oversized_{index:05d}.jpg",
    )

    canvas_width, canvas_height = oversized.size

    max_x = max(
        0,
        canvas_width - VIDEO_WIDTH,
    )

    max_y = max(
        0,
        canvas_height - VIDEO_HEIGHT,
    )

    start_x, start_y, end_x, end_y = (
        get_motion_positions(
            effect,
            index,
            max_x,
            max_y,
        )
    )

    base = ImageClip(str(temp_path)).with_duration(duration)

    def crop_frame(get_frame, t):
        frame = get_frame(t)

        progress = ease_in_out(t / duration)

        x = int(
            round(
                start_x
                + (end_x - start_x) * progress
            )
        )

        y = int(
            round(
                start_y
                + (end_y - start_y) * progress
            )
        )

        x = max(0, min(max_x, x))
        y = max(0, min(max_y, y))

        return frame[
            y : y + VIDEO_HEIGHT,
            x : x + VIDEO_WIDTH,
        ]

    return base.transform(crop_frame)


# ============================================================
# STATIC HOLD
# ============================================================


def make_static_hold(image_path, duration, index):
    """
    Completely static scene.

    This is useful when the image contains:
    - lots of small details
    - text
    - diagrams
    - faces
    - screenshots
    - architecture drawings
    - maps

    No camera movement happens.
    """

    image = prepare_exact_frame(image_path)

    temp_path = save_temp_image(
        image,
        f"static_{index:05d}.jpg",
    )

    return ImageClip(
        str(temp_path)
    ).with_duration(duration)


# ============================================================
# SUBTLE PARALLAX
# ============================================================


def make_subtle_parallax(image_path, duration, index):
    """
    Very conservative parallax-style treatment.

    This is NOT AI depth estimation.

    It uses:
      - one sharp foreground frame
      - one slightly oversized soft background
      - tiny background movement

    The foreground itself remains completely stable.

    This gives a subtle sense of depth without animated zoom.
    """

    # --------------------------------------------------------
    # Sharp foreground
    # --------------------------------------------------------

    foreground = prepare_exact_frame(image_path)

    foreground_path = save_temp_image(
        foreground,
        f"parallax_foreground_{index:05d}.jpg",
    )

    foreground_clip = ImageClip(
        str(foreground_path)
    ).with_duration(duration)

    # --------------------------------------------------------
    # Soft background
    # --------------------------------------------------------

    background = Image.open(image_path).convert("RGB")

    background_width = VIDEO_WIDTH + 40
    background_height = VIDEO_HEIGHT + 40

    source_ratio = background.width / background.height
    target_ratio = (
        background_width / background_height
    )

    if source_ratio > target_ratio:
        new_height = background_height
        new_width = int(
            background.width
            * new_height
            / background.height
        )
    else:
        new_width = background_width
        new_height = int(
            background.height
            * new_width
            / background.width
        )

    background = background.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    left = max(
        0,
        (new_width - background_width) // 2,
    )

    top = max(
        0,
        (new_height - background_height) // 2,
    )

    background = background.crop(
        (
            left,
            top,
            left + background_width,
            top + background_height,
        )
    )

    # Soft background only.
    background = background.filter(
        ImageFilter.GaussianBlur(10)
    )

    background = ImageEnhance.Brightness(
        background
    ).enhance(0.96)

    background_path = save_temp_image(
        background,
        f"parallax_background_{index:05d}.jpg",
    )

    background_clip = ImageClip(
        str(background_path)
    ).with_duration(duration)

    # Tiny movement only: 4 pixels.
    directions = [
        (4, 4, 0, 0),
        (0, 4, 4, 0),
        (4, 0, 0, 4),
        (0, 0, 4, 4),
    ]

    sx, sy, ex, ey = directions[
        index % len(directions)
    ]

    def move_background(get_frame, t):
        frame = get_frame(t)

        progress = ease_in_out(t / duration)

        x = int(
            round(
                sx
                + (ex - sx) * progress
            )
        )

        y = int(
            round(
                sy
                + (ey - sy) * progress
            )
        )

        return frame[
            y : y + VIDEO_HEIGHT,
            x : x + VIDEO_WIDTH,
        ]

    background_clip = background_clip.transform(
        move_background
    )

    return CompositeVideoClip(
        [
            background_clip,
            foreground_clip,
        ],
        size=(VIDEO_WIDTH, VIDEO_HEIGHT),
    )


# ============================================================
# CROSSFADE
# ============================================================


def make_crossfade_scene(
    image_path,
    duration,
    index,
):
    """
    Static image intended to be combined with crossfade
    transitions.

    Crossfade is handled when scenes are joined.
    """

    return make_static_hold(
        image_path,
        duration,
        index,
    )


# ============================================================
# EFFECT SELECTION
# ============================================================


def choose_effect_for_scene(index):
    """
    Select an effect from EFFECTS_NEEDED.

    CROSSFADE is a TRANSITION rather than a camera movement,
    so when it appears in EFFECTS_NEEDED it is applied between
    scenes rather than becoming the scene's camera effect.

    Therefore the actual scene effects are selected from:

        horizontal_pan
        vertical_pan
        diagonal_drift
        static_hold
        subtle_parallax

    If the user chooses only ["crossfade"], every image is
    displayed as a static hold with crossfade transitions.
    """

    scene_effects = [
        effect
        for effect in EFFECTS_NEEDED
        if effect != "crossfade"
    ]

    if not scene_effects:
        return "static_hold"

    return scene_effects[
        index % len(scene_effects)
    ]


# ============================================================
# BUILD VIDEO
# ============================================================


def build_video(
    images,
    target_duration,
):
    """
    Build enough scenes to cover target_duration.

    Scene durations are distributed evenly.

    The selected EFFECTS_NEEDED list is used repeatedly across
    the available images.
    """

    if not images:
        raise RuntimeError("No images available.")

    # We use a practical number of scenes for the preview.
    # For the full video, this uses all available images.
    if PREVIEW_MODE:
        # Select enough images to cover the preview.
        # At least 1 and at most 4 scenes for a 10-second test.
        scene_count = min(
            len(images),
            max(
                1,
                math.ceil(target_duration / 3.0),
            ),
        )
        selected_images = images[:scene_count]
    else:
        selected_images = images

    scene_duration = (
        target_duration / len(selected_images)
    )

    clips = []

    print("\n==============================")
    print("CINEMATIC EFFECT ASSIGNMENT")
    print("==============================")

    for index, image_path in enumerate(
        selected_images
    ):
        effect = choose_effect_for_scene(index)

        print(
            f"Scene {index + 1:03d}: "
            f"{image_path.name} -> {effect}"
        )

        if effect == "horizontal_pan":
            clip = make_pan_clip(
                image_path,
                scene_duration,
                "horizontal_pan",
                index,
            )

        elif effect == "vertical_pan":
            clip = make_pan_clip(
                image_path,
                scene_duration,
                "vertical_pan",
                index,
            )

        elif effect == "diagonal_drift":
            clip = make_pan_clip(
                image_path,
                scene_duration,
                "diagonal_drift",
                index,
            )

        elif effect == "static_hold":
            clip = make_static_hold(
                image_path,
                scene_duration,
                index,
            )

        elif effect == "subtle_parallax":
            clip = make_subtle_parallax(
                image_path,
                scene_duration,
                index,
            )

        else:
            clip = make_static_hold(
                image_path,
                scene_duration,
                index,
            )

        # Fade the first scene in.
        if index == 0:
            from moviepy.video.fx import FadeIn

            clip = clip.with_effects(
                [FadeIn(START_FADE)]
            )

        # Fade final scene out.
        if index == len(selected_images) - 1:
            from moviepy.video.fx import FadeOut

            clip = clip.with_effects(
                [FadeOut(END_FADE)]
            )

        clips.append(clip)

    # --------------------------------------------------------
    # Crossfade transitions
    # --------------------------------------------------------

    use_crossfade = (
        "crossfade" in EFFECTS_NEEDED
    )

    if use_crossfade and len(clips) > 1:
        print(f"\nCrossfades: ENABLED ({CROSSFADE_DURATION}s)")
        final = concatenate_videoclips(
            clips,
            method="compose",
            padding=-CROSSFADE_DURATION,
        )
    else:
        print("\nCrossfades: DISABLED")
        final = concatenate_videoclips(clips, method="compose")

    # Force exact requested duration.
    final = final.subclipped(
        0,
        min(target_duration, final.duration),
    )

    return final


# ============================================================
# AUDIO
# ============================================================


def attach_audio(video, narration_path, music_path):
    """Attach narration and looping background music."""
    audio_tracks = []

    # Narration is the primary track.
    if narration_path.exists():
        narration = AudioFileClip(str(narration_path))
        narration = narration.subclipped(0, min(narration.duration, video.duration))
        if PREVIEW_MODE:
            narration = narration.subclipped(0, min(PREVIEW_SECONDS, narration.duration))
        audio_tracks.append(narration)
    else:
        print(f"\nWARNING: narration file not found: {narration_path}")

    # Music plays underneath narration for the whole video.
    if music_path.exists():
        music_source = AudioFileClip(str(music_path))
        target_duration = min(PREVIEW_SECONDS, video.duration) if PREVIEW_MODE else video.duration

        if music_source.duration < target_duration:
            loops_needed = math.ceil(target_duration / music_source.duration)
            music = concatenate_audioclips([music_source] * loops_needed)
        else:
            music = music_source

        music = music.subclipped(0, min(target_duration, music.duration))
        music = music.with_volume_scaled(MUSIC_VOLUME)
        audio_tracks.append(music)
        print(f"Background music: {music_path} (volume={MUSIC_VOLUME})")
    else:
        print(f"\nWARNING: music file not found: {music_path}")

    if not audio_tracks:
        print("\nWARNING: No audio files found.")
        return video

    combined_audio = CompositeAudioClip(audio_tracks)
    combined_audio = combined_audio.subclipped(0, min(combined_audio.duration, video.duration))
    return video.with_audio(combined_audio)


# ============================================================
# RENDER
# ============================================================


def render_video(
    video,
    output_path,
):
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("\n==============================")
    print("RENDERING")
    print("==============================")
    print(f"Output: {output_path}")
    print(f"FPS: {FPS}")
    print(f"Bitrate: {BITRATE}")

    video.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate=BITRATE,
        preset="medium",
        threads=os.cpu_count() or 4,
        logger="bar",
    )


# ============================================================
# CAPTIONS
# ============================================================


def transcribe_narration(narration_path):
    print("\n==============================")
    print("TRANSCRIBING NARRATION (Whisper)")
    print("==============================")
    print(f"Model: {WHISPER_MODEL_SIZE}")

    model = whisper.load_model(WHISPER_MODEL_SIZE)
    result = model.transcribe(str(narration_path), word_timestamps=True)

    words = []
    for segment in result["segments"]:
        for word_info in segment.get("words", []):
            text = word_info["word"].strip()
            if not text:
                continue
            words.append({
                "text": text,
                "start": word_info["start"],
                "end": word_info["end"],
            })

    print(f"Transcribed {len(words)} words.")
    return words


def _format_ass_time(seconds):
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centisecs = int(round((secs - int(secs)) * 100))
    return f"{hours:01d}:{minutes:02d}:{int(secs):02d}.{centisecs:02d}"


def generate_ass_captions(words, ass_path):
    print("\n==============================")
    print("GENERATING CAPTIONS (.ass)")
    print("==============================")

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {VIDEO_WIDTH}\n"
        f"PlayResY: {VIDEO_HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Captions,{CAPTION_FONT_NAME},{CAPTION_FONT_SIZE},{CAPTION_HIGHLIGHT_COLOR},"
        f"{CAPTION_DEFAULT_COLOR},{CAPTION_OUTLINE_COLOR},&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,"
        f"40,40,{CAPTION_MARGIN_V},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [
        words[i:i + WORDS_PER_CAPTION_LINE]
        for i in range(0, len(words), WORDS_PER_CAPTION_LINE)
    ]

    events = []
    for line_words in lines:
        if not line_words:
            continue

        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]

        karaoke_text = ""
        for word in line_words:
            duration_cs = max(1, int(round((word["end"] - word["start"]) * 100)))
            karaoke_text += f"{{\\k{duration_cs}}}{word['text']} "

        events.append(
            f"Dialogue: 0,{_format_ass_time(line_start)},{_format_ass_time(line_end)},"
            f"Captions,,0,0,0,,{karaoke_text.strip()}"
        )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")

    print(f"Captions written: {ass_path} ({len(events)} lines)")


def burn_captions(video_path, ass_path, output_path):
    print("\n==============================")
    print("BURNING CAPTIONS")
    print("==============================")

    render_dir = video_path.parent

    # Run from inside the output folder and use bare relative filenames --
    # this avoids the Windows drive-letter colon-escaping problem in
    # ffmpeg's filter-graph string entirely.
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.name,
        "-vf", f"ass={ass_path.name}",
        "-c:v", "libx264",
        "-c:a", "copy",
        output_path.name,
    ]

    print(f"Running (from {render_dir}):")
    print("  " + " ".join(cmd))

    subprocess.run(cmd, check=True, cwd=render_dir)
    print(f"Captioned video saved: {output_path}")


# ============================================================
# CLEANUP
# ============================================================


def cleanup_temp_files():
    """
    Remove temporary cinematic image files.

    Comment this out if you want to inspect the generated
    intermediate images.
    """

    temp_dir = OUTPUT_DIR / "_cinematic_temp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)


# ============================================================
# MAIN
# ============================================================


def main():

    ensure_output_dir()

    images = get_images()

    print("\n")
    print("==============================================")
    print(" MAKE_VIDEO.PY")
    print(" CINEMATIC NO-ZOOM VIDEO GENERATOR")
    print("==============================================")

    print(
        f"\nImages found: {len(images)}"
    )

    print(f"\nNarration: {NARRATION_PATH}")
    print(f"Music:     {MUSIC_PATH}")
    print(f"Music volume: {MUSIC_VOLUME}")

    print(
        "\nEffects requested:"
    )

    for effect in EFFECTS_NEEDED:
        print(f"  - {effect}")

    if PREVIEW_MODE:
        print(
            f"\nPREVIEW MODE: ON "
            f"({PREVIEW_SECONDS} seconds)"
        )

        target_duration = PREVIEW_SECONDS
        output_path = PREVIEW_OUTPUT

    else:
        print("\nFULL VIDEO MODE: ON")

        # Full video duration comes from narration.
        if not NARRATION_PATH.exists():
            raise RuntimeError(
                "Full video mode requires "
                f"{NARRATION_PATH}"
            )

        narration = AudioFileClip(
            str(NARRATION_PATH)
        )

        target_duration = narration.duration

        narration.close()

        output_path = FINAL_OUTPUT

    # --------------------------------------------------------
    # Build cinematic video
    # --------------------------------------------------------

    video = build_video(
        images,
        target_duration,
    )

    # --------------------------------------------------------
    # Attach narration
    # --------------------------------------------------------

    video = attach_audio(
        video,
        NARRATION_PATH,
        MUSIC_PATH,
    )

    # --------------------------------------------------------
    # Render the base video (no captions yet)
    # --------------------------------------------------------

    no_captions_path = output_path.with_name(
        output_path.stem + "_nocaptions" + output_path.suffix
    )

    render_video(video, no_captions_path)

    try:
        video.close()
    except Exception:
        pass

    # --------------------------------------------------------
    # Captions
    # --------------------------------------------------------

    if NARRATION_PATH.exists():
        if PREVIEW_MODE:
            # Don't transcribe the whole narration just to use the first
            # few seconds of it -- cut a short clip first.
            preview_narration_path = OUTPUT_DIR / "_preview_narration.mp3"
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(NARRATION_PATH),
                    "-t", str(PREVIEW_SECONDS),
                    str(preview_narration_path),
                ],
                check=True,
            )
            words = transcribe_narration(preview_narration_path)
        else:
            words = transcribe_narration(NARRATION_PATH)

        words = [w for w in words if w["start"] < target_duration]

        if words:
            # Save the captions file next to the video itself, not a fixed
            # OUTPUT_DIR -- PREVIEW_OUTPUT/FINAL_OUTPUT may live in a
            # different folder than OUTPUT_DIR, and burn_captions() runs
            # ffmpeg from wherever the video actually is.
            ass_path = output_path.parent / "captions.ass"
            generate_ass_captions(words, ass_path)
            burn_captions(no_captions_path, ass_path, output_path)
        else:
            print("\nWARNING: No words transcribed -- skipping captions.")
            shutil.copy(no_captions_path, output_path)
    else:
        print(f"\nWARNING: narration not found -- skipping captions: {NARRATION_PATH}")
        shutil.copy(no_captions_path, output_path)

    cleanup_temp_files()

    print("\n==============================================")
    print("DONE")
    print("==============================================")
    print(f"Created: {output_path}")

    if PREVIEW_MODE:
        print(
            "\nThis was the 10-second preview."
        )
        print(
            "If it looks good, change:"
        )
        print(
            "    PREVIEW_MODE = False"
        )
        print(
            "and run the script again for the full video."
        )


if __name__ == "__main__":
    main()