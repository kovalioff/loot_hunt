"""Conservative query/offer type checks for device and accessory searches.

Only reject when title evidence identifies a conflicting item. Unknown products do
not inherit the rules for a device merely because they mention a generic brand.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalized(text: str) -> str:
    value = (text or "").translate(str.maketrans({"ł": "l", "Ł": "L", "ß": "ss"}))
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold()


ACCESSORIES = {
    "bag": r"\b(?:torb\w*|plecak\w*|backpack\w*|(?:laptop|notebook)?tasch\w*|(?:laptop|notebook)?rucksack\w*|bags?|briefcases?|сумк\w*|рюкзак\w*|портфел\w*)\b",
    "case": r"\b(?:etui|pokrow\w*|case|cases|cover|covers|schutzhu\w*|huelle\w*|hulle\w*|чехол\w*|чехл\w*|кейс\w*|футляр\w*)\b",
    "charger": r"\b(?:ladowark\w*|ladowac\w*|stacj\w*\s+(?:bezprzewodow\w*\s+)?laduj\w*|charger\w*|charging\s+(?:station|dock|stand|pad)|ladegerat\w*|ladestation\w*|ladepad\w*|зарядк\w*|зарядн\w*|блок\s+питания)\b",
    "tips": r"\b(?:koncowk\w*|nakladk\w*|ear\s*tips?|eartips?|ohrpolster\w*|ohrstops\w*|насадк\w*|амбушюр\w*)\b",
    "cable": r"\b(?:kabel(?!los)\w*|przewod\w*|cables?|кабел\w*|провод\w*)\b",
    "screen_protection": r"\b(?:szklo\w*|folia\w*|screen\s+protector\w*|panzerglas\w*|schutzfolie\w*|защитн\w*\s+(?:стекл\w*|пленк\w*))\b",
    "strap": r"\b(?:pasek|pask\w*|strap\w*|armband\w*|ремеш\w*)\b",
    "stand": r"\b(?:podstawk\w*|podkladk\w*|stojak\w*|stolik\w*|uchwyt\w*|(?:laptop|notebook)?stands?\w*|mounts?|halterung\w*|kuhlpad\w*|lapdesk\w*|подставк\w*|держател\w*|столик\w*)\b",
    "controller": r"\b(?:pad|gamepad\w*|controllers?|dualsense\w*|kontroler\w*|контроллер\w*|геймпад\w*|джойстик\w*)\b",
    "game": r"\b(?:gra|gry|games?|spiel\w*|игр(?!ов)\w*)\b",
    "filter": r"\b(?:filtr\w*|filters?|filter\w*|фильтр\w*|worki\s+do\s+odkurzacz\w*)\b",
    "brush": r"\b(?:szczotk\w*|brush\w*|burste\w*|щетк\w*|щеточ\w*)\b",
    "remote": r"\b(?:pilot\w*|remote\s+controls?|fernbedienung\w*|пульт\w*)\b",
}

DEVICES = {
    "earphones": r"\b(?:air\s*pods\w*|galaxy\s*buds\w*|pixel\s*buds\w*|earbuds\w*|earphones?\w*|headphones?\w*|sluchawk\w*|kopfh\w*|наушник\w*|аирподс\w*|эйрподс\w*)\b",
    "phone": r"\b(?:iphone\w*|smartfon\w*|smartphone\w*|telefon\w*|handy\w*|pixel\s*\d+\w*|galaxy\s*[sa]\d+\w*|айфон\w*|телефон\w*|смартфон\w*)\b",
    "laptop": r"\b(?:macbook\w*|laptop\w*|notebook\w*|ultrabook\w*|ноутбук\w*|макбук\w*)\b",
    "console": r"\b(?:ps[45]|playstation\s*[45]|xbox\w*|nintendo\s+switch\w*|konsol\w*|console\w*|konsole\w*|приставк\w*|консол\w*)\b",
    "watch": r"\b(?:apple\s*watch\w*|galaxy\s*watch\w*|smartwatch\w*|smart\s+watch\w*|умн\w*\s+час\w*)\b",
    "vacuum": r"\b(?:odkurzacz\w*|vacuum\w*|staubsauger\w*|saugroboter\w*|пылесос\w*)\b",
    "television": r"\b(?:telewizor\w*|television\w*|fernseher\w*|телевизор\w*)\b",
    "monitor": r"\b(?:monitor\w*|монитор\w*)\b",
}

BUNDLE_CONNECTOR = re.compile(r"(?:\+|\b(?:z|ze|wraz\s+z|i|oraz|and|und|with|mit|с|со|и)\b)")
BUNDLE_SUFFIX = re.compile(r"\b(?:w\s+zestawie|im\s+lieferumfang|included|в\s+комплекте)\b")
NEGATION = re.compile(r"(?:\b(?:bez|without|ohne|без|не)\s+)$")
CONTRACT = re.compile(
    r"\b(?:allnet|mobilfunkvertrag\w*|handyvertrag\w*|zahnzusatzversicherung\w*|versicherung\w*|abonament\w*|subscription\w*|подписк\w*|страховк\w*)\b"
    r"|\b(?:vodafone|telekom|freenet|klarmobil)\b.*\b(?:mtl|monat\w*|monthly)\b"
)


@dataclass(frozen=True)
class Intent:
    device: str | None
    accessory: str | None
    accessory_span: tuple[int, int] | None = None


def _first(text: str, patterns: dict[str, str]):
    matches = [(match.start(), name, match) for name, pattern in patterns.items() if (match := re.search(pattern, text))]
    return min(matches, key=lambda item: item[0]) if matches else None


def _negated_accessories(text: str) -> set[str]:
    return {name for name, pattern in ACCESSORIES.items() for match in re.finditer(pattern, text)
            if NEGATION.search(text[max(0, match.start() - 16):match.start()])}


def infer_intent(text: str) -> Intent:
    value = normalized(text)
    device = _first(value, DEVICES)
    accessory = _first(value, ACCESSORIES)
    if accessory:
        start, name, match = accessory
        if name == "game" and device and device[1] == "console" and start < device[0] and re.fullmatch(r"game\s+", value[start:device[0]]):
            accessory = None
        elif NEGATION.search(value[max(0, start - 16):start]):
            accessory = None
        elif device and device[0] < start and (BUNDLE_CONNECTOR.search(value[device[2].end():start]) or (BUNDLE_SUFFIX.search(value[start:]) and re.search(r"\b(?:sluchawk\w*|kopfh\w*|headphones?\w*|earbuds\w*|наушник\w*|konsol\w*|console\w*)\b", value[:start]))):
            accessory = None
        else:
            return Intent(device[1] if device else None, name, match.span())
    return Intent(device[1] if device else None, None)


def accessory_retrieval_query(query: str, platform: str) -> str | None:
    """Translate an explicit accessory noun without changing its target model."""
    intent = infer_intent(query)
    if not intent.accessory or not intent.accessory_span:
        return None
    terms = {
        "bag": {"pl": "torba", "de": "tasche"},
        "case": {"pl": "etui", "de": "hülle"},
        "charger": {"pl": "ładowarka", "de": "ladegerät"},
        "tips": {"pl": "końcówki", "de": "ohraufsätze"},
        "cable": {"pl": "kabel", "de": "kabel"},
        "screen_protection": {"pl": "szkło ochronne", "de": "schutzfolie"},
        "strap": {"pl": "pasek", "de": "armband"},
        "stand": {"pl": "podstawka", "de": "halterung"},
        "controller": {"pl": "kontroler", "de": "controller"},
        "game": {"pl": "gra", "de": "spiel"},
        "filter": {"pl": "filtr", "de": "filter"},
        "brush": {"pl": "szczotka", "de": "bürste"},
        "remote": {"pl": "pilot", "de": "fernbedienung"},
    }
    # Positions refer to normalized input. Replace only when normalization keeps
    # length; otherwise retain the original query as a retrieval fallback.
    if len(normalized(query)) != len(query):
        return None
    start, end = intent.accessory_span
    term = terms[intent.accessory].get(platform, terms[intent.accessory]["pl"])
    result = query[:start] + term + query[end:]
    result = re.sub(r"\b(?:для|for|für|fuer)\b", "für" if platform == "de" else "do", result, flags=re.IGNORECASE)
    target_terms = (
        (r"\bпылесос\w*", "staubsauger" if platform == "de" else "odkurzacza"),
        (r"\bнаушник\w*", "kopfhörer" if platform == "de" else "słuchawek"),
        (r"\b(?:айфон|айфона|айфону)\w*", "iphone"),
        (r"\b(?:телефон|смартфон)\w*", "handy" if platform == "de" else "telefonu"),
        (r"\b(?:ноутбук|макбук)\w*", "laptop"),
    )
    for pattern, replacement in target_terms:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return " ".join(result.split())


def _airpods_version(text: str):
    value = normalized(text)
    match = re.search(r"\bair\s*pods\s*(pro|max)?\s*\(?\s*(?:gen(?:eration)?\s*)?([1-9])(?!\d)", value)
    return (match.group(1) or "standard", int(match.group(2))) if match else None


def mismatch(query: str, title: str) -> str | None:
    from .structural_relevance import evaluate_structural_relevance

    struct_res = evaluate_structural_relevance(query, title)
    if struct_res.level == "IRRELEVANT":
        return struct_res.rejection or "accessory or structural mismatch"

    wanted = infer_intent(query)
    if not wanted.device and not wanted.accessory:
        return None
    forbidden = _negated_accessories(normalized(query))
    if any(re.search(ACCESSORIES[name], normalized(title)) for name in forbidden):
        return "explicitly excluded accessory"
    actual = infer_intent(title)
    if wanted.device and not wanted.accessory and CONTRACT.search(normalized(title)) and not CONTRACT.search(normalized(query)):
        return "contract or subscription instead of standalone device"
    if wanted.accessory:
        if actual.accessory != wanted.accessory:
            return "requested accessory type not confirmed"
    elif wanted.device and actual.accessory:
        return "accessory instead of requested device"
    query_variant = re.search(r"\bair\s*pods\s*(pro|max)\b", normalized(query))
    if query_variant and not re.search(r"\bair\s*pods\s*" + query_variant.group(1) + r"\b", normalized(title)):
        return "requested AirPods variant not confirmed"
    if expected := _airpods_version(query):
        if _airpods_version(title) != expected:
            return "requested AirPods generation not confirmed"
    return None
