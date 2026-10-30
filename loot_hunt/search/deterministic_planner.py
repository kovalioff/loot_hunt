from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from loot_hunt.platforms import Platform, get_platform

from .models import (
    CategoryScope,
    PlannedQuery,
    SearchPlan,
    SemanticConstraint,
    SortMode,
    TemporalConstraint,
)

STOP_PATTERNS = [
    r"\b(хочу|мне|нам|для меня|найди|покажи|ищу|посоветуй|где купить)\b",
    r"\b(подскажи|нужен|нужна|нужно|самый|самая|самое|самые)\b",
    r"\b(chcę|dla mnie|znajdź|znajdz|pokaż|pokaz|szukam|gdzie kupić)\b",
    r"\b(potrzebuję|poleć|najbardziej)\b",
    r"\b(i want|for me|find|find me|show me|looking for|where to buy|need|recommend|most)\b",
    r"\b(ich will|für mich|suche|finde|zeige|wo kaufen|brauche|empfehle|am meisten)\b",
    r"\b(пожалуйста|proszę|please|bitte)\b",
]

CHEAP_PATTERNS = [
    r"\b(дешев\w*|недорог\w*|бюджетн\w*|подешевле|копеечн\w*)\b",
    r"\b(tani\w*|najtańsz\w*|niedrog\w*|budżetow\w*|ekonomiczn\w*)\b",
    r"\b(cheap\w*|budget\w*|affordable|low[- ]cost|cheapest)\b",
    r"\b(günstig\w*|billig\w*|preiswert\w*|sparen)\b",
]

HOT_PATTERNS = [
    r"\b(горяч\w*|топов\w*|популярн\w*|лучш\w*|хайпов\w*)\b",
    r"\b(gorąc\w*|najlepsz\w*|popularn\w*|hity?|sztos)\b",
    r"\b(hot\w*|popular|trending|best|top[- ]rated)\b",
    r"\b(heiß\w*|beliebt\w*|beste\w*|top)\b",
]

ENTITY_ONTOLOGY: dict[str, dict[str, list[str] | str]] = {
    "pc": {
        "stems": [
            r"\b(компьютер\w*|пк|комп\b|системник\w*)",
            r"\b(komputer\w*|pc\b|stacjonarn\w*)",
            r"\b(computer\w*|desktop\w*)",
            r"\b(rechner\w*)",
        ],
        "pl": ["komputer", "pc", "komputer stacjonarny"],
        "de": ["gaming pc", "pc", "computer"],
        "en": ["gaming pc", "desktop pc"],
        "category": "electronics",
    },
    "laptop": {
        "stems": [
            r"\b(ноутбук\w*|ноут\w*|лэптоп\w*)",
            r"\b(laptop\w*|notebook\w*|ultrabook\w*)",
        ],
        "pl": ["laptop", "notebook"],
        "de": ["laptop", "notebook"],
        "en": ["laptop", "notebook"],
        "category": "electronics",
    },
    "headphones": {
        "stems": [
            r"\b(наушник\w*|уши\b|гарнитур\w*)",
            r"\b(słuchawk\w*)",
            r"\b(headphone\w*|earphone\w*|earbuds\w*)",
            r"\b(kopfhörer\w*)",
        ],
        "pl": ["słuchawki", "słuchawki bezprzewodowe"],
        "de": ["kopfhörer", "wireless kopfhörer"],
        "en": ["headphones", "wireless earbuds"],
        "category": "electronics",
    },
    "tv": {
        "stems": [
            r"\b(телевизор\w*|телик\w*|тв\b)",
            r"\b(telewizor\w*|tv\b)",
            r"\b(television\w*|tv\b)",
            r"\b(fernseher\w*)",
        ],
        "pl": ["telewizor", "tv"],
        "de": ["fernseher", "tv"],
        "en": ["smart tv", "tv"],
        "category": "electronics",
    },
    "smartphone": {
        "stems": [
            r"\b(смартфон\w*|телефон\w*|мобилк\w*)",
            r"\b(smartfon\w*|telefon\w*)",
            r"\b(smartphone\w*|phone\w*)",
            r"\b(handy\w*)",
        ],
        "pl": ["smartfon", "telefon"],
        "de": ["smartphone", "handy"],
        "en": ["smartphone"],
        "category": "electronics",
    },
    "iphone": {
        "stems": [r"\b(айфон\w*|iphone\w*)"],
        "pl": ["iphone"],
        "de": ["iphone"],
        "en": ["iphone"],
        "category": "electronics",
    },
    "console": {
        "stems": [
            r"\b(консол\w*|приставк\w*)",
            r"\b(konsol\w*)",
            r"\b(console\w*)",
        ],
        "pl": ["konsola", "playstation", "xbox"],
        "de": ["konsole", "playstation", "xbox"],
        "en": ["console", "playstation", "xbox"],
        "category": "gaming",
    },
    "ps5": {
        "stems": [r"\b(ps5|playstation\s*5)\b"],
        "pl": ["ps5", "playstation 5"],
        "de": ["ps5", "playstation 5"],
        "en": ["ps5", "playstation 5"],
        "category": "gaming",
    },
    "vacuum": {
        "stems": [
            r"\b(пылесос\w*|робот-пылесос\w*)",
            r"\b(odkurzacz\w*)",
            r"\b(vacuum\w*)",
            r"\b(staubsauger\w*)",
        ],
        "pl": ["odkurzacz", "odkurzacz pionowy"],
        "de": ["staubsauger", "saugroboter"],
        "en": ["vacuum cleaner", "robot vacuum"],
        "category": "home",
    },
    "lego": {
        "stems": [r"\b(лего\b|lego\b)"],
        "pl": ["lego"],
        "de": ["lego"],
        "en": ["lego"],
        "category": "family",
    },
}


