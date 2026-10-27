"""Общие настройки тестов."""

import sys
from pathlib import Path

# Скрипты эксперимента 0.2 лежат отдельно от пакета ядра.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "ai_reliability"))
