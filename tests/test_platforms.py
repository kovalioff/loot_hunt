from loot_hunt.platforms import PLATFORMS, Platform, get_platform


def test_platforms_registered():
    assert "pl" in PLATFORMS
    assert "de" in PLATFORMS
    assert "uk" in PLATFORMS

    pl = PLATFORMS["pl"]
    de = PLATFORMS["de"]
    uk = PLATFORMS["uk"]

    assert pl.domain == "https://www.pepper.pl"
    assert de.domain == "https://www.mydealz.de"
    assert uk.domain == "https://www.hotukdeals.com"

    assert pl.currency == "zł"
    assert de.currency == "€"
    assert uk.currency == "£"


def test_platform_price_conversion_and_formatting():
    de = PLATFORMS["de"]
    uk = PLATFORMS["uk"]
    pl = PLATFORMS["pl"]

    assert pl.to_pln(100.0) == 100.0
    assert pl.format_price_with_pln(100.0) == "100 zł"

    # EUR to PLN (rate ~4.30)
    assert de.to_pln(50.0) == 215.0
    assert de.format_price(50.0) == "50 €"
    assert de.format_price_with_pln(50.0) == "50 € (~215 zł)"

    # GBP to PLN (rate ~5.15)
    assert uk.to_pln(20.0) == 103.0
    assert uk.format_price(20.0) == "20 £"
    assert uk.format_price_with_pln(20.0) == "20 £ (~103 zł)"


def test_forwarding_configuration():
    de = PLATFORMS["de"]
    assert de.forwarding_service_name == "Bodycar1.com"
    assert de.forwarding_price_pln == 46.0
    assert "bodycar1.com" in (de.forwarding_url or "")

    uk = PLATFORMS["uk"]
    assert uk.forwarding_service_name == "Meest Post"
    assert uk.forwarding_price_pln == 55.0
    assert "meestpost.com" in (uk.forwarding_url or "")

    pl = PLATFORMS["pl"]
    assert pl.forwarding_service_name is None
    assert pl.forwarding_price_pln is None


def test_get_platform_fallbacks():
    assert get_platform("pl").code == "pl"
    assert get_platform("de").code == "de"
    assert get_platform("DE").code == "de"
    assert get_platform("uk").code == "uk"
    assert get_platform("unknown").code == "pl"
    assert get_platform(None).code == "pl"
    assert isinstance(get_platform(PLATFORMS["de"]), Platform)
