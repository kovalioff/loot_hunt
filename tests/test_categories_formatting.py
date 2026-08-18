from datetime import UTC, datetime

from loot_hunt.pepper.categories import categories_from_state, flatten
from loot_hunt.pepper.models import Offer
from loot_hunt.telegram.formatting import offer_card
from loot_hunt.telegram.keyboards import main_menu, notification_keyboard, result_keyboard


def test_arbitrary_depth_categories():
    state = {
        "nav": [
            {
                "id": 1,
                "name": "A",
                "url": "/grupa/a",
                "children": [
                    {
                        "id": 2,
                        "name": "B",
                        "url": "/grupa/b",
                        "children": [{"id": 3, "name": "C", "url": "/grupa/c"}],
                    }
                ],
            }
        ]
    }
    roots = categories_from_state(state)
    assert set(flatten(roots)) == {"1", "2", "3"}


def test_main_menu_has_discovery_subscriptions_help_and_no_tracking_section():
    texts = [button.text for row in main_menu().keyboard for button in row]
    assert texts == ["🔎 Найти предложения", "📋 Мои подписки", "❓ Помощь"]
    assert "🔔 Отслеживание" not in texts
    admin = [button.text for row in main_menu(admin=True).keyboard for button in row]
    assert "📊 Статистика" in admin


def test_clickable_merchant_and_html_are_safely_escaped():
    offer = Offer(
        "1",
        "A < B",
        current_price=10,
        old_price=20,
        discount=50,
        merchant="A&B <shop>",
        merchant_url='https://shop.example/x?a=1&b="2"',
        coupon_code="X<Y",
        published_at=datetime.now(UTC),
    )
    card = offer_card(offer, "Europe/Warsaw")
    assert "A &lt; B" in card and "X&lt;Y" in card and "<s>20 zł</s>" in card
    assert 'href="https://shop.example/x?a=1&amp;b=&quot;2&quot;"' in card
    assert ">A&amp;B &lt;shop&gt;</a>" in card


def test_missing_merchant_url_is_plain_and_missing_name_gets_safe_link():
    plain = offer_card(Offer("1", "X", merchant="Amazon.pl"), "Europe/Warsaw")
    generic = offer_card(Offer("2", "Y", merchant_url="https://shop.example/deal"), "Europe/Warsaw")
    assert "🏪 Amazon.pl" in plain and "<a " not in plain
    assert ">Открыть в магазине</a>" in generic


def test_pepper_url_is_never_a_merchant_fallback():
    card = offer_card(
        Offer(
            "1",
            "X",
            merchant="Store",
            merchant_url="https://www.pepper.pl/promocje/x",
            pepper_url="https://www.pepper.pl/promocje/x",
        ),
        "Europe/Warsaw",
    )
    assert "🏪 Store" in card and "<a " not in card


def test_result_and_notification_keyboards_have_no_offer_links():
    offers = [Offer("1", "X", merchant_url="https://shop.example/x")]
    keyboard = result_keyboard("abc123", offers, 0, 6)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert all(button.url is None for button in buttons)
    assert any(button.text == "🔔 Отслеживать этот поиск" for button in buttons)
    assert any(button.text == "➡️ Ещё" for button in buttons)
    notification = notification_keyboard(7)
    notification_buttons = [button for row in notification.inline_keyboard for button in row]
    assert all(button.url is None for button in notification_buttons)
    assert [button.text for button in notification_buttons] == ["🔕 Отключить отслеживание"]
