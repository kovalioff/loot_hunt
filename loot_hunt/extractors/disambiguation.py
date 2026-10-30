from __future__ import annotations

import re

from .models import ParsedEntity

ACCESSORY_HEADS = {
    "kabel", "przewód", "cable", "кабель", "провод",
    "etui", "case", "pokrowiec", "hülle", "tasche", "чехол", "футляр",
    "torba", "plecak", "bag", "backpack", "рюкзак", "сумка",
    "ładowarka", "charger", "netzteil", "зарядка", "зарядное", "блок питания",
    "podstawka", "stand", "holder", "halterung", "подставка", "держатель",
    "uchwyt", "mount", "stojak",
    "szkło", "folia", "glass", "screen protector", "защитное стекло", "пленка",
    "pasek", "strap", "band", "armband", "ремешок",
    "hub", "dock", "adapter", "przejściówka", "хаб", "адаптер", "переходник",
    "gra", "game", "spiel", "игра", "płytka",
    "wentylator", "cooler", "chłodzenie", "кулер",
}

ACCESSORY_PREPOSITIONS = {
    "do", "na", "pod", "dla", "for", "für", "to", "для", "под", "на", "к"
}

ATTRIBUTE_PREPOSITIONS = {
    "z", "ze", "with", "mit", "с", "со", "plus", "+", "wraz z"
}

SPEC_PATTERNS = {
    "gpu": r"\b(rtx\s*\d{4}(?:\s*ti|\s*super)?|gtx\s*\d{4}|rx\s*\d{4}(?:\s*xt)?)\b",
    "cpu": (
        r"\b(i[3579]-\d{4,5}[a-z]*|ryzen\s*[3579]\s*\d{4}[a-z]*|apple\s*m[1234](?:\s*pro|\s*max)?)\b"
    ),
    "ram": r"\b(\d{1,3}\s*gb\s*(?:ram|ddr[45])?)\b",
    "storage": r"\b(\d{1,2}\s*tb|\d{3,4}\s*gb)\s*(?:ssd|nvme|m\.2|dysk|hdd)?\b",
    "port": r"\b(usb[- ]?c|thunderbolt\s*[34]|hdmi\s*2\.[01])\b",
    "screen_hz": r"\b(\d{2,3}\s*hz)\b",
}


def parse_title_entities(
    title: str,
    price: float | None = None,
    category_hint: str | None = None,
) -> ParsedEntity:
    lower_title = title.lower()
    words = re.findall(r"[\w-]+", lower_title)

    # 1. Detect accessory pattern: [AccessoryHead] ... [Preposition: do/for/na] ... [Target]
    is_acc = False
    acc_type = None
    acc_target = None
    explanation = []

    for idx, word in enumerate(words):
        if word in ACCESSORY_HEADS:
            for next_idx in range(idx + 1, min(idx + 6, len(words))):
                prep = words[next_idx]
                if prep in ACCESSORY_PREPOSITIONS and next_idx + 1 < len(words):
                    target_candidate = words[next_idx + 1]
                    is_acc = True
                    acc_type = word
                    acc_target = target_candidate
                    explanation.append(
                        f"Detected accessory pattern: '{word}' + '{prep}' + '{target_candidate}'"
                    )
                    break
        if is_acc:
            break

    # 2. Extract specs (GPU, CPU, RAM, Storage, Port, Hz)
    found_specs: dict[str, str] = {}
    for spec_name, pattern in SPEC_PATTERNS.items():
        match = re.search(pattern, lower_title, re.IGNORECASE)
        if match:
            found_specs[spec_name] = match.group(1).upper().strip()

    # 3. Head class determination
    if is_acc:
        head_class = "accessory"
        explanation.append(
            f"Classified as accessory '{acc_type}' FOR '{acc_target}'. Not the main device!"
        )
    else:
        has_laptop = bool(
            re.search(r"\b(laptop|notebook|ноутбук|laptopy|ultrabook|macbook)\b", lower_title)
        )
        has_gpu = bool(
            re.search(r"\b(karta graficzna|graphics card|grafikkarte|видеокарта)\b", lower_title)
        )
        has_console = bool(
            re.search(r"\b(konsola|playstation|ps[45]|xbox|nintendo)\b", lower_title)
        )
        has_phone = bool(
            re.search(
                r"\b(smartfon|smartphone|telefon|phone|телефон|смартфон|iphone|pixel|galaxy)\b",
                lower_title,
            )
        )

        if has_laptop:
            head_class = "laptop"
            explanation.append("Matched explicit laptop keywords as head product.")
            if "gpu" in found_specs:
                explanation.append(
                    f"GPU '{found_specs['gpu']}' is an internal spec of the laptop."
                )
        elif has_phone:
            head_class = "smartphone"
            explanation.append("Matched explicit smartphone/phone keywords as head product.")
        elif has_gpu:
            head_class = "gpu"
            explanation.append("Matched explicit GPU/graphics card keywords.")
        elif has_console:
            head_class = "console"
            explanation.append("Matched console keywords.")
        elif "gpu" in found_specs and not has_laptop:
            if price is not None and price < 200.0:
                head_class = "accessory"
                explanation.append(f"Price {price} is too low for GPU or Laptop; accessory likely.")
            else:
                head_class = "gpu"
                explanation.append("Standalone GPU model detected without laptop wrapper.")
        else:
            head_class = "other"
            explanation.append("No specialized hardware class matched.")

    # 4. Category hint validation from Pepper
    if category_hint:
        hint_lower = category_hint.lower()
        if "laptop" in hint_lower and head_class != "accessory":
            head_class = "laptop"
            explanation.append(f"Confirmed by Pepper category hint '{category_hint}'.")
        elif "karty graficzne" in hint_lower and head_class != "accessory":
            head_class = "gpu"
            explanation.append(f"Confirmed by Pepper category hint '{category_hint}'.")

    return ParsedEntity(
        raw_title=title,
        price=price,
        head_class=head_class,
        is_accessory=is_acc,
        accessory_type=acc_type,
        accessory_target=acc_target,
        specs=found_specs,
        explanation=" | ".join(explanation),
    )
