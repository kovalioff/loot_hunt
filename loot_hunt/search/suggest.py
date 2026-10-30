"""High-speed deterministic autocomplete and suggestion engine (<30ms).

Supports:
1. Multi-domain suggestions across all Ulovio verticals (electronics, travel, food/restaurants,
   groceries, fashion, home, auto, kids).
2. Word prefix completion: 'ноут' -> ['ноутбук', 'ноутбук игровой', ...].
3. Next-word prediction: 'сумка для ' -> ['сумка для ноутбука', 'сумка для ручной клади', ...].
4. Typo-tolerant and keyboard layout recovery: 'yjen' or 'нотуб' -> suggests 'ноутбук ...'.
5. Dynamic index extension from successful queries / catalog items.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Sequence

from .spelling import correct_query

# Canonical seed catalog of popular search phrases across all Ulovio verticals
POPULAR_SUGGESTIONS: tuple[str, ...] = (
    # Electronics
    "ноутбук",
    "ноутбук игровой",
    "ноутбук для работы и учёбы",
    "ноутбук Apple MacBook",
    "ноутбук Lenovo IdeaPad",
    "ноутбук ASUS ROG",
    "сумка для ноутбука",
    "подставка для ноутбука",
    "наушники",
    "наушники беспроводные",
    "наушники Sony WH-1000XM5",
    "наушники Apple AirPods Pro",
    "наушники с шумоподавлением",
    "чехол для AirPods",
    "смартфон",
    "смартфон Samsung Galaxy",
    "смартфон Xiaomi",
    "iPhone 15",
    "iPhone 15 Pro",
    "iPhone 16 Pro Max",
    "телевизор",
    "телевизор 55 дюймов 4K",
    "телевизор OLED",
    "монитор 27 дюймов 144Hz",
    "пылесос",
    "робот-пылесос",
    "робот-пылесос Dyson",
    "PlayStation 5",
    "консоль Nintendo Switch",
    # Food, Groceries & Restaurants
    "пицца",
    "пицца пепперони",
    "пицца четыре сыра",
    "доставка пиццы",
    "кофемашина",
    "кофемашина DeLonghi",
    "кофемашина Philips",
    "капсулы для кофемашины",
    "кофе в зернах",
    "кофе в капсулах",
    "суши и роллы сет",
    "бургеры с говядиной",
    "шашлык из свинины",
    "приправа для шашлыка",
    "сыр пармезан",
    "оливковое масло extra virgin",
    # Travel, Hotels & Tours
    "туры в Турцию",
    "туры в Турцию все включено",
    "туры в Египет",
    "туры выходного дня",
    "горящие туры",
    "тур в Анталью 7 ночей",
    "отели в Варшаве",
    "отели в Кракове",
    "отели в Берлине",
    "авиабилеты в Рим",
    "чемодан",
    "чемодан для ручной клади",
    "чехол на чемодан",
    "страховка для путешествий",
    # Clothes & Shoes
    "кроссовки",
    "кроссовки Nike Air Max",
    "кроссовки Adidas Originals",
    "ботинки зимние",
    "куртка осенняя",
    "куртка пуховик",
    "шнурки для кроссовок",
    "крем для обуви",
    "джинсы Levi's",
    "худи оверсайз",
    # Home, Auto, Kids
    "диван",
    "диван угловой раскладной",
    "чехол на диван",
    "стол письменный",
    "кресло компьютерное",
    "автотовары",
    "коврики в салон автомобиля",
    "видеорегистратор",
    "детские коляски",
    "конструктор LEGO City",
)

# Next-word completion patterns when input ends with a space
NEXT_WORD_COMPLETIONS: dict[str, tuple[str, ...]] = {
    "сумка для ": (
        "сумка для ноутбука",
        "сумка для ручной клади",
        "сумка для документов",
        "сумка для обуви",
    ),
    "чехол для ": (
        "чехол для iPhone 15",
        "чехол для AirPods Pro",
        "чехол для ноутбука",
        "чехол для чемодана",
    ),
    "чехол на ": (
        "чехол на диван",
        "чехол на чемодан",
        "чехол на сиденье автомобиля",
        "чехол на матрас",
    ),
    "тур в ": (
        "туры в Турцию",
        "туры в Турцию все включено",
        "туры в Египет",
        "туры в Грецию",
        "тур в Анталью 7 ночей",
    ),
    "туры в ": (
        "туры в Турцию",
        "туры в Турцию все включено",
        "туры в Египет",
        "туры в Испанию",
    ),
    "кофе в ": (
        "кофе в зернах",
        "кофе в капсулах",
        "кофе в зернах 1 кг",
        "кофе в дрип-пакетах",
    ),
    "наушники ": (
        "наушники беспроводные",
        "наушники Sony WH-1000XM5",
        "наушники Apple AirPods",
        "наушники с шумоподавлением",
    ),
    "ноутбук ": (
        "ноутбук игровой",
        "ноутбук для работы и учёбы",
        "ноутбук Apple MacBook",
        "ноутбук Lenovo IdeaPad",
    ),
    "пицца ": (
        "пицца пепперони",
        "пицца четыре сыра",
        "пицца маргарита",
        "пицца с морепродуктами",
    ),
    "кофемашина ": (
        "кофемашина DeLonghi",
        "кофемашина Philips",
        "кофемашина капсульная",
        "кофемашина рожковая",
    ),
    "кроссовки ": (
        "кроссовки Nike Air Max",
        "кроссовки Adidas Originals",
        "кроссовки мужские",
        "кроссовки женские",
    ),
}


@dataclass(frozen=True, slots=True)
class Suggestion:
    text: str
    matched_prefix: str
    highlight_span: tuple[int, int]
    category: str | None = None


class SuggestionEngine:
    def __init__(self, initial_items: Sequence[str] = POPULAR_SUGGESTIONS) -> None:
        self._items: list[str] = list(dict.fromkeys(initial_items))
        # Pre-calculate normalized mapping
        self._index: list[tuple[str, str]] = [
            (item, item.lower().replace("ё", "е")) for item in self._items
        ]

    def add_item(self, phrase: str) -> None:
        clean = phrase.strip()
        if len(clean) >= 2 and clean not in self._items:
            self._items.append(clean)
            self._index.append((clean, clean.lower().replace("ё", "е")))

    def suggest(self, query: str, *, limit: int = 6) -> list[Suggestion]:
        start_time = time.monotonic()
        raw = query.strip()
        if not raw:
            return []

        # 1. Check if user typed word ending with a space (next-word completion)
        if query.endswith(" ") or query.endswith("  "):
            norm_ending = raw.lower().replace("ё", "е") + " "
            for key, completions in NEXT_WORD_COMPLETIONS.items():
                if norm_ending == key or norm_ending.endswith(" " + key):
                    results = []
                    for comp in completions[:limit]:
                        results.append(
                            Suggestion(
                                text=comp,
                                matched_prefix=raw,
                                highlight_span=(0, len(raw)),
                            )
                        )
                    return results

        # 2. Check layout / typo correction on query first
        correction = correct_query(raw)
        search_target = correction.effective_query if correction.was_corrected else raw
        norm_target = search_target.lower().replace("ё", "е")

        matches: list[Suggestion] = []
        seen: set[str] = set()

        # Prefix matches first
        for original, normalized in self._index:
            if normalized.startswith(norm_target):
                if original not in seen:
                    seen.add(original)
                    matches.append(
                        Suggestion(
                            text=original,
                            matched_prefix=search_target,
                            highlight_span=(0, len(search_target)),
                        )
                    )
            if len(matches) >= limit:
                break

        # Infix / word-boundary matches second (if room left)
        if len(matches) < limit:
            for original, normalized in self._index:
                if original in seen:
                    continue
                # Word boundary match: e.g. 'ноутбук' matches in 'сумка для ноутбука'
                if f" {norm_target}" in normalized:
                    idx = normalized.find(f" {norm_target}") + 1
                    seen.add(original)
                    matches.append(
                        Suggestion(
                            text=original,
                            matched_prefix=search_target,
                            highlight_span=(idx, idx + len(search_target)),
                        )
                    )
                if len(matches) >= limit:
                    break

        # Fuzzy prefix match (e.g. 'нотуб' -> 'ноутбук') if still no matches
        if not matches and len(norm_target) >= 3:
            from .spelling import damerau_levenshtein_distance
            target_len = len(norm_target)
            for original, normalized in self._index:
                words = normalized.split()
                for word in words:
                    if len(word) >= target_len - 1:
                        sub = word[:target_len]
                        if damerau_levenshtein_distance(norm_target, sub) <= 1:
                            if original not in seen:
                                seen.add(original)
                                matches.append(
                                    Suggestion(
                                        text=original,
                                        matched_prefix=search_target,
                                        highlight_span=(0, len(sub)),
                                    )
                                )
                                break
                if len(matches) >= limit:
                    break

        return matches[:limit]


# Global singleton instance for high-speed calls
engine = SuggestionEngine()


def get_suggestions(query: str, *, limit: int = 6) -> list[dict]:
    """Return serialized suggestion dicts: [{'text': ..., 'highlight_span': ...}] in < 5ms."""
    items = engine.suggest(query, limit=limit)
    return [
        {
            "text": item.text,
            "matched_prefix": item.matched_prefix,
            "highlight_span": list(item.highlight_span),
        }
        for item in items
    ]
