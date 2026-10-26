"""Пиксельная обработка картинки из консоли.

    python tools/pixelize.py вход.png выход.png --style hibit
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from PIL import Image  # noqa: E402

from matricaria.art.pixelize import pixelize  # noqa: E402
from matricaria.art.style import STYLES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Сделать из картинки пиксельный портрет")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--style", choices=sorted(STYLES), default="hibit")
    parser.add_argument("--no-upscale", action="store_true", help="сохранить в исходном размере сетки")
    args = parser.parse_args()

    with Image.open(args.source) as image:
        result = pixelize(image, STYLES[args.style], upscale=not args.no_upscale)
    result.save(args.target)
    print(f"{args.target}: {result.width}×{result.height}")


if __name__ == "__main__":
    main()
