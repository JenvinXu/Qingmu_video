"""Create the product's own simple leaf icon; no external image assets."""

from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "apps/desktop/assets"
root.mkdir(parents=True, exist_ok=True)
image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((12, 12, 500, 500), radius=116, fill="#25543c")
draw.ellipse((140, 103, 374, 394), fill="#d1edca")
draw.polygon([(135, 300), (156, 396), (215, 362)], fill="#25543c")
draw.line([(163, 360), (215, 281), (280, 212), (337, 159)], fill="#4d8460", width=13)
image.save(root / "icon.png")
image.save(
    root / "icon.ico",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
