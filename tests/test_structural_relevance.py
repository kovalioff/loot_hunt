import pytest
from loot_hunt.search.structural_relevance import evaluate_structural_relevance


def test_electronics_main_vs_accessory():
    # Searching for laptop: rejects accessories (RU/PL/DE)
    r1 = evaluate_structural_relevance("ноутбук", "Torba na laptopa 15.6")
    assert r1.level == "IRRELEVANT"
    assert "accessory" in (r1.rejection or "")

    r2 = evaluate_structural_relevance("ноутбук", "Podstawka pod laptopa regulowana")
    assert r2.level == "IRRELEVANT"

    r3 = evaluate_structural_relevance("ноутбук", "Laptoptasche Dell 15.6 Zoll")
    assert r3.level == "IRRELEVANT"

    r4 = evaluate_structural_relevance("ноутбук", "Notebookständer ergonomisch")
    assert r4.level == "IRRELEVANT"

    # Confirms laptop
    r5 = evaluate_structural_relevance("ноутбук", "Laptop Lenovo IdeaPad 16GB 512GB")
    assert r5.level == "RELEVANT"


def test_headphones_sony_wh1000xm5():
    q = "наушники Sony WH-1000XM5"
    # Rejects accessories
    assert evaluate_structural_relevance(q, "Ładowarka do Sony WH-1000XM5").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q, "Ersatz-Ohrpolster für WH-1000XM5").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q, "Etui do XM3 / XM4 / XM5").level == "IRRELEVANT"

    # Rejects generation substitution
    r_gen = evaluate_structural_relevance(q, "Słuchawki Sony WH-1000XM4 ANC")
    assert r_gen.level == "IRRELEVANT"
    assert "mismatch" in (r_gen.rejection or "")

    # Confirms headphones
    r_ok = evaluate_structural_relevance(q, "Słuchawki Sony WH-1000XM5 ANC bezprzewodowe")
    assert r_ok.level == "RELEVANT"


def test_food_and_restaurants():
    # Searching for pizza
    q_pizza = "пицца"
    assert evaluate_structural_relevance(q_pizza, "Pudełko na pizzę 32cm").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_pizza, "Pizzakarton 100 sztuk").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_pizza, "Gewürz für Pizza 50g").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_pizza, "Pizza Margherita 32cm").level == "RELEVANT"

    # Searching for coffee machine
    q_coffee = "кофемашина"
    assert evaluate_structural_relevance(q_coffee, "Entkalker für Kaffeemaschine DeLonghi").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_coffee, "Капсулы для кофемашины Nespresso 100 шт").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_coffee, "Ekspres ciśnieniowy DeLonghi Magnifica S").level == "RELEVANT"


def test_travel_and_tours():
    q_tour = "тур в Турцию"
    assert evaluate_structural_relevance(q_tour, "Reiseversicherung für Türkei-Reise").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_tour, "Страховка для тура в Турцию").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_tour, "Турция, Анталья 7 ночей в отеле 5*").level == "RELEVANT"

    q_suitcase = "чемодан"
    assert evaluate_structural_relevance(q_suitcase, "Pokrowiec na walizkę rozmiar L").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_suitcase, "Schutzhülle für Koffer").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_suitcase, "Walizka kabinowa Samsonite").level == "RELEVANT"


def test_apparel_home_auto():
    q_sofa = "диван"
    assert evaluate_structural_relevance(q_sofa, "Pokrowiec na kanapę welur").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_sofa, "Чехол на диван трикотажный").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_sofa, "Kanapa rozkładana 3-osobowa").level == "RELEVANT"

    q_shoes = "кроссовки"
    assert evaluate_structural_relevance(q_shoes, "Шнурки для кроссовок 120см").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_shoes, "Prawidła do butów drewniane").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_shoes, "Schuhspanner aus Buchenholz").level == "IRRELEVANT"
    assert evaluate_structural_relevance(q_shoes, "Buty Nike Air Max").level == "RELEVANT"


def test_bundles_preserve_relevance():
    # Main item followed by bonus/gift/bundle connector is RELEVANT
    assert evaluate_structural_relevance("ноутбук", "Laptop Dell + torba i mysz gratis").level == "RELEVANT"
    assert evaluate_structural_relevance("Sony WH-1000XM5", "Sony WH-1000XM5 inkl. Tasche und Ladekabel").level == "RELEVANT"
    assert evaluate_structural_relevance("кофемашина", "Кофемашина DeLonghi + капсулы в подарок").level == "RELEVANT"
    assert evaluate_structural_relevance("тур в Анталью", "Тур в Анталью 7 ночей + трансфер и страховка в комплекте").level == "RELEVANT"


def test_explicit_accessory_queries():
    # User looking for accessory wants the accessory, NOT the device
    q_bag = "сумка для ноутбука"
    assert evaluate_structural_relevance(q_bag, "Torba na laptopa 15.6 cali").level == "RELEVANT"
    assert evaluate_structural_relevance(q_bag, "Laptoptasche Dell").level == "RELEVANT"
    assert evaluate_structural_relevance(q_bag, "Laptop Lenovo IdeaPad 16").level == "IRRELEVANT"

    q_capsules = "капсулы для кофемашины"
    assert evaluate_structural_relevance(q_capsules, "Kapsułki do ekspresu Nespresso").level == "RELEVANT"
    assert evaluate_structural_relevance(q_capsules, "Ekspres ciśnieniowy DeLonghi").level == "IRRELEVANT"


def test_defects_and_empty_boxes_rejected():
    assert evaluate_structural_relevance("ноутбук", "Laptop Lenovo na części / uszkodzony").level == "IRRELEVANT"
    assert evaluate_structural_relevance("iPhone 15", "iPhone 15 samo pudełko / nur OVP").level == "IRRELEVANT"
    assert evaluate_structural_relevance("Sony WH-1000XM5", "Sony WH-1000XM5 tylko кейс без наушников").level == "IRRELEVANT"


def test_uncertain_candidates():
    # Candidate lacks explicit head noun, but matches model/brand
    r = evaluate_structural_relevance("ноутбук", "Lenovo IdeaPad 15ALC05")
    # Should not be deleted, but marked UNCERTAIN
    assert r.level in ("UNCERTAIN", "RELEVANT")
