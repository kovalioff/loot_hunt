import time
import pytest
from loot_hunt.search.suggest import get_suggestions, engine


def test_prefix_suggestions():
    # User types 'ноут' -> suggests laptop queries
    results = get_suggestions("ноут")
    texts = [r["text"] for r in results]
    assert any("ноутбук" in t for t in texts)
    assert any("ноутбук игровой" in t for t in texts)

    # User types 'пиц' -> suggests pizza
    p_res = get_suggestions("пиц")
    p_texts = [r["text"] for r in p_res]
    assert any("пицца" in t for t in p_texts)

    # User types 'тур' -> suggests tours
    t_res = get_suggestions("тур")
    t_texts = [r["text"] for r in t_res]
    assert any("туры в Турцию" in t for t in t_texts)


def test_next_word_prediction():
    # When user enters a word with a space: 'сумка для '
    results = get_suggestions("сумка для ")
    texts = [r["text"] for r in results]
    assert "сумка для ноутбука" in texts
    assert "сумка для ручной клади" in texts

    # 'тур в ' -> suggests 'туры в Турцию', 'тур в Анталью 7 ночей'
    t_res = get_suggestions("тур в ")
    t_texts = [r["text"] for r in t_res]
    assert any("Турцию" in t or "Анталью" in t for t in t_texts)

    # 'кофе в ' -> 'кофе в зернах'
    c_res = get_suggestions("кофе в ")
    c_texts = [r["text"] for r in c_res]
    assert "кофе в зернах" in c_texts


def test_typo_and_layout_recovery_suggestions():
    # Mistyped keyboard layout: 'yjen' (QWERTY for 'ноут')
    results = get_suggestions("yjen")
    texts = [r["text"] for r in results]
    assert any("ноутбук" in t for t in texts)

    # Single-letter typo: 'нотуб' -> suggests 'ноутбук'
    typo_res = get_suggestions("нотуб")
    typo_texts = [r["text"] for r in typo_res]
    assert any("ноутбук" in t for t in typo_texts)


def test_latency_is_under_30ms():
    queries = ["ноут", "сумка для ", "пиц", "тур", "yjen", "кофе в ", "airpods"]
    for q in queries:
        t0 = time.perf_counter()
        res = get_suggestions(q)
        duration_ms = (time.perf_counter() - t0) * 1000
        assert duration_ms < 30.0, f"Query '{q}' took {duration_ms:.2f}ms (must be < 30ms)"
        assert isinstance(res, list)
