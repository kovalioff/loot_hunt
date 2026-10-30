from loot_hunt.extractors.disambiguation import parse_title_entities


def test_user_example_laptop_with_rtx():
    title = "Вау крутой ноутбук с юсб си rtx 3070"
    res = parse_title_entities(title, price=3499.0, category_hint="Laptopy")
    assert res.head_class == "laptop"
    assert not res.is_accessory
    assert res.specs.get("gpu") == "RTX 3070"


def test_accessory_cable_for_laptop():
    title = "Kabel USB-C do laptopa Lenovo 100W PD"
    res = parse_title_entities(title, price=35.0, category_hint="Akcesoria")
    assert res.head_class == "accessory"
    assert res.is_accessory
    assert res.accessory_type == "kabel"
    assert res.accessory_target == "laptopa"


def test_game_for_console():
    title = "Gra Marvel's Spider-Man 2 na PS5"
    res = parse_title_entities(title, price=179.0, category_hint="Gry")
    assert res.head_class == "accessory"
    assert res.is_accessory
    assert res.accessory_type == "gra"
    assert res.accessory_target == "ps5"


def test_real_console_detected():
    title = "Konsola Sony PlayStation 5 Slim 1TB"
    res = parse_title_entities(title, price=2099.0, category_hint="Konsole")
    assert res.head_class == "console"
    assert not res.is_accessory
    assert res.specs.get("storage") == "1TB"
