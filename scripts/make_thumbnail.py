"""
make_thumbnail.py
=====================================
Generates a YouTube thumbnail by overlaying bold, high-contrast text onto
one of your existing images.

HOW TO USE
------------
    python make_thumbnail.py path/to/source_image.png "YOUR THUMBNAIL TEXT" output/thumbnail.jpg

Or import and call generate_thumbnail() directly from another script (this
is what the GitHub Actions workflow will do, reading the text from your
metadata.json).

DESIGN NOTES
--------------
- Text is placed in the lower third, since that's the classic thumbnail
  layout and keeps the top of the image (usually the most interesting
  part) unobstructed.
- A semi-transparent dark gradient band sits behind the text so it stays
  readable regardless of what's in the underlying image.
- Text auto-shrinks to fit the image width instead of running off the edge.
- Bold + a black outline stroke gives the classic high-contrast thumbnail
  look that reads well even at small preview sizes.
"""

import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont

THUMBNAIL_WIDTH = 1280   # YouTube's recommended thumbnail size
THUMBNAIL_HEIGHT = 720

# A bold font is required for the classic thumbnail look. The exact file
# location differs between operating systems, so we check a list of common
# locations for Windows, macOS, and Linux (the GitHub Actions runner uses
# Linux) and use whichever one actually exists on the machine running this.
CANDIDATE_FONT_PATHS = [
    r"C:\Windows\Fonts\ariblk.ttf",                              # Windows: Arial Black
    r"C:\Windows\Fonts\arialbd.ttf",                             # Windows: Arial Bold (fallback)
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",         # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",      # Linux (GitHub Actions runner)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Linux fallback
]


def find_font_path():
    for path in CANDIDATE_FONT_PATHS:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "Could not find a bold font on this system. Checked:\n"
        + "\n".join(f"  - {p}" for p in CANDIDATE_FONT_PATHS)
        + "\n\nTo fix: find any bold .ttf font file on your computer "
        "(on Windows, look in C:\\Windows\\Fonts\\ for a file ending in "
        "'bd.ttf' or 'Bold.ttf') and add its exact path to "
        "CANDIDATE_FONT_PATHS at the top of this script."
    )


FONT_PATH = find_font_path()
MAX_FONT_SIZE = 110
MIN_FONT_SIZE = 50
TEXT_COLOR = (255, 255, 255)
OUTLINE_COLOR = (0, 0, 0)
OUTLINE_WIDTH = 6
SIDE_MARGIN = 60           # keep text this far from left/right edges
BOTTOM_MARGIN = 50         # distance from the bottom of the frame
GRADIENT_HEIGHT_FRACTION = 0.45  # how much of the bottom gets the dark gradient behind the text


def _wrap_text_to_fit(draw, text, max_width, font_path):
    """
    Finds the largest font size where the text fits on ONE line. If even the
    minimum font size doesn't fit on one line, wraps the text onto two lines
    instead of letting it run off the edges (which is what happened before
    this fix -- long titles were silently overflowing past the image edges).
    """
    size = MAX_FONT_SIZE
    while size > MIN_FONT_SIZE:
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font, [text]
        size -= 4

    # Didn't fit on one line even at the minimum size -- split into two lines
    # at the midpoint word boundary and use the minimum font size for both.
    words = text.split()
    mid = len(words) // 2
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])
    font = ImageFont.truetype(font_path, MIN_FONT_SIZE)
    return font, [line1, line2]


def _add_bottom_gradient(img):
    """Darkens the bottom portion of the image so white text stays readable."""
    w, h = img.size
    gradient_h = int(h * GRADIENT_HEIGHT_FRACTION)
    gradient = Image.new("L", (1, gradient_h), color=0)
    for y in range(gradient_h):
        # fades from transparent at the top of the band to fairly dark at the bottom
        alpha = int(180 * (y / gradient_h))
        gradient.putpixel((0, y), alpha)
    gradient = gradient.resize((w, gradient_h))

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    black_band = Image.new("RGBA", (w, gradient_h), (0, 0, 0, 255))
    black_band.putalpha(gradient)
    overlay.paste(black_band, (0, h - gradient_h), black_band)

    return Image.alpha_composite(img.convert("RGBA"), overlay)


