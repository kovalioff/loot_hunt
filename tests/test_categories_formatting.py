from datetime import UTC, datetime

from loot_hunt.pepper.categories import categories_from_state, flatten
from loot_hunt.pepper.models import Offer
from loot_hunt.telegram.formatting import offer_card
from loot_hunt.telegram.keyboards import result_keyboard


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


def test_html_escaping_and_conditional_card():
    offer = Offer(
        "1",
        "A < B",
        current_price=10,
        old_price=20,
        discount=50,
        coupon_code="X<Y",
        published_at=datetime.now(UTC),
    )
    card = offer_card(offer, "Europe/Warsaw")
    assert "A &lt; B" in card and "X&lt;Y" in card and "<s>20 zł</s>" in card


def test_callback_data_is_compact_and_direct_button_conditional():
    offers = [Offer("1", "X", merchant_url="https://shop.example/x")]
    keyboard = result_keyboard("abc123", offers, 0, 6)
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert callbacks and all(len(value.encode()) <= 64 for value in callbacks)
    assert keyboard.inline_keyboard[0][0].url == "https://shop.example/x"
