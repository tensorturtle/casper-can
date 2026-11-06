# /// script
# requires-python = ">=3.14"
# dependencies = ["pillow"]
# ///
"""Generate the app's selectable icons through OpenRouter, from committed specs.

Every icon in the app is reproducible from a spec below, so any one can be
re-prompted without guessing what produced it.

    OPENROUTER_API_KEY=... uv run iphone-app/icons/generate_icons.py           # missing only
    OPENROUTER_API_KEY=... FORCE=1 uv run iphone-app/icons/generate_icons.py gauge

Writes the raw model output to `raw/<slug>.png`, then installs a 1024x1024
opaque RGB copy into the asset catalogue:

- `<appiconset>/icon.png` — the app icon itself (`AppIcon` is the default);
- `IconPreview-<slug>.imageset/` — a small copy the in-app picker can display,
  since iOS gives an app no way to load its own alternate icons as images.

iOS rejects icons with an alpha channel, hence the RGB conversion.
"""
import base64
import concurrent.futures
import json
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-3-pro-image")
HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "Casper CAN" / "Casper CAN" / "Assets.xcassets"

STYLE = (
    "An iOS app icon. Square, full-bleed artwork with no rounded-corner mask and "
    "no border (iOS applies its own mask). Flat modern vector style: one bold, "
    "simple shape, centred, with generous padding so it survives being masked. "
    "A solid or very gently graded background colour fills every corner. Crisp "
    "edges, at most three colours, no fine detail, no photorealism, no 3D bevel. "
    "It must read clearly at 60 pixels. Absolutely no text, letters, numerals, "
    "logos, badges or brand marks anywhere. The background colour must run "
    "right to all four edges and corners of the canvas: do not draw a rounded "
    "square, tile, card or frame around the design."
)

# slug -> (app icon set name, prompt). The first is the default icon.
SPECS = {
    "obd-plug": ("AppIcon",
        "The face of an OBD-II car diagnostic socket seen straight on: the "
        "characteristic trapezoid outline, wider at the top than the bottom, with "
        "rounded corners, and sixteen round pin holes in two rows of eight. White "
        "silhouette on a deep teal-to-navy background. Exactly two of the pin "
        "holes glow warm amber."),
    "gauge": ("AppIcon-Gauge",
        "A single thick speedometer arc spanning about 270 degrees, with a bold "
        "needle pointing up and to the right. Three small concentric radio-wave "
        "arcs radiate from the needle's pivot, suggesting a wireless signal. White "
        "arc and waves, amber needle, on a deep charcoal-blue background."),
    "waveform-road": ("AppIcon-Waveform",
        "A straight road seen from the driver's seat, receding to a vanishing "
        "point in the upper third. Its two edge lines are drawn as square waves - "
        "flat steps with right-angle corners, like a digital signal trace, "
        "shrinking with perspective - one white, one amber. Midnight-blue "
        "background that lightens slightly toward the horizon."),
    "fuel": ("AppIcon-Fuel",
        "A minimal fuel-pump nozzle silhouette, angled downward, with a single "
        "fuel drop falling from its tip. Beneath it, a short row of four blank "
        "rounded rectangles like the wheels of a mechanical odometer, with no "
        "numbers on them. White shapes on a warm orange background."),
    "grille": ("AppIcon-Grille",
        "The front view of a generic, boxy small SUV reduced to its essentials: a "
        "flat roofline, two round headlamps and a horizontal slatted grille, with "
        "no badge or emblem of any kind. White shape with amber lamps on a deep "
        "forest-green background."),
}


def generate(slug, prompt):
    key = os.environ["OPENROUTER_API_KEY"]
    body = {
        "model": MODEL,
        "modalities": ["image", "text"],
        "max_tokens": 4096,
        "messages": [{"role": "user",
                      "content": f"{prompt}\n\n{STYLE}\n\nComposition: 1:1 square."}],
        "image_config": {"aspect_ratio": "1:1"},
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.load(resp)
    images = data["choices"][0]["message"].get("images") or []
    if not images:
        raise RuntimeError(f"{slug}: no image returned: {json.dumps(data)[:300]}")
    url = images[0]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1])


def fill_light_corners(img):
    """Paint over a rounded-tile mask the model drew despite being told not to.

    The model habitually returns its own rounded square with white corners.
    iOS masks the icon again, so those corners would show as white wedges.
    Each light corner is flood-filled with the background sampled just inside it.
    """
    w, h = img.size
    inset = w // 10
    for (cx, cy), (sx, sy) in (
        ((0, 0), (inset, inset)), ((w - 1, 0), (w - 1 - inset, inset)),
        ((0, h - 1), (inset, h - 1 - inset)), ((w - 1, h - 1), (w - 1 - inset, h - 1 - inset)),
    ):
        if sum(img.getpixel((cx, cy))) > 600:
            ImageDraw.floodfill(img, (cx, cy), img.getpixel((sx, sy)), thresh=80)


def install(slug, iconset, raw_path):
    img = Image.open(raw_path).convert("RGB")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((1024, 1024), Image.LANCZOS)
    fill_light_corners(img)

    icon_dir = ASSETS / f"{iconset}.appiconset"
    icon_dir.mkdir(exist_ok=True)
    for old in icon_dir.glob("*.png"):
        old.unlink()
    img.save(icon_dir / "icon.png")
    (icon_dir / "Contents.json").write_text(json.dumps({
        "images": [{"filename": "icon.png", "idiom": "universal",
                    "platform": "ios", "size": "1024x1024"}],
        "info": {"author": "xcode", "version": 1},
    }, indent=2) + "\n")

    preview_dir = ASSETS / f"IconPreview-{slug}.imageset"
    preview_dir.mkdir(exist_ok=True)
    img.resize((180, 180), Image.LANCZOS).save(preview_dir / "preview.png")
    (preview_dir / "Contents.json").write_text(json.dumps({
        "images": [{"filename": "preview.png", "idiom": "universal"}],
        "info": {"author": "xcode", "version": 1},
    }, indent=2) + "\n")


def run(slug):
    iconset, prompt = SPECS[slug]
    raw = HERE / "raw" / f"{slug}.png"
    if raw.exists() and not os.environ.get("FORCE"):
        print(f"{slug}: exists, installing (FORCE=1 to regenerate)")
    else:
        raw.parent.mkdir(exist_ok=True)
        raw.write_bytes(generate(slug, prompt))
        print(f"{slug}: generated")
    install(slug, iconset, raw)
    return slug


if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SPECS)
    unknown = [s for s in wanted if s not in SPECS]
    if unknown:
        raise SystemExit(f"unknown slug(s): {unknown}; known: {list(SPECS)}")
    with concurrent.futures.ThreadPoolExecutor(len(wanted)) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(run, s) for s in wanted]):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED: {exc}")
