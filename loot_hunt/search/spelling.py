"""Deterministic typo tolerance, keyboard layout auto-correction, and transliteration.

Zero-AI, high-performance module for RU, PL, DE, EN:
1. Keyboard layout switching (QWERTY <-> ЙЦУКЕН).
2. Orthography, double consonants and diacritics normalization.
3. Transliteration of brands and common category terms.
4. Damerau-Levenshtein fuzzy matching against multi-domain dictionary.
5. IMMUNITY for alphanumeric hardware models and numbers (e.g. WH-1000XM5, DDR5, RTX 4060).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# QWERTY <-> ЙЦУКЕН layout mapping
EN_TO_RU_LAYOUT = str.maketrans({
    "q": "й", "w": "ц", "e": "у", "r": "к", "t": "е", "y": "н", "u": "г", "i": "ш", "o": "щ", "p": "з",
    "[": "х", "]": "ъ", "a": "ф", "s": "ы", "d": "в", "f": "а", "g": "п", "h": "р", "j": "о", "k": "л",
    "l": "д", ";": "ж", "'": "э", "z": "я", "x": "ч", "c": "с", "v": "м", "b": "и", "n": "т", "m": "ь",
    ",": "б", ".": "ю", "`": "ё",
    "Q": "Й", "W": "Ц", "E": "У", "R": "К", "T": "Е", "Y": "Н", "U": "Г", "I": "Ш", "O": "Щ", "P": "З",
    "{": "Х", "}": "Ъ", "A": "Ф", "S": "Ы", "D": "В", "F": "А", "G": "П", "H": "Р", "J": "О", "K": "Л",
    "L": "Д", ":": "Ж", '"': "Э", "Z": "Я", "X": "Ч", "C": "С", "V": "М", "B": "И", "N": "Т", "M": "Ь",
    "<": "Б", ">": "Ю", "~": "Ё",
})

RU_TO_EN_LAYOUT = str.maketrans({
    "й": "q", "ц": "w", "у": "e", "к": "r", "е": "t", "н": "y", "г": "u", "ш": "i", "щ": "o", "з": "p",
    "х": "[", "ъ": "]", "ф": "a", "ы": "s", "в": "d", "а": "f", "п": "g", "р": "h", "о": "j", "л": "k",
    "д": "l", "ж": ";", "э": "'", "я": "z", "ч": "x", "с": "c", "м": "v", "и": "b", "т": "n", "ь": "m",
    "б": ",", "ю": ".", "ё": "`",
    "Й": "Q", "Ц": "W", "У": "E", "К": "R", "Е": "T", "Н": "Y", "Г": "U", "Ш": "I", "Щ": "O", "З": "P",
    "Х": "{", "Ъ": "}", "Ф": "A", "Ы": "S", "В": "D", "А": "F", "П": "G", "Р": "H", "О": "J", "Л": "K",
    "Д": "L", "Ж": ":", "Э": '"', "Я": "Z", "Ч": "X", "С": "C", "М": "V", "И": "B", "Т": "N", "Ь": "M",
    "Б": "<", "Ю": ">", "Ё": "~",
})

# Brand and category transliterations (Russian phonetics -> Latin brand / standard term)
TRANSLITERATIONS: dict[str, str] = {
    # Electronics / Tech
    "айфон": "iphone",
    "айфона": "iphone",
    "айфоны": "iphone",
    "айпад": "ipad",
    "макбук": "macbook",
    "макбука": "macbook",
    "макбуки": "macbook",
    "аирподс": "airpods",
    "эйрподс": "airpods",
    "сяоми": "xiaomi",
    "ксиоми": "xiaomi",
    "ксиаоми": "xiaomi",
    "хиаоми": "xiaomi",
    "сони": "sony",
    "самсунг": "samsung",
    "самсунга": "samsung",
    "бош": "bosch",
    "дайсон": "dyson",
    "делонги": "delonghi",
    "делонжи": "delonghi",
    "асус": "asus",
    "эйсер": "acer",
    "асер": "acer",
    "леново": "lenovo",
    "хуавей": "huawei",
    "хонор": "honor",
    "филипс": "philips",
    "тефаль": "tefal",
    "браун": "braun",
    "нинтендо": "nintendo",
    "плейстейшн": "playstation",
    "плейстейшен": "playstation",
    "сони плейстейшн": "playstation",
    "иксбокс": "xbox",
    "хбокс": "xbox",
    "свитч": "switch",
    "свич": "switch",
    "киндл": "kindle",
    "гармин": "garmin",
    # Cars / Auto
    "бмв": "bmw",
    "мерседес": "mercedes",
    "ауди": "audi",
    "фольксваген": "volkswagen",
    "тойота": "toyota",
    "шкода": "skoda",
    "хендай": "hyundai",
    "хендэ": "hyundai",
    "киа": "kia",
    "мазда": "mazda",
    # Food / Coffee / Brands
    "неспрессо": "nespresso",
    "дольче густо": "dolce gusto",
    "лавецца": "lavazza",
    "лавацца": "lavazza",
    "пепси": "pepsi",
    "кока кола": "coca-cola",
    # Clothes / Fashion
    "найк": "nike",
    "адидас": "adidas",
    "пума": "puma",
    "рибок": "reebok",
    "нью беланс": "new balance",
    "нью бэланс": "new balance",
    "зара": "zara",
}

# Frequent spelling simplifications / double consonants
COMMON_VARIANTS: dict[str, str] = {
    "пица": "пицца",
    "пицу": "пиццу",
    "пицы": "пиццы",
    "кросовки": "кроссовки",
    "кросовок": "кроссовок",
    "каппучино": "капучино",
    "еспрессо": "эспрессо",
    "экспрессо": "эспрессо",
    "кофемашына": "кофемашина",
    "кофе машина": "кофемашина",
    "робот пылесос": "робот-пылесос",
    "ноут бук": "ноутбук",
    "телевизер": "телевизор",
    "пылисос": "пылесос",
}

# Multi-domain dictionary of canonical vocabulary (RU, PL, DE, EN) across all Ulovio verticals
MULTI_DOMAIN_VOCABULARY: set[str] = {
    # Electronics & Gadgets
    "ноутбук", "ноутбуки", "ноутбука", "ноутбуков", "игровой", "игровые", "ноут",
    "наушники", "наушников", "беспроводные", "гарнитура",
    "смартфон", "смартфоны", "смартфона", "телефон", "телефоны", "телефона",
    "планшет", "планшеты", "планшета",
    "телевизор", "телевизоры", "телевизора", "монитор", "мониторы", "монитора",
    "пылесос", "пылесосы", "пылесоса", "робот-пылесос",
    "клавиатура", "мышь", "видеокарта", "процессор", "накопитель", "колонки",
    "часы", "смарт-часы", "браслет", "приставка", "консоль",
    # Food, Groceries, Restaurants, Kitchen
    "пицца", "пиццы", "пиццу", "пиццерия", "пепперони", "сырная",
    "суши", "роллы", "бургер", "бургеры", "доставка", "ресторан", "рестораны",
    "кофемашина", "кофеварка", "кофемолка", "кофе", "зерновой", "молотый", "капсулы",
    "шашлык", "стейк", "мясо", "сыр", "молоко", "масло", "хлеб", "шоколад", "чай",
    "сковорода", "кастрюля", "ножи", "блендер", "миксер", "чайник", "гриль", "духовка",
    # Travel, Tours, Hotels
    "тур", "туры", "тура", "туров", "горящие", "путевка", "путевки", "путевку",
    "отель", "отели", "отеля", "гостиница", "гостиницы", "билеты", "авиабилеты",
    "турция", "турцию", "турции", "египет", "греция", "испания", "италия", "кипр",
    "анталья", "стамбул", "варшава", "краков", "берлин", "мюнхен", "париж", "рим",
    "чемодан", "чемоданы", "чемодана", "рюкзак", "сумка", "страховка", "трансфер",
    # Clothes, Shoes, Accessories
    "кроссовки", "кроссовок", "кеды", "ботинки", "сапоги", "туфли", "обувь",
    "куртка", "куртки", "пальто", "пуховик", "ветровка", "худи", "толстовка",
    "джинсы", "брюки", "штаны", "рубашка", "футболка", "платье", "юбка",
    "шнурки", "стельки", "крем", "крем для обуви", "шапка", "перчатки", "ремень",
    # Home, Furniture, Garden, Auto
    "диван", "диваны", "дивана", "кресло", "стул", "стол", "кровать", "матрас",
    "шкаф", "комод", "полка", "ковер", "покрывало", "подушка", "одеяло",
    "посудомойка", "стиралка", "холодильник", "плита", "микроволновка",
    "автомобиль", "машина", "автотовары", "коврики", "аккумулятор", "резина", "шины",
    # Polish terms
    "laptop", "laptopy", "słuchawki", "smartfon", "telefon", "telewizor", "monitor",
    "odkurzacz", "ekspres", "kawa", "pizza", "wycieczka", "wakacje", "hotel", "loty",
    "buty", "kurtka", "spodnie", "sukienka", "kanapa", "fotel", "stół", "lodówka",
    # German terms
    "laptop", "notebook", "kopfhörer", "smartphone", "fernseher", "staubsauger",
    "kaffeemaschine", "kaffee", "pizza", "reise", "urlaub", "hotel", "flüge",
    "schuhe", "jacke", "hose", "sofa", "tisch", "kühlschrank",
    # English terms / Global brands
    "laptop", "headphones", "smartphone", "iphone", "macbook", "ipad", "airpods",
    "sony", "samsung", "xiaomi", "dell", "lenovo", "asus", "acer", "apple",
    "pizza", "coffee", "tour", "hotel", "shoes", "jacket", "sofa",
}


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    original_query: str
    effective_query: str
    was_corrected: bool
    did_you_mean: str | None = None
    reason: str | None = None


def is_hardware_or_model_code(token: str) -> bool:
    """Check if token is an alphanumeric hardware model or specification token.

    CRITICAL RULE: Alphanumeric model numbers, SKUs, and specifications
    (e.g., WH-1000XM5, XM5, RTX 4060, DDR5, i7-13700K, PS5, 128GB, 15.6)
    must NEVER be modified by typo-tolerance.
    """
    clean = token.strip(" ,.-!?()/").lower()
    if not clean:
        return False
    # Pure numbers (e.g. 2500, 4060, 15)
    if clean.isdigit():
        return True
    # Has both digits and letters: e.g. xm5, rtx4060, ddr5, ps5, 128gb, t14, etc.
    has_digit = any(c.isdigit() for c in clean)
    has_alpha = any(c.isalpha() for c in clean)
    if has_digit and has_alpha:
        return True
    # Known standalone hardware prefixes/series
    if clean in {
        "rtx", "gtx", "rx", "ddr4", "ddr5", "pcie", "oled", "qled", "ips", "amoled",
        "anc", "pro", "max", "ultra", "mini", "plus", "slim", "lite", "se", "fe",
    }:
        return True
    return False


def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Damerau-Levenshtein distance between two strings."""
    d: dict[tuple[int, int], int] = {}
    len1, len2 = len(s1), len(s2)
    for i in range(-1, len1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, len2 + 1):
        d[(-1, j)] = j + 1

    for i in range(len1):
        for j in range(len2):
            cost = 0 if s1[i] == s2[j] else 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,          # deletion
                d[(i, j - 1)] + 1,          # insertion
                d[(i - 1, j - 1)] + cost,   # substitution
            )
            if i > 0 and j > 0 and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + 1)  # transposition

    return d[(len1 - 1, len2 - 1)]


