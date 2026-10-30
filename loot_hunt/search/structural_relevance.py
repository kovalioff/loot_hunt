"""Multi-domain deterministic syntactic and structural search relevance analyzer.

Universal rules for RU, PL, DE, EN without neural networks, embeddings or external APIs:
1. Head (what is sought/sold) vs Target/Modifier (for what / with what / to what it relates).
2. Prepositional compatibility templates in normal and inverted order.
3. German Komposita (right-head decomposition).
4. Bundle detection (main head before bundle connector remains RELEVANT).
5. Defect, empty box, and missing item rejection.
6. Exact model code normalization, generation conflict protection, and multi-model spam filtering.
7. 3-level evaluation: RELEVANT, UNCERTAIN, IRRELEVANT.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

RelevanceLevel = Literal["RELEVANT", "UNCERTAIN", "IRRELEVANT"]

# Normalize text: strip diacritics, lowercase, unify spaces
POLISH_CHAR_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n", "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
    "ß": "ss", "ä": "a", "ö": "o", "ü": "u",
    "Ä": "a", "Ö": "o", "Ü": "u",
})


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.translate(POLISH_CHAR_MAP)
    decomposed = unicodedata.normalize("NFKD", cleaned)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(stripped.split())


# Bundle connectors: content after connector is an included bonus/accessory
BUNDLE_CONNECTOR_PATTERN = re.compile(
    r"(?:\s+\+\s+|\s+&\s+|\b(?:z|ze|wraz\s+z|oraz|and|und|with|mit|с|со|вместе\s+с|плюс)\b|"
    r"\b(?:w\s+zestawie|w\s+pakiecie|gratis|darmo|inkl\b|inklusive|im\s+set|im\s+lieferumfang|"
    r"в\s+комплекте|в\s+подарок|бесплатно\s+в\s+комплекте|bundle)\b)",
    re.IGNORECASE,
)

# Prepositional compatibility markers (normal order: [Head X] + [prep] + [Target Y])
# Also supports inverted order: [prep] + [Target Y] + [Head X]
COMPATIBILITY_PREPOSITIONS = (
    # RU
    r"для", r"к", r"под", r"от", r"на", r"подходит\s+для", r"совместим(?:о|ый|ая|ое)?\s+с",
    # PL
    r"do", r"dla", r"na", r"pod", r"pasuje\s+do", r"kompatybiln[yae]\s+z", r"przeznaczon[yae]\s+do",
    # DE
    r"für", r"fuer", r"fur", r"zu", r"zum", r"zur", r"passend\s+für", r"passend\s+fuer", r"passend\s+fur",
    r"kompatibel\s+mit", r"geeignet\s+für", r"geeignet\s+fuer", r"geeignet\s+fur",
    # EN
    r"for", r"fits", r"compatible\s+with", r"designed\s+for", r"suitable\s+for",
)

COMPATIBILITY_PREP_REGEX = re.compile(
    rf"\b(?:{'|'.join(COMPATIBILITY_PREPOSITIONS)})\b",
    re.IGNORECASE,
)

# Universal Accessory / Consumable / Packaging / Service heads across domains:
ACCESSORY_HEAD_PATTERNS = {
    # Tech / Gadgets: Bags, Cases, Covers, Sleeves
    "bag_case": (
        r"\b(?:torb\w*|plecak\w*|etui\w*|pokrow\w*|futeral\w*|saszetk\w*|"
        r"tasch\w*|rucksack\w*|hüll\w*|huell\w*|hull\w*|schutzhüll\w*|schutzhuell\w*|schutzhull\w*|"
        r"case|cases|cover|covers|sleeve\w*|pouch\w*|"
        r"сумк\w*|рюкзак\w*|чехол\w*|чехл\w*|кейс\w*|футляр\w*|обложк\w*|портфел\w*)\b"
    ),
    # Chargers, cables, power, docks, mounts, stands
    "power_mount": (
        r"\b(?:ładowark\w*|ladowark\w*|przewód\w*|przewod\w*|kabel(?!los)\w*|podstawk\w*|podkładk\w*|podkladk\w*|stojak\w*|uchwyt\w*|stolik\w*|"
        r"ladegerät\w*|ladegeraet\w*|ladegerat\w*|ladestation\w*|halterung\w*|ständer\w*|staender\w*|stander\w*|"
        r"mount|dock|stand|kuhlpad\w*|"
        r"зарядк\w*|зарядн\w*|блок\s+питания|кабел\w*|провод\w*|подставк\w*|держател\w*|креплени\w*|столик\w*)\b"
    ),
    # Screen protection, glass, films
    "screen_protection": (
        r"\b(?:szkło\w*|szklo\w*|folia\w*|panzerglas\w*|schutzfolie\w*|screen\s+protector\w*|"
        r"защитн\w*\s+(?:стекл\w*|пленк\w*)|бронепленк\w*)\b"
    ),
    # Replacement parts, tips, ear pads, filters, brushes
    "parts_filters": (
        r"\b(?:końcówk\w*|koncowk\w*|nakładk\w*|nakladk\w*|filtr\w*|szczotk\w*|pasek\w*|pask\w*|"
        r"ohrpolster\w*|ohrstöpsel\w*|ohrstopsel\w*|aufsaetz\w*|aufsätz\w*|aufsatz\w*|bürste\w*|buerste\w*|burste\w*|"
        r"filter\w*|armband\w*|"
        r"амбушюр\w*|насадк\w*|фильтр\w*|щетк\w*|ремеш\w*|сменн\w*\s+лезви\w*)\b"
    ),
    # Food & Kitchen consumables: boxes, spices, seasonings, pods, descalers
    "food_consumable": (
        r"\b(?:pudełko\w*|pudelko\w*|karton\w*|opakowani\w*|"
        r"przypraw\w*|kapsułk\w*|kapsulk\w*|odkamieniacz\w*|"
        r"pizzakarton\w*|karton\w*|schachtel\w*|verpackung\w*|gewürz\w*|gewuerz\w*|gewurz\w*|kapsel\w*|entkalker\w*|"
        r"коробк\w*|упаковк\w*|тара\w*|ящик\w*|приправ\w*|специ\w*|капсул\w*|очистител\w*|средство\s+от\s+накипи)\b"
    ),
    # Travel / Tourism: insurance, suitcase covers, transfer
    "travel_service": (
        r"\b(?:ubezpieczeni\w*|transfer\w*|pokrowiec\s+na\s+walizk\w*|"
        r"reiseversicherung\w*|versicherung\w*|transfer\w*|kofferhüll\w*|kofferhuell\w*|kofferhull\w*|"
        r"страховк\w*|полис\w*|трансфер\w*|чехол\s+на\s+чемодан)\b"
    ),
    # Clothes, shoes, home, auto: shoe trees, polish, covers, floor mats
    "care_mats_covers": (
        r"\b(?:prawidł\w*|prawidlo\w*|prawidl\w*|pasta\s+do\s+butów|pasta\s+do\s+butow|sznurowadł\w*|sznurowadlo\w*|"
        r"sznurowadl\w*|wkładk\w*|wkladk\w*|"
        r"pokrowiec\s+na\s+kanap\w*|narzuta\s+na\s+sof\w*|dywaniki\s+do\w*|dywanik\w*|"
        r"schuhspanner\w*|schuhcreme\w*|schnürsenkel\w*|schnuersenkel\w*|schnursenkel\w*|einlegesohl\w*|sofabezug\w*|"
        r"fußmatten\w*|fussmatten\w*|fussmatte\w*|"
        r"крем\s+для\s+обуви|шнурк\w*|стельк\w*|формодержател\w*|чехол\s+на\s+диван|покрывало\s+на\s+диван|коврик\w*)\b"
    ),
}

# German Komposita right-head suffixes that indicate an accessory/service/container
GERMAN_KOMPOSITA_SUFFIXES = (
    "tasche", "taschen",
    "ständer", "staender", "stander",
    "halter", "halterung", "halterungen",
    "polster", "ohrpolster",
    "karton", "pizzakarton", "kartons",
    "entkalker", "reiniger",
    "spanner", "schuhspanner",
    "versicherung", "reiseversicherung",
    "hülle", "huelle", "hulle", "hüllen", "huellen", "hullen",
    "schutzhülle", "schutzhuelle", "schutzhulle",
    "glas", "panzerglas", "displayglas",
    "folie", "schutzfolie",
    "kabel", "ladekabel",
    "bezug", "sofabezug", "sitzbezug",
    "matte", "matten", "fussmatte", "fussmatten", "fußmatte", "fußmatten",
    "überwurf", "ueberwurf", "uberwurf",
    "aufsatz", "aufsätze", "aufsaetze", "aufsaetze",
    "adapter",
)

# Cross-lingual target families (RU <-> PL <-> DE <-> EN)
CROSS_LINGUAL_SYNONYMS: dict[str, set[str]] = {
    "laptop": {
        "ноутбук", "ноутбука", "ноутбуки", "ноут", "лэптоп", "laptop", "laptopa", "laptopy",
        "notebook", "notebooka", "notebooki", "macbook",
    },
    "headphones": {
        "наушники", "наушников", "наушникам", "гарнитура", "słuchawki", "sluchawki",
        "sluchawek", "słuchawek", "kopfhörer", "kopfhorer", "kopfhorer", "headphones",
        "earbuds", "earphones", "airpods",
    },
    "phone": {
        "телефон", "телефона", "смартфон", "смартфона", "smartfon", "telefon", "telefonu",
        "handy", "smartphone", "iphone",
    },
    "coffee_machine": {
        "кофемашина", "кофемашины", "кофеварка", "кофе", "kawa", "kawy", "kaffee", "ekspres",
        "ekspresu", "kaffeemaschine", "nespresso",
    },
    "pizza": {
        "пицца", "пиццы", "пиццу", "pizza", "pizze", "pizzy", "pizzę",
    },
    "tour": {
        "тур", "тура", "туры", "турцию", "турция", "путевка", "путевки", "отдых",
        "wycieczka", "wycieczki", "wakacje", "reise", "urlaub", "tour", "türkei", "turkei",
    },
    "suitcase": {
        "чемодан", "чемодана", "чемоданы", "walizka", "walizki", "walizkę", "koffer",
        "suitcase", "luggage",
    },
    "sofa": {
        "диван", "дивана", "диваны", "kanapa", "kanapy", "kanapę", "sofa", "couch",
    },
    "shoes": {
        "обувь", "туфли", "ботинки", "кроссовки", "кроссовок", "but", "buty", "butów", "butow",
        "schuh", "schuhe", "sneaker", "shoes",
    },
    "auto": {
        "машина", "машины", "автомобиль", "авто", "samochód", "samochodu", "auto", "pkw",
        "car", "bmw", "audi", "mercedes",
    },
}

# Rejection markers: defects, empty packaging, missing components, dummy units
DEFECT_EMPTY_MARKERS = re.compile(
    r"\b(?:"
    r"без\s+\w+|bez\s+\w+|ohne\s+\w+|without\s+\w+|"
    r"только\s+(?:коробка|бокс|кейс|упаковка|корпус)|пустая\s+коробка|samo\s+pudełko|samo\s+pudelko|leerkarton|nur\s+ovp|empty\s+box|only\s+box|"
    r"на\s+запчасти|uszkodzon\w*|defekt\w*|ersatzteil\w*|муляж\w*|пробник\w*|dummy|for\s+parts"
    r")\b",
    re.IGNORECASE,
)

# Contracts / subscriptions (SIM contracts, mobile plans)
CONTRACT_MARKERS = re.compile(
    r"\b(?:"
    r"allnet|mobilfunkvertrag\w*|handyvertrag\w*|zahnzusatzversicherung\w*|abonament\w*|subscription\w*|"
    r"подписк\w*|тариф\w*|контракт\w*"
    r")\b|\b(?:vodafone|telekom|freenet|klarmobil|o2)\b.*\b(?:mtl|monat\w*|monthly)\b",
    re.IGNORECASE,
)


# Known standalone brands (for generic brand queries where user does not specify a product type)
KNOWN_BRANDS = frozenset({
    "sony", "apple", "samsung", "xiaomi", "lenovo", "asus", "philips", "bosch", "dyson",
    "anker", "logitech", "huawei", "dell", "hp", "lg", "bose", "sennheiser", "jbl",
    "panasonic", "toshiba", "acer", "msi", "canon", "nikon"
})

# Model code aliases (e.g. ps5 <-> playstation 5)
MODEL_ALIASES: dict[str, tuple[str, ...]] = {
    "ps5": ("ps5", "playstation 5", "playstation5"),
    "ps4": ("ps4", "playstation 4", "playstation4"),
    "ps3": ("ps3", "playstation 3", "playstation3"),
}

BUNDLE_SUFFIX_PATTERN = re.compile(
    r"\b(?:"
    r"w\s+zestawie|w\s+pakiecie|w\s+komplecie|gratis|darmo|im\s+lieferumfang|im\s+set|inklusive|inkl\b|"
    r"в\s+комплекте|в\s+подарок|бесплатно|included"
    r")\b",
    re.IGNORECASE,
)
NEGATION_PREFIX = re.compile(r"(?:\b(?:без|bez|ohne|without|не)\s+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PhraseDecomposition:
    raw: str
    normalized: str
    head_candidate: str | None
    target_candidate: str | None
    is_bundle: bool
    is_accessory_head: bool
    is_inverted: bool
    is_german_kompositum: bool
    model_codes: tuple[str, ...]
    negated_accessories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuralResult:
    level: RelevanceLevel
    score: float
    reasons: tuple[str, ...]
    uncertainty_reasons: tuple[str, ...] = ()
    rejection: str | None = None
    is_uncertain: bool = False
    head: str | None = None
    target: str | None = None
    is_bundle: bool = False


def extract_model_codes(text: str) -> tuple[str, ...]:
    """Extract and normalize model tokens: 'WH-1000XM5' -> 'wh1000xm5', 'ps5', etc."""
    norm = normalize_text(text)
    found: list[str] = []
    # Check Playstation / console aliases
    for alias_pattern, canonical in (
        (r"\bplaystation\s*5\b", "ps5"),
        (r"\bplaystation\s*4\b", "ps4"),
        (r"\bplaystation\s*3\b", "ps3"),
    ):
        if re.search(alias_pattern, norm):
            found.append(canonical)

    for match in re.finditer(r"\b([a-z0-9]+(?:[-/][a-z0-9]+)+|[a-z]+\d+[a-z0-9]*|\d+[a-z]+[a-z0-9]*)\b", norm):
        val = match.group(0).replace("-", "").replace("/", "")
        if any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            if not re.fullmatch(r"\d+(?:gb|tb|mb|hz|cal|cala|cali|cm|mm|kg|g|w|v|mah|k)", val):
                found.append(val)
    return tuple(dict.fromkeys(found))


def detect_german_kompositum(word: str) -> tuple[str, str] | None:
    """Decompose German compound word A+B: Laptoptasche -> ('laptop', 'tasche')."""
    clean = normalize_text(word).replace("-", "")
    for suffix in GERMAN_KOMPOSITA_SUFFIXES:
        norm_suffix = normalize_text(suffix)
        if clean.endswith(norm_suffix) and len(clean) > len(norm_suffix) + 2:
            prefix = clean[:-len(norm_suffix)]
            return prefix, norm_suffix
    return None


def decompose_phrase(text: str) -> PhraseDecomposition:
    """Extract Head vs Target, bundle status, Komposita, and compatibility patterns."""
    raw = text.strip()
    norm = normalize_text(raw)
    model_codes = extract_model_codes(raw)

    is_bundle = False
    primary_part = norm

    b_match = BUNDLE_CONNECTOR_PATTERN.search(norm)
    s_match = BUNDLE_SUFFIX_PATTERN.search(norm)
    split_match = b_match or s_match

    if split_match:
        is_bundle = True
        prefix = norm[:split_match.start()].strip()
        words = prefix.split()
        if words and any(re.search(pat, words[-1], re.IGNORECASE) for pat in ACCESSORY_HEAD_PATTERNS.values()):
            primary_part = " ".join(words[:-1]).strip()
        else:
            primary_part = prefix

    is_german = False
    head_candidate: str | None = None
    target_candidate: str | None = None
    is_accessory_head = False
    is_inverted = False
    negated_accessories: list[str] = []

    words = primary_part.split()
    for word in words:
        decomp = detect_german_kompositum(word)
        if decomp:
            is_german = True
            is_accessory_head = True
            target_candidate = decomp[0]
            head_candidate = decomp[1]
            break

    if not head_candidate:
        prep_match = COMPATIBILITY_PREP_REGEX.search(primary_part)
        if prep_match:
            left_part = primary_part[:prep_match.start()].strip()
            right_part = primary_part[prep_match.end():].strip()

            if left_part and right_part:
                head_candidate = left_part
                target_candidate = right_part
                for pat in ACCESSORY_HEAD_PATTERNS.values():
                    for m in re.finditer(pat, head_candidate, re.IGNORECASE):
                        before = head_candidate[max(0, m.start() - 16):m.start()]
                        if NEGATION_PREFIX.search(before):
                            negated_accessories.append(m.group(0))
                        else:
                            is_accessory_head = True
            elif not left_part and right_part:
                r_words = right_part.split()
                if len(r_words) >= 2:
                    is_inverted = True
                    for split_idx in range(1, len(r_words)):
                        potential_target = " ".join(r_words[:split_idx])
                        potential_head = " ".join(r_words[split_idx:])
                        if any(re.search(pat, potential_head, re.IGNORECASE) for pat in ACCESSORY_HEAD_PATTERNS.values()):
                            head_candidate = potential_head
                            target_candidate = potential_target
                            is_accessory_head = True
                            break
                    if not head_candidate:
                        target_candidate = r_words[0]
                        head_candidate = " ".join(r_words[1:])

    if not is_accessory_head:
        for pat in ACCESSORY_HEAD_PATTERNS.values():
            for m in re.finditer(pat, primary_part, re.IGNORECASE):
                before = primary_part[max(0, m.start() - 16):m.start()]
                if NEGATION_PREFIX.search(before):
                    negated_accessories.append(m.group(0))
                else:
                    is_accessory_head = True
                    if not head_candidate:
                        head_candidate = primary_part

    return PhraseDecomposition(
        raw=raw,
        normalized=norm,
        head_candidate=head_candidate,
        target_candidate=target_candidate,
        is_bundle=is_bundle,
        is_accessory_head=is_accessory_head,
        is_inverted=is_inverted,
        is_german_kompositum=is_german,
        model_codes=model_codes,
        negated_accessories=tuple(negated_accessories),
    )


def target_matches(query_target: str, title_target: str, title_full: str) -> bool:
    """Check if the requested accessory target matches the offer across languages."""
    q_norm = normalize_text(query_target)
    t_norm = normalize_text(title_full)

    q_tokens = [w for w in q_norm.split() if len(w) >= 3]
    if not q_tokens:
        return True

    # Direct match or substring
    if any(tok in t_norm for tok in q_tokens):
        return True

    # Model codes / SKUs in target
    q_codes = extract_model_codes(query_target)
    if q_codes and any(code in t_norm for code in q_codes):
        return True

    # Cross-lingual synonyms
    for concept_family in CROSS_LINGUAL_SYNONYMS.values():
        norm_family = {normalize_text(w) for w in concept_family}
        if any(tok in norm_family or any(w.startswith(tok[:4]) for w in norm_family) for tok in q_tokens):
            if any(w in t_norm for w in norm_family):
                return True

    return False


def is_multi_model_spam(title_norm: str) -> bool:
    """Detect compatibility spam like 'do XM3 / XM4 / XM5' or 'für iPhone 12/13/14/15'."""
    slash_series = re.search(r"\b[a-z0-9]+\s*[/|,]\s*[a-z0-9]+\s*[/|,]\s*[a-z0-9]+", title_norm)
    if slash_series:
        frag = slash_series.group(0)
        digits = re.findall(r"\d+", frag)
        if len(digits) >= 3:
            return True
    return False


def evaluate_structural_relevance(
    query: str,
    title: str,
    category: str = "",
    *,
    specs: dict | None = None,
) -> StructuralResult:
    """Evaluate candidate relevance using generalized multi-domain structural rules.

    Returns StructuralResult with level in (RELEVANT, UNCERTAIN, IRRELEVANT).
    """
    q_decomp = decompose_phrase(query)
    t_decomp = decompose_phrase(title)
    q_norm = q_decomp.normalized
    t_norm = t_decomp.normalized

    # 1. Defect / Empty packaging rejection (unless user explicitly searched for it)
    if not DEFECT_EMPTY_MARKERS.search(q_norm):
        if DEFECT_EMPTY_MARKERS.search(t_norm):
            return StructuralResult(
                level="IRRELEVANT",
                score=0.0,
                reasons=(),
                rejection="defect, empty packaging or spare parts offer",
            )

    # 2. Contract / Subscription deals (e.g. mobile contract instead of device)
    if not CONTRACT_MARKERS.search(q_norm) and CONTRACT_MARKERS.search(t_norm):
        return StructuralResult(
            level="IRRELEVANT",
            score=0.0,
            reasons=(),
            rejection="contract or subscription deal instead of standalone purchase",
        )

    # 3. Multi-model spam check
    if q_decomp.model_codes and is_multi_model_spam(t_norm):
        return StructuralResult(
            level="IRRELEVANT",
            score=0.0,
            reasons=(),
            rejection="multi-model compatibility spam string",
        )

    # 4. Model generation mismatch check
    if q_decomp.model_codes:
        for q_code in q_decomp.model_codes:
            q_digits = re.findall(r"\d+", q_code)
            if q_digits:
                target_num = q_digits[-1]
                for t_code in t_decomp.model_codes:
                    t_digits = re.findall(r"\d+", t_code)
                    if t_digits and t_digits[-1] != target_num:
                        prefix_q = re.sub(r"\d+", "", q_code)
                        prefix_t = re.sub(r"\d+", "", t_code)
                        if prefix_q and prefix_q == prefix_t and q_code not in t_decomp.model_codes:
                            return StructuralResult(
                                level="IRRELEVANT",
                                score=0.0,
                                reasons=(),
                                rejection=f"model generation mismatch: requested {q_code}, found {t_code}",
                            )

    # 4b. Explicit exclusions check (e.g. "airpods без чехла", "laptop ohne tasche")
    if q_decomp.negated_accessories:
        for neg_term in q_decomp.negated_accessories:
            for pat in ACCESSORY_HEAD_PATTERNS.values():
                if re.search(pat, neg_term, re.IGNORECASE):
                    if re.search(pat, t_norm, re.IGNORECASE):
                        return StructuralResult(
                            level="IRRELEVANT",
                            score=0.0,
                            reasons=(),
                            rejection=f"offer contains explicitly excluded accessory: {neg_term}",
                        )

    query_tokens = [t for t in q_norm.split() if len(t) >= 3]
    is_generic_brand = (
        q_norm in KNOWN_BRANDS
        or (len(query_tokens) == 1 and query_tokens[0] in KNOWN_BRANDS and not q_decomp.model_codes and not q_decomp.is_accessory_head)
    )

    # 5. Intent: User searched for an ACCESSORY / CONSUMABLE / SERVICE (e.g. "сумка для ноутбука")
    if q_decomp.is_accessory_head:
        if not t_decomp.is_accessory_head:
            return StructuralResult(
                level="IRRELEVANT",
                score=0.0,
                reasons=(),
                rejection="main product instead of requested accessory/service",
            )

        if q_decomp.target_candidate:
            if not target_matches(q_decomp.target_candidate, t_decomp.target_candidate or "", t_norm):
                return StructuralResult(
                    level="IRRELEVANT",
                    score=0.0,
                    reasons=(),
                    rejection="accessory target does not match requested target",
                )

        return StructuralResult(
            level="RELEVANT",
            score=15.0,
            reasons=("requested accessory type confirmed",),
            head=t_decomp.head_candidate,
            target=t_decomp.target_candidate,
            is_bundle=t_decomp.is_bundle,
        )

    # 6. Intent: User searched for a MAIN ITEM (e.g. "ноутбук", "пицца", "кофемашина", "Sony WH-1000XM5")
    if t_decomp.is_accessory_head:
        if is_generic_brand and any(b in t_norm for b in (query_tokens or [q_norm])):
            return StructuralResult(
                level="RELEVANT",
                score=12.0,
                reasons=("generic brand match",),
                head=t_decomp.head_candidate or t_decomp.raw,
                target=t_decomp.target_candidate,
                is_bundle=t_decomp.is_bundle,
            )

        if t_decomp.is_bundle:
            primary_decomp = decompose_phrase(BUNDLE_CONNECTOR_PATTERN.split(t_norm, maxsplit=1)[0])
            if not primary_decomp.is_accessory_head:
                return StructuralResult(
                    level="RELEVANT",
                    score=14.0,
                    reasons=("bundle with main product as head",),
                    is_bundle=True,
                    head=primary_decomp.head_candidate or primary_decomp.raw,
                )

        return StructuralResult(
            level="IRRELEVANT",
            score=0.0,
            reasons=(),
            rejection="accessory, consumable, packaging, or service instead of main item",
            head=t_decomp.head_candidate,
            target=t_decomp.target_candidate,
        )

    # 7. Model code verification (if exact model requested)
    if q_decomp.model_codes:
        missing_codes = []
        for c in q_decomp.model_codes:
            aliases = MODEL_ALIASES.get(c, (c,))
            matched = any(a in t_decomp.model_codes for a in aliases) or any(a in t_norm for a in aliases)
            if not matched:
                missing_codes.append(c)
        if missing_codes:
            return StructuralResult(
                level="IRRELEVANT",
                score=0.0,
                reasons=(),
                rejection=f"missing exact model: {', '.join(missing_codes)}",
            )

    # 8. Check for UNCERTAIN candidate:
    reasons: list[str] = ["main object confirmed"]
    uncertainty_reasons: list[str] = []
    is_uncertain = False

    title_tokens = [t for t in t_norm.split() if len(t) >= 3]
    query_tokens = [t for t in q_norm.split() if len(t) >= 3]
    overlap = sum(1 for t in query_tokens if any(t in w for w in title_tokens))

    if len(title_tokens) <= 2 and overlap < len(query_tokens):
        is_uncertain = True
        uncertainty_reasons.append("brief title with unconfirmed generic terms")

    level: RelevanceLevel = "UNCERTAIN" if is_uncertain else "RELEVANT"
    score = 8.0 if is_uncertain else 12.0
    if q_decomp.model_codes:
        score += 8.0
        reasons.append("exact model match")

    return StructuralResult(
        level=level,
        score=score,
        reasons=tuple(reasons),
        uncertainty_reasons=tuple(uncertainty_reasons),
        is_uncertain=is_uncertain,
        head=t_decomp.head_candidate or t_decomp.raw,
        target=t_decomp.target_candidate,
        is_bundle=t_decomp.is_bundle,
    )
