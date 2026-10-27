"""Клиент для OpenAI-совместимых сайтов (NanoGPT, OpenRouter, llama-server и др.).

Только стандартная библиотека Python: ничего ставить не нужно.
Настройки моделей — в models.toml, ключи — в .env (файл не попадает в git).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS = HERE / "models.toml"
DEFAULT_ENV = HERE / ".env"

# Порядок упрощения формата ответа, если сайт не понимает строгую схему.
FORMAT_FALLBACK = {"json_schema": "json_object", "json_object": "none"}


class LLMError(Exception):
    """Запрос к модели не удался даже после повторов."""


@dataclass
class Profile:
    id: str
    name: str
    url: str
    model: str
    key_env: str = ""
    price_in: float = 0.0  # долларов за 1 млн входных токенов
    price_out: float = 0.0  # долларов за 1 млн выходных токенов
    response_format: str = "json_schema"  # json_schema | json_object | none
    temperature: float = 0.7
    max_tokens: int = 600
    timeout: float = 180.0
    # Дополнительные поля запроса, например reasoning_effort = "none".
    extra: dict = field(default_factory=dict)

    @property
    def is_fake(self) -> bool:
        return self.url.startswith("fake://")

    @property
    def has_prices(self) -> bool:
        return self.price_in > 0 or self.price_out > 0


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency: float
    cost: float
    reasoning_tokens: int = 0  # сколько токенов модель потратила на размышления

    def stats(self, role: str) -> dict:
        return {
            "role": role,
            "latency": round(self.latency, 3),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost": self.cost,
            "reasoning_tokens": self.reasoning_tokens,
        }


def load_env(path: Path | str = DEFAULT_ENV) -> None:
    """Читает файл .env (строки КЛЮЧ=значение). Уже заданные переменные не трогает."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_profiles(path: Path | str = DEFAULT_MODELS) -> dict[str, Profile]:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    profiles = {}
    for pid, raw in data["profiles"].items():
        profiles[pid] = Profile(id=pid, **raw)
    return profiles


def make_client(profile: Profile) -> "ChatClient":
    if profile.is_fake:
        return FakeClient(profile)
    if "ВПИШИТЕ" in profile.model:
        raise LLMError(
            f"В models.toml у профиля {profile.id} не вписано имя модели (поле model)."
        )
    key = os.environ.get(profile.key_env, "") if profile.key_env else ""
    if profile.key_env and not key:
        raise LLMError(
            f"Нет ключа: добавьте строку {profile.key_env}=... в файл "
            f"experiments/ai_reliability/.env"
        )
    return ChatClient(profile, key)


class ChatClient:
    def __init__(self, profile: Profile, api_key: str = ""):
        self.profile = profile
        self.api_key = api_key
        self.response_format = profile.response_format

    def _format_field(self, schema: dict | None) -> dict | None:
        if schema is None or self.response_format == "none":
            return None
        if self.response_format == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {"name": "reply", "schema": schema, "strict": False},
        }

    def complete(
        self,
        messages: list[dict],
        schema: dict | None = None,
        temperature: float | None = None,
    ) -> Completion:
        body = {
            "model": self.profile.model,
            "messages": messages,
            "temperature": self.profile.temperature if temperature is None else temperature,
            "max_tokens": self.profile.max_tokens,
            "stream": False,
            **self.profile.extra,
        }
        delays = [2, 4, 8]
        attempt = 0
        while True:
            fmt = self._format_field(schema)
            if fmt is None:
                body.pop("response_format", None)
            else:
                body["response_format"] = fmt
            started = time.monotonic()
            try:
                data = self._post(body)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                # Сайт не понял формат ответа — пробуем формат попроще.
                if exc.code in (400, 422) and fmt is not None:
                    self.response_format = FORMAT_FALLBACK[self.response_format]
                    print(
                        f"  [{self.profile.id}] сайт отклонил формат ответа, "
                        f"перехожу на '{self.response_format}': {detail[:120]}"
                    )
                    continue
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < len(delays):
                    time.sleep(delays[attempt])
                    attempt += 1
                    continue
                raise LLMError(f"HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    attempt += 1
                    continue
                raise LLMError(f"нет связи с {self.profile.url}: {exc}") from exc
            latency = time.monotonic() - started
            return self._parse(data, latency)

    def list_models(self) -> list[str]:
        """Имена всех моделей, которые отдаёт сайт (GET /models)."""
        url = self.profile.url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.profile.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise LLMError(f"не удалось получить список моделей: {exc}") from exc
        return sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m)

    def _post(self, body: dict) -> dict:
        url = self.profile.url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.profile.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _parse(self, data: dict, latency: float) -> Completion:
        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"непонятный ответ сайта: {str(data)[:300]}") from exc
        if not text.strip() and data["choices"][0].get("finish_reason") == "length":
            print(
                f"  [{self.profile.id}] ответ пустой: модель потратила все токены "
                f"(вероятно, на размышления). Увеличьте max_tokens в models.toml."
            )
        usage = data.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        cost = (pt * self.profile.price_in + ct * self.profile.price_out) / 1_000_000
        details = usage.get("completion_tokens_details") or {}
        rt = int(details.get("reasoning_tokens") or 0)
        return Completion(text, pt, ct, latency, round(cost, 6), rt)


class FakeClient(ChatClient):
    """Поддельная модель: отвечает без сети, чтобы проверить сам скрипт.

    Иногда нарочно ошибается (ломает JSON, предлагает невозможное действие),
    чтобы было что ловить валидатору. Результат детерминирован.
    """

    def __init__(self, profile: Profile):
        super().__init__(profile, "")

    def complete(self, messages, schema=None, temperature=None) -> Completion:
        last = messages[-1]["content"]
        system = messages[0]["content"]
        seed = int(hashlib.sha256(last.encode("utf-8")).hexdigest(), 16)
        retry = any("Ответ отклонён" in m["content"] for m in messages if m["role"] == "user")
        if '"contradiction"' in system:
            text = json.dumps({"contradiction": False, "reason": "поддельная проверка"})
        elif '"ok"' in system:
            text = json.dumps({"ok": seed % 5 != 0, "reason": "поддельный судья"})
        elif seed % 10 == 0 and not retry and "только JSON" not in last:
            text = "Ну... это сломанный ответ без JSON"
        else:
            actions = []
            low = last.lower()
            if not retry and ("дай" in low or "отдай" in low):
                actions = [{"type": "give_item", "item": "bow", "to": "kira"}]
            text = json.dumps(
                {
                    "say": "Хм. Не знаю, что тебе на это сказать.",
                    "emotion": "neutral",
                    "actions": actions,
                    "facts": [],
                },
                ensure_ascii=False,
            )
        pt, ct = sum(len(m["content"]) for m in messages) // 4, len(text) // 4
        cost = (pt * self.profile.price_in + ct * self.profile.price_out) / 1_000_000
        return Completion(text, pt, ct, 0.01, round(cost, 6))