def fix_wrong_keyboard_layout(text: str) -> str | None:
    """Check if query was typed in the wrong keyboard layout (RU <-> EN)."""
    # 1. English to Russian layout (e.g. 'yjen,er' -> 'ноутбук', 'gbwwf' -> 'пицца')
    # Convert only recognized words; a valid brand or model in a mixed query
    # must not be translated merely because another word has the wrong layout.
    known = (
        MULTI_DOMAIN_VOCABULARY | set(TRANSLITERATIONS)
        | set(TRANSLITERATIONS.values()) | set(COMMON_VARIANTS)
    )
    parts = re.split(r"(\s+)", text)
    changed = False
    for index, token in enumerate(parts):
        if not token.strip() or token.lower() in known or is_hardware_or_model_code(token):
            continue
        table = RU_TO_EN_LAYOUT if re.search(r"[а-яё]", token, re.IGNORECASE) else EN_TO_RU_LAYOUT
        candidate = token.translate(table).lower()
        recognized = candidate in known or correct_single_word_typo(candidate)
        if candidate != token.lower() and recognized:
            parts[index] = candidate
            changed = True
    if changed:
        for index, token in enumerate(parts):
            candidate = token.translate(EN_TO_RU_LAYOUT).lower()
            if token.lower() not in known and candidate in {"в", "для", "до", "на", "с", "и", "от"}:
                parts[index] = candidate
    return "".join(parts) if changed else None


