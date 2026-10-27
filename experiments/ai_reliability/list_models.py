"""Поиск точного имени модели на сайте (NanoGPT, OpenRouter и др.).

Пример:
    python3 list_models.py mimo            # модели NanoGPT, в имени которых есть «mimo»
    python3 list_models.py --profile A     # все модели сайта из профиля A
"""

from __future__ import annotations

import argparse
import sys

from llm import LLMError, load_env, load_profiles, make_client


def filter_ids(ids: list[str], query: str) -> list[str]:
    """Имена, в которых есть все слова запроса (без учёта регистра)."""
    words = query.lower().split()
    return [i for i in ids if all(w in i.lower() for w in words)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Список моделей на сайте")
    parser.add_argument("query", nargs="?", default="", help="часть имени модели, например mimo")
    parser.add_argument("--profile", default="mimo", help="профиль из models.toml, чей сайт и ключ взять")
    args = parser.parse_args(argv)

    load_env()
    profiles = load_profiles()
    if args.profile not in profiles:
        print(f"Нет профиля {args.profile!r} в models.toml. Есть: {', '.join(profiles)}")
        return 2
    profile = profiles[args.profile]
    try:
        # Имя модели для списка не нужно, поэтому проверку «ВПИШИТЕ» обходим.
        if "ВПИШИТЕ" in profile.model:
            profile.model = "-"
        ids = make_client(profile).list_models()
    except LLMError as exc:
        print(f"Ошибка: {exc}")
        return 1
    found = filter_ids(ids, args.query)
    print(f"Сайт {profile.url}: всего моделей {len(ids)}, подходит {len(found)}")
    for model_id in found:
        print(" ", model_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
