"""Случайность мира по seed (D51).

Каждое случайное решение получает свой генератор из seed мира и «ключа»:
кто решает, что и в какую минуту. Состояние генератора нигде не хранится,
поэтому тот же seed и те же действия всегда дают тот же результат,
а откат к снимку ничего не сбивает.
"""

import hashlib
import random


def rng(seed: int, *keys) -> random.Random:
    """Генератор для одного решения: `rng(seed, "decide", "boris", 1440)`."""
    text = ":".join(str(key) for key in (seed, *keys))
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
