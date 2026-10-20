"""Проверка новых релизов на GitHub — только по явной команде пользователя.

Никаких фоновых запросов и телеметрии: функция вызывается из диалога «О
программе», ходит один раз на api.github.com и больше ничего не делает.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

REPO = "Thunderouse/mediaforge"
TIMEOUT = 8.0
USER_AGENT = "MediaForge-update-check"


class UpdateError(RuntimeError):
    """Сеть недоступна, репозиторий закрыт или ответ не разобрать."""


@dataclass
class Release:
    version: str
    url: str
    notes: str = ""
    published: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.0' -> (1, 2, 0); хвосты вроде '-beta' отбрасываются."""
    numbers = re.findall(r"\d+", str(text).split("-")[0])
    return tuple(int(n) for n in numbers) if numbers else (0,)


def is_newer(latest: str, current: str) -> bool:
    left, right = parse_version(latest), parse_version(current)
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


def fetch_latest(repo: str = REPO, timeout: float = TIMEOUT, attempts: int = 2) -> dict:
    """Сырой JSON последнего релиза. Отдельная функция — её подменяют в тестах.

    Две попытки: на мобильном/Wi-Fi первый запрос часто обрывается по TLS.
    """
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise UpdateError("Релизы не найдены (возможно, репозиторий закрыт)") from exc
            raise UpdateError(f"GitHub ответил ошибкой {exc.code}") from exc
        except json.JSONDecodeError as exc:
            raise UpdateError("Неожиданный ответ GitHub") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0)
    raise UpdateError("Не удалось связаться с GitHub — проверьте интернет") from last_error


def check_latest(current: str, repo: str = REPO,
                 fetcher=fetch_latest) -> Release | None:
    """Возвращает новый релиз или None, если установлена последняя версия."""
    data = fetcher(repo)
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        raise UpdateError("В ответе GitHub нет номера версии")
    version = tag.lstrip("vV")
    if not is_newer(version, current):
        return None
    return Release(
        version=version,
        url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        notes=str(data.get("body") or "")[:4000],
        published=str(data.get("published_at") or ""),
    )


__all__ = ["REPO", "Release", "UpdateError", "check_latest", "fetch_latest",
           "is_newer", "parse_version"]