def correct_single_word_typo(word: str) -> str | None:
    """Fuzzy match single word against domain vocabulary if length >= 4."""
    norm = word.lower()
    if len(norm) < 4:
        return None
    if is_hardware_or_model_code(norm):
        return None
    if norm in MULTI_DOMAIN_VOCABULARY:
        return None

    # Check common phonetic / double consonants
    if norm in COMMON_VARIANTS:
        return COMMON_VARIANTS[norm]

    # Find closest match with Damerau-Levenshtein distance == 1
    best_match = None
    min_dist = 2
    ambiguous = False
    for vocab in sorted(MULTI_DOMAIN_VOCABULARY):
        # Length filter: must be within +/- 1 character
        if abs(len(vocab) - len(norm)) > 1:
            continue
        # First letter must match (or second if first was accidentally dropped/inserted)
        if vocab[0] != norm[0] and len(norm) > 4:
            continue
        dist = damerau_levenshtein_distance(norm, vocab)
        if dist < min_dist:
            min_dist = dist
            best_match = vocab
            ambiguous = False
        elif dist == min_dist:
            ambiguous = True

    return best_match if min_dist == 1 and not ambiguous else None


def correct_query(query: str) -> CorrectionResult:
    """Perform deterministic layout, transliteration, and typo correction on query.

    Returns CorrectionResult with original_query, effective_query, and was_corrected.
    """
    raw = query.strip()
    if not raw:
        return CorrectionResult(raw, raw, False)

    # 1. Check wrong keyboard layout first
    layout_fixed = fix_wrong_keyboard_layout(raw)
    working = layout_fixed or raw

    # 2. Tokenize and examine each token
    corrected_tokens = []
    any_token_corrected = bool(layout_fixed)

    # Check multi-word transliterations first (e.g., 'сони плейстейшн' -> 'playstation')
    phrases = TRANSLITERATIONS | COMMON_VARIANTS
    for phrase in sorted(phrases, key=len, reverse=True):
        if " " in phrase:
            working, count = re.subn(
                rf"\b{re.escape(phrase)}\b", phrases[phrase], working, flags=re.IGNORECASE
            )
            any_token_corrected |= bool(count)

    # Re-tokenize potentially updated string
    tokens = re.split(r"(\s+|[,!?;/]+)", working)

    for token in tokens:
        # Keep whitespace/separators as-is
        if not token.strip() or re.match(r"^[\s,\-!?;/]+$", token):
            corrected_tokens.append(token)
            continue

        clean_token = token.lower()

        # Check hardware code immunity
        if is_hardware_or_model_code(clean_token):
            corrected_tokens.append(token)
            continue

        # Check single-word transliterations (e.g. 'айфон' -> 'iphone', 'сяоми' -> 'xiaomi')
        if clean_token in TRANSLITERATIONS:
            corrected_tokens.append(TRANSLITERATIONS[clean_token])
            any_token_corrected = True
            continue

        # Check common variants (e.g. 'пица' -> 'пицца', 'кросовки' -> 'кроссовки')
        if clean_token in COMMON_VARIANTS:
            corrected_tokens.append(COMMON_VARIANTS[clean_token])
            any_token_corrected = True
            continue

        # Check single-word typos (Damerau-Levenshtein distance == 1)
        if typo_fix := correct_single_word_typo(clean_token):
            corrected_tokens.append(typo_fix)
            any_token_corrected = True
            continue

        corrected_tokens.append(token)

    effective = "".join(corrected_tokens).strip()
    # Normalize spaces
    effective = " ".join(effective.split())

    was_corrected = any_token_corrected and (effective.lower() != raw.lower())
    return CorrectionResult(
        original_query=raw,
        effective_query=effective if was_corrected else raw,
        was_corrected=was_corrected,
        did_you_mean=effective if was_corrected else None,
        reason="typo/transliteration corrected" if was_corrected else None,
    )