class DeterministicSearchPlanner:
    def __init__(self, platform: Platform | str = "pl") -> None:
        self.platform = get_platform(platform)

    def plan(self, raw_text: str, platform: Platform | str | None = None) -> SearchPlan:
        target = get_platform(platform) if platform else self.platform
        text = raw_text.strip()

        # 1. Detect sort mode
        sort_mode: SortMode = "fresh"
        for pattern in CHEAP_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                sort_mode = "cheap"
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
                break

        if sort_mode == "fresh":
            for pattern in HOT_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    sort_mode = "hot"
                    text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
                    break

        # 2. Extract numeric price bounds
        min_price: float | None = None
        max_price: float | None = None

        max_match = re.search(
            r"(?:до|do|under|below|bis|<|<=)\s*(\d+(?:[.,]\d+)?)\s*(?:zł|pln|eur|€|usd|\$|gbp|£)?",
            text,
            re.IGNORECASE,
        )
        if max_match:
            try:
                max_price = float(max_match.group(1).replace(",", "."))
                text = text[: max_match.start()] + text[max_match.end() :]
            except ValueError:
                pass

        min_match = re.search(
            r"(?:от|od|from|over|above|ab|>|>=)\s*(\d+(?:[.,]\d+)?)\s*(?:zł|pln|eur|€|usd|\$|gbp|£)?",
            text,
            re.IGNORECASE,
        )
        if min_match:
            try:
                min_price = float(min_match.group(1).replace(",", "."))
                text = text[: min_match.start()] + text[min_match.end() :]
            except ValueError:
                pass

        # 3. Extract temporal filters
        temporal: TemporalConstraint | None = None
        now = datetime.now(tz=UTC)
        if re.search(r"\b(сегодня|dzisiaj|today|heute)\b", text, re.IGNORECASE):
            temporal = TemporalConstraint(
                required=True,
                start_date=now.date(),
                end_date=now.date(),
                description="today",
            )
            text = re.sub(r"\b(сегодня|dzisiaj|today|heute)\b", "", text, flags=re.IGNORECASE)
        elif re.search(
            r"\b(со вчера(?:шнего)?(?: дня)?|od wczoraj|since yesterday|gestern)\b",
            text,
            re.IGNORECASE,
        ):
            yesterday = (now - timedelta(days=1)).date()
            temporal = TemporalConstraint(
                required=True,
                start_date=yesterday,
                end_date=now.date(),
                description="since yesterday",
            )
            text = re.sub(
                r"\b(со вчера(?:шнего)?(?: дня)?|od wczoraj|since yesterday|gestern)\b",
                "",
                text,
                flags=re.IGNORECASE,
            )
        elif re.search(
            r"\b(за неделю|z tego tygodnia|this week|diese woche)\b", text, re.IGNORECASE
        ):
            week_ago = (now - timedelta(days=7)).date()
            temporal = TemporalConstraint(
                required=True,
                start_date=week_ago,
                end_date=now.date(),
                description="this week",
            )
            text = re.sub(
                r"\b(за неделю|z tego tygodnia|this week|diese woche)\b",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # 4. Strip conversational stopwords
        for pattern in STOP_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

        cleaned = re.sub(r"\s+", " ", text).strip(" ,.-!?")

        # 5. Entity & Ontology Mapping
        matched_concept: str | None = None
        target_category: CategoryScope | None = None
        queries: list[PlannedQuery] = []

        for concept_name, config in ENTITY_ONTOLOGY.items():
            stems = config.get("stems", [])
            for stem_pattern in stems:
                if re.search(stem_pattern, cleaned, re.IGNORECASE):
                    matched_concept = concept_name
                    cat_val = config.get("category")
                    if isinstance(cat_val, str):
                        target_category = cat_val  # type: ignore[assignment]

                    remainder = re.sub(stem_pattern, "", cleaned, flags=re.IGNORECASE).strip()
                    remainder = re.sub(r"\s+", " ", remainder).strip()

                    target_terms = config.get(target.code) or config.get("pl", [])
                    if isinstance(target_terms, list):
                        if remainder:
                            for term in target_terms[:2]:
                                queries.append(
                                    PlannedQuery(
                                        query=f"{term} {remainder}".strip(),
                                        category=target_category,
                                    )
                                )
                        else:
                            for term in target_terms:
                                queries.append(
                                    PlannedQuery(query=term, category=target_category)
                                )
                    break
            if matched_concept:
                break

        # Fallback if no specific entity ontology matched
        if not queries:
            query_str = cleaned if cleaned else raw_text.strip()
            queries.append(PlannedQuery(query=query_str, category=None))

        # Check for exact SKU or hardware model
        is_exact = bool(
            re.search(
                r"\b(rtx|gtx|rx|i[3579]-|ryzen|iphone\s*\d+|ps[45]|m[1234])\b",
                raw_text,
                re.IGNORECASE,
            )
        )
        intent = "exact" if is_exact else ("broad" if matched_concept else "search")

        hard_constraints: list[SemanticConstraint] = []
        if max_price is not None:
            hard_constraints.append(
                SemanticConstraint(name=f"max_price_{int(max_price)}", evidence_terms=[])
            )

        return SearchPlan(
            original_query=raw_text,
            intent=intent,
            platform=target.code,
            sort_mode=sort_mode,
            min_price=min_price,
            max_price=max_price,
            temporal=temporal,
            hard_constraints=hard_constraints,
            queries=queries,
        )