def generate_thumbnail(source_image_path, text, output_path, font_path=FONT_PATH):
    img = Image.open(source_image_path).convert("RGB")

    # Fit/crop to the exact thumbnail aspect ratio (16:9), same center-crop
    # logic your video script already uses, so thumbnails match your footage.
    target_ratio = THUMBNAIL_WIDTH / THUMBNAIL_HEIGHT
    source_ratio = img.width / img.height
    if source_ratio > target_ratio:
        new_height = THUMBNAIL_HEIGHT
        new_width = int(img.width * new_height / img.height)
    else:
        new_width = THUMBNAIL_WIDTH
        new_height = int(img.height * new_width / img.width)
    img = img.resize((new_width, new_height), Image.LANCZOS)
    left = (new_width - THUMBNAIL_WIDTH) // 2
    top = (new_height - THUMBNAIL_HEIGHT) // 2
    img = img.crop((left, top, left + THUMBNAIL_WIDTH, top + THUMBNAIL_HEIGHT))

    img = _add_bottom_gradient(img)
    draw = ImageDraw.Draw(img)

    max_text_width = THUMBNAIL_WIDTH - (SIDE_MARGIN * 2)
    font, lines = _wrap_text_to_fit(draw, text.upper(), max_text_width, font_path)

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = 15
    total_text_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    y = THUMBNAIL_HEIGHT - BOTTOM_MARGIN - total_text_height

    for line, lw, lh in zip(lines, line_widths, line_heights):
        x = (THUMBNAIL_WIDTH - lw) / 2
        for dx in range(-OUTLINE_WIDTH, OUTLINE_WIDTH + 1, 2):
            for dy in range(-OUTLINE_WIDTH, OUTLINE_WIDTH + 1, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=OUTLINE_COLOR)
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        y += lh + line_spacing

    img.convert("RGB").save(output_path, quality=95)
    print(f"Thumbnail saved to: {output_path}")


DEFAULT_THUMBNAIL_TEXT = "WATCH NOW"  # used only if metadata.json has no thumbnail_text and no video_title either


def resolve_thumbnail_inputs(metadata_path):
    """
    Reads metadata.json and figures out which source image and text to use
    for the thumbnail, with safe fallbacks so a missing key never crashes
    the build:
      - thumbnail_source_image: uses metadata's value if present, otherwise
        just picks the first image (alphabetically) in the images/ folder
        next to metadata.json.
      - thumbnail_text: uses metadata's value if present, otherwise falls
        back to video_title, otherwise a generic default.
    """
    metadata_dir = os.path.dirname(os.path.abspath(metadata_path))
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    source_image = metadata.get("thumbnail_source_image")
    if source_image:
        source_image = os.path.join(metadata_dir, source_image)
    else:
        images_dir = os.path.join(metadata_dir, "images")
        candidates = sorted(
            f for f in os.listdir(images_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ) if os.path.isdir(images_dir) else []
        if not candidates:
            raise FileNotFoundError(
                f"No thumbnail_source_image set in metadata.json, and no images "
                f"found in {images_dir} to fall back on."
            )
        source_image = os.path.join(images_dir, candidates[0])
        print(f"No thumbnail_source_image in metadata.json -- defaulting to first image: {candidates[0]}")

    text = metadata.get("thumbnail_text") or metadata.get("video_title") or DEFAULT_THUMBNAIL_TEXT
    if "thumbnail_text" not in metadata:
        print(f"No thumbnail_text in metadata.json -- defaulting to: {text}")

    return source_image, text


if __name__ == "__main__":
    if len(sys.argv) == 3:
        # New, simpler usage: python make_thumbnail.py metadata.json output/thumbnail.jpg
        metadata_path, output_path = sys.argv[1], sys.argv[2]
        source_image, text = resolve_thumbnail_inputs(metadata_path)
        generate_thumbnail(source_image, text, output_path)
    elif len(sys.argv) == 4:
        # Old usage still works too: python make_thumbnail.py <source_image> <text> <output_path>
        generate_thumbnail(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("Usage:")
        print("  python make_thumbnail.py <metadata.json> <output_path>")
        print("  python make_thumbnail.py <source_image> <text> <output_path>")
        raise SystemExit(1)