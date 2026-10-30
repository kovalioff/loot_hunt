from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from loot_hunt.database import Database
from loot_hunt.pepper.models import Offer
from loot_hunt.platforms import PLATFORMS
from loot_hunt.telegram.formatting import offer_card
from loot_hunt.telegram.handlers import TelegramHandlers
from loot_hunt.telegram.keyboards import region_keyboard, result_keyboard


def test_offer_card_german_deal_with_forwarding_estimate():
    offer = Offer(
        thread_id="101",
        title="Bose QuietComfort Headphones",
        current_price=199.0,
        old_price=349.0,
        discount=43,
        temperature=450,
        merchant="Amazon DE",
        merchant_url="https://www.amazon.de/dp/B0CCZ26B5V",
        published_at=datetime.now(UTC),
        currency="€",
        country="DE",
        platform_code="de",
        price_pln=855.70,
        forwarding_service=PLATFORMS["de"].forwarding_service_name,
        forwarding_price_pln=PLATFORMS["de"].forwarding_price_pln,
        forwarding_url=PLATFORMS["de"].forwarding_url,
    )
    card = offer_card(offer, "Europe/Warsaw")

    # Flag and country
    assert "🇩🇪" in card
    assert "Niemcy (Mydealz.de)" in card

    # Original price and converted PLN price
    assert "199 €" in card
    assert "~855.70 zł" in card

    # Forwarding delivery information
    assert "Доставка в Польшу" in card
    assert "~46 zł" in card
    assert 'href="https://bodycar1.com/"' in card
    assert "Bodycar1.com" in card

    # Affiliate link injected for Amazon DE
    assert "tag=loothunt-de-21" in card


def test_offer_card_uk_deal_with_forwarding_estimate():
    offer = Offer(
        thread_id="102",
        title="Barbour Wax Jacket",
        current_price=120.0,
        old_price=240.0,
        discount=50,
        temperature=320,
        merchant="End Clothing UK",
        merchant_url="https://www.endclothing.com/gb/barbour-jacket.html",
        published_at=datetime.now(UTC),
        currency="£",
        country="GB",
        platform_code="uk",
        price_pln=618.0,
        forwarding_service=PLATFORMS["uk"].forwarding_service_name,
        forwarding_price_pln=PLATFORMS["uk"].forwarding_price_pln,
        forwarding_url=PLATFORMS["uk"].forwarding_url,
    )
    card = offer_card(offer, "Europe/Warsaw")

    assert "🇬🇧" in card
    assert "UK (HotUKDeals.com)" in card
    assert "120 £" in card
    assert "~618 zł" in card
    assert "Meest Post" in card
    assert "~55 zł" in card
    assert 'href="https://www.meestpost.com/"' in card


def test_result_keyboard_includes_forwarding_button_for_foreign_deals():
    de_offer = Offer(
        thread_id="1",
        title="DE Deal",
        country="DE",
        platform_code="de",
        forwarding_service="Bodycar1.com",
        forwarding_price_pln=46.0,
        forwarding_url="https://bodycar1.com/",
    )
    keyboard = result_keyboard("session123", [de_offer], 0, 1)
    buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    delivery_btn = next((b for b in buttons if b.url == "https://bodycar1.com/"), None)

    assert delivery_btn is not None
    assert "Bodycar1.com" in delivery_btn.text
    assert "~46 zł" in delivery_btn.text
    assert "🇩🇪" in delivery_btn.text


def test_region_keyboard_markup():
    keyboard = region_keyboard("de")
    buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]

    assert any("🇵🇱" in t and "Pepper.pl" in t for t in texts)
    assert any("🇩🇪" in t and "Mydealz.de" in t and "✅" in t for t in texts)
    assert any("🇬🇧" in t and "HotUKDeals.com" in t for t in texts)


async def test_database_user_platform_preferences(tmp_path):
    db = Database(tmp_path / "test_prefs.db")
    await db.connect()
    try:
        # Default is pl
        assert await db.get_user_platform(12345) == "pl"

        # Update to Germany
        await db.set_user_platform(12345, "de")
        assert await db.get_user_platform(12345) == "de"

        # Update to UK
        await db.set_user_platform(12345, "uk")
        assert await db.get_user_platform(12345) == "uk"
    finally:
        await db.close()


async def test_handlers_region_command_and_callback():
    database = SimpleNamespace(
        get_user_platform=AsyncMock(return_value="pl"),
        set_user_platform=AsyncMock(),
    )
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    handlers = TelegramHandlers(settings, database, None, None)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    await handlers.region_command(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "Текущий регион поиска" in args[0]
    assert kwargs.get("reply_markup") is not None

    callback = SimpleNamespace(
        data="reg:de",
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_reply_markup=AsyncMock()),
    )
    await handlers.set_region(callback)

    database.set_user_platform.assert_awaited_once_with(100, "de")
    callback.answer.assert_awaited_once()
    callback.message.edit_reply_markup.assert_awaited_once()
