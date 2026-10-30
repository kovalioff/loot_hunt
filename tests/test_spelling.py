import pytest
from loot_hunt.search.spelling import correct_query, is_hardware_or_model_code


def test_keyboard_layout_correction():
    res1 = correct_query("yjen,er")
    assert res1.was_corrected is True
    assert res1.effective_query == "ноутбук"

    res2 = correct_query("gbwwf")
    assert res2.was_corrected is True
    assert res2.effective_query == "пицца"

    res3 = correct_query("neh d nehwbf")
    assert res3.was_corrected is True
    assert res3.effective_query in ("тур в турция", "тур в турцию", "тур в турции")

    res4 = correct_query("шзрщту")
    assert res4.was_corrected is True
    assert res4.effective_query == "iphone"


def test_orthography_and_double_consonants():
    assert correct_query("пица").effective_query == "пицца"
    assert correct_query("кросовки").effective_query == "кроссовки"
    assert correct_query("каппучино").effective_query == "капучино"


def test_brand_transliterations():
    assert correct_query("айфон").effective_query == "iphone"
    assert correct_query("макбук").effective_query == "macbook"
    assert correct_query("сяоми").effective_query == "xiaomi"
    assert correct_query("сони").effective_query == "sony"
    assert correct_query("делонги").effective_query == "delonghi"


def test_fuzzy_typos():
    assert correct_query("нотубук").effective_query == "ноутбук"
    assert correct_query("пуетвка").effective_query == "путевка"
    assert correct_query("наушинки").effective_query == "наушники"
    assert correct_query("рестраны").effective_query == "рестораны"


def test_model_code_immunity():
    # Alphanumeric codes and hardware specs must NEVER be altered
    assert is_hardware_or_model_code("WH-1000XM5") is True
    assert is_hardware_or_model_code("DDR5") is True
    assert is_hardware_or_model_code("RTX4060") is True
    assert is_hardware_or_model_code("PS5") is True

    res = correct_query("Sony WH-1000XM5")
    assert "WH-1000XM5" in res.effective_query
    assert "WH-1000XM4" not in res.effective_query

    res_ddr = correct_query("память DDR5")
    assert "DDR5" in res_ddr.effective_query
