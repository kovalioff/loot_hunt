from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    name: str
    path: str
    emoji: str = "•"
    children: tuple[Category, ...] = field(default_factory=tuple)


# Verified parent paths, with the two additional 2026 Pepper parents documented by Pepper Help.
PARENTS: tuple[Category, ...] = (
    Category("electronics", "Электроника", "/grupa/elektronika", "💻"),
    Category("gaming", "Gaming", "/grupa/gry", "🎮"),
    Category("home", "Дом", "/grupa/dom-i-mieszkanie", "🏠"),
    Category("garden", "Сад и ремонт", "/grupa/dom", "🔧"),
    Category("fashion", "Мода", "/grupa/moda", "👟"),
    Category("health", "Красота и здоровье", "/grupa/zdrowie-i-uroda", "💄"),
    Category("family", "Семья и дети", "/grupa/dla-dzieci", "👶"),
    Category("grocery", "Продукты", "/grupa/artykuly-spozywcze", "🛒"),
    Category("travel", "Путешествия", "/grupa/podroze", "✈️"),
    Category("auto", "Авто", "/grupa/motoryzacja", "🚗"),
    Category("culture", "Культура", "/grupa/rozrywka", "🎬"),
    Category("sport", "Спорт", "/grupa/sport", "🏃"),
    Category("telecom", "Интернет и связь", "/grupa/internet-i-uslugi", "📡"),
    Category("finance", "Финансы и страхование", "/grupa/finanse-i-ubezpieczenia", "💳"),
    Category("services", "Услуги", "/grupa/uslugi-i-subskrypcje", "🧾"),
)


def categories_from_state(state: dict[str, Any]) -> tuple[Category, ...]:
    """Extract an arbitrary-depth category tree from Pepper navigation page state."""
    candidates: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            path = node.get("url") or node.get("path")
            title = node.get("title") or node.get("name")
            if isinstance(path, str) and path.startswith("/grupa/") and title:
                candidates.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(state)

    def convert(raw: dict[str, Any]) -> Category:
        path = str(raw.get("url") or raw.get("path"))
        children_raw = raw.get("children") or raw.get("subcategories") or raw.get("groups") or []
        children = tuple(convert(child) for child in children_raw if isinstance(child, dict))
        identifier = str(raw.get("groupId") or raw.get("id") or path.rsplit("/", 1)[-1])
        return Category(
            identifier, str(raw.get("title") or raw.get("name")), path, children=children
        )

    roots: list[Category] = []
    seen: set[str] = set()
    for raw in candidates:
        path = str(raw.get("url") or raw.get("path"))
        if path not in seen:
            seen.add(path)
            roots.append(convert(raw))
    return tuple(roots)


def flatten(categories: tuple[Category, ...]) -> dict[str, Category]:
    result: dict[str, Category] = {}

    def add(category: Category) -> None:
        result[category.key] = category
        for child in category.children:
            add(child)

    for item in categories:
        add(item)
    return result


def category_from_group(group: dict[str, Any], *, fallback: Category | None = None) -> Category:
    """Convert Pepper's current INITIAL_STATE.group hierarchy."""

    def convert(raw: dict[str, Any]) -> Category:
        identifier = str(raw.get("threadGroupId") or raw.get("id") or "")
        slug = str(raw.get("threadGroupUrlName") or raw.get("slug") or "")
        name = str(raw.get("threadGroupName") or raw.get("name") or slug)
        children = tuple(
            convert(child) for child in raw.get("children", []) if isinstance(child, dict)
        )
        return Category(identifier or slug, name, f"/grupa/{slug}", children=children)

    live = convert(group)
    if not fallback:
        return live
    return Category(fallback.key, fallback.name, live.path, fallback.emoji, live.children)
