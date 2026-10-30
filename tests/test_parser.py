import json

from loot_hunt.pepper.parser import detail_from_page, listing_threads, normalize_offer


def test_listing_vue_and_full_normalization():
    raw = {
        "threadId": 123,
        "title": "OLED &amp; TV",
        "price": {"amount": "3999,00"},
        "nextBestPrice": 4999,
        "temperature": 427,
        "merchant": {"name": "Media Expert"},
        "merchantUrl": "https://shop.example/deal?aff=kept",
        "voucherCode": "LATO150",
        "publishedAt": "2026-08-18T12:30:00Z",
        "category": {"name": "Elektronika"},
        "url": "/promocje/oled-123",
        "isExpired": False,
    }
    payload = {"name": "ThreadMainListItemNormalizer", "props": {"thread": raw}}
    page = f"<div data-vue3='{json.dumps(payload, separators=(',', ':'))}'></div>"
    parsed = listing_threads(page)
    offer = normalize_offer(parsed[0])
    assert offer and offer.thread_id == "123"
    assert offer.title == "OLED & TV"
    assert offer.current_price == 3999
    assert offer.old_price == 4999
    assert offer.discount == 20
    assert offer.temperature == 427
    assert offer.merchant == "Media Expert"
    assert offer.merchant_url == "https://shop.example/deal?aff=kept"
    assert offer.coupon_code == "LATO150"
    assert offer.category == "Elektronika"


def test_expired_no_price_and_bad_discount_are_safe():
    offer = normalize_offer(
        {"threadId": "7", "title": "Za darmo", "price": "free", "discount": 999, "isExpired": True}
    )
    assert offer and offer.current_price is None and offer.discount is None and offer.is_expired


def test_zero_price_voucher_is_treated_as_no_price():
    offer = normalize_offer({"threadId": "8", "title": "40% voucher", "price": 0, "percentage": 40})
    assert offer and offer.current_price is None and offer.discount == 40


def test_detail_initial_state():
    raw = {"threadId": 9, "title": "Travel", "dealUrl": "https://travel.example/a"}
    page = "<script>window.__INITIAL_STATE__ = " + json.dumps({"threadDetail": raw}) + ";</script>"
    offer = detail_from_page(page, "https://www.pepper.pl/promocje/travel-9")
    assert offer and offer.merchant_url == "https://travel.example/a"


def test_pepper_url_is_never_used_as_merchant_url():
    offer = normalize_offer(
        {"threadId": 1, "title": "X", "dealUrl": "https://www.pepper.pl/share-deal/1"}
    )
    assert offer and offer.merchant_url is None


def test_structured_pepper_visit_url_is_accepted_for_resolution():
    offer = normalize_offer(
        {
            "threadId": 1,
            "title": "X",
            "linkCloakedItemMainButton": "https://www.pepper.pl/visit/threadmain/1",
        }
    )
    assert offer and offer.merchant_url == "https://www.pepper.pl/visit/threadmain/1"


def test_pepper_image_metadata_becomes_safe_regional_cdn_url():
    raw = {"threadId": 1, "title": "Sony", "mainImage": {"path": "threads/raw/AbC12", "name": "123_1"}}
    assert normalize_offer(raw).image_url == "https://static.pepper.pl/threads/raw/AbC12/123_1/123_1.jpg"
    assert normalize_offer(raw, platform_code="de").image_url == "https://static.mydealz.de/threads/raw/AbC12/123_1/123_1.jpg"
    raw["mainImage"]["path"] = "threads/raw/../../private"
    assert normalize_offer(raw).image_url is None


def test_shipping_is_unknown_unless_free_or_positive_price_is_explicit():
    raw = {"threadId": 1, "title": "X", "shipping": {"isFree": None, "price": 0}}
    assert normalize_offer(raw).shipping_price is None
    raw["shipping"] = {"isFree": 1, "price": 0}
    assert normalize_offer(raw).shipping_price == 0
    assert normalize_offer(raw).shipping_free is True
    raw["shipping"] = {"isFree": 0, "price": 19}
    assert normalize_offer(raw).shipping_price == 19
