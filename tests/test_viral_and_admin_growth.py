from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from loot_hunt.channel import ChannelPublisher
from loot_hunt.database import Database
from loot_hunt.pepper.models import Offer
from loot_hunt.telegram.handlers import TelegramHandlers


async def test_referral_tracking_and_subscription_limits(tmp_path):
    db = Database(tmp_path / "test_ref.db")
    await db.connect()
    try:
        alice = 1001
        bob = 2002
        charlie = 3003
        dave = 4004

        # Baseline: 3 slots
        assert await db.get_subscription_limit(alice) == 3
        assert await db.get_referral_count(alice) == 0

        # Cannot refer oneself
        assert await db.record_referral(alice, alice) is False

        # Bob joins via Alice
        assert await db.record_referral(alice, bob) is True
        # Bob cannot be referred a second time
        assert await db.record_referral(alice, bob) is False

        # Alice now has 1 referral -> 3 + 2 = 5 slots
        assert await db.get_referral_count(alice) == 1
        assert await db.get_subscription_limit(alice) == 5

        # Charlie joins via Alice -> 5 + 2 = 7 slots
        assert await db.record_referral(alice, charlie) is True
        assert await db.get_subscription_limit(alice) == 7

        # Dave joins via Alice -> 3 referrals -> unlimited (50 slots)
        assert await db.record_referral(alice, dave) is True
        assert await db.get_referral_count(alice) == 3
        assert await db.get_subscription_limit(alice) >= 50
    finally:
        await db.close()


async def test_admin_grant_bonus_slots(tmp_path):
    db = Database(tmp_path / "test_admin_slots.db")
    await db.connect()
    try:
        admin_id = 999
        user_id = 42

        # Base limit is 3
        assert await db.get_subscription_limit(user_id) == 3
        assert await db.get_bonus_slots(user_id) == 0

        # Admin grants +5 slots
        new_bonus = await db.grant_bonus_slots(user_id, 5, granted_by=admin_id)
        assert new_bonus == 5
        assert await db.get_bonus_slots(user_id) == 5
        assert await db.get_subscription_limit(user_id) == 8  # 3 + 5

        # Admin grants another +10 slots
        new_bonus = await db.grant_bonus_slots(user_id, 10, granted_by=admin_id)
        assert new_bonus == 15
        assert await db.get_subscription_limit(user_id) == 18  # 3 + 15
    finally:
        await db.close()


async def test_admin_grant_command_ux():
    database = SimpleNamespace(
        grant_bonus_slots=AsyncMock(return_value=5),
        get_subscription_limit=AsyncMock(return_value=8),
    )
    settings = SimpleNamespace(
        admin_ids=frozenset({777}),
        timezone="Europe/Warsaw",
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    handlers = TelegramHandlers(settings, database, None, None)

    # 1. Non-admin attempt should be ignored
    unauthorized = SimpleNamespace(
        text="/grant 42 5",
        from_user=SimpleNamespace(id=123),  # not admin
        answer=AsyncMock(),
        bot=bot,
    )
    await handlers.grant_command(unauthorized)
    unauthorized.answer.assert_not_awaited()

    # 2. Admin valid command
    admin_msg = SimpleNamespace(
        text="/grant 42 5",
        from_user=SimpleNamespace(id=777),  # admin
        answer=AsyncMock(),
        bot=bot,
    )
    await handlers.grant_command(admin_msg)

    database.grant_bonus_slots.assert_awaited_once_with(42, 5, granted_by=777)
    admin_msg.answer.assert_awaited_once()
    assert "начислено +5 слотов" in admin_msg.answer.call_args[0][0]
    bot.send_message.assert_awaited_once()
    assert "Администратор начислил вам +5" in bot.send_message.call_args[0][1]


async def test_referral_command_ux():
    database = SimpleNamespace(
        get_referral_count=AsyncMock(return_value=2),
        get_subscription_limit=AsyncMock(return_value=7),
    )
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    handlers = TelegramHandlers(settings, database, None, None)

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=555),
        answer=AsyncMock(),
    )
    await handlers.referral_command(msg)

    msg.answer.assert_awaited_once()
    reply_text = msg.answer.call_args[0][0]
    markup = msg.answer.call_args[1]["reply_markup"]

    assert "start=ref_555" in reply_text
    assert "Приглашено друзей: <b>2</b>" in reply_text
    assert "Лимит активных подписок: <b>7</b>" in reply_text
    assert markup is not None


async def test_start_with_referral_code_records_invite():
    database = SimpleNamespace(
        record_referral=AsyncMock(return_value=True),
    )
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    bot = SimpleNamespace(send_message=AsyncMock())
    handlers = TelegramHandlers(settings, database, None, None)

    msg = SimpleNamespace(
        text="/start ref_888",
        from_user=SimpleNamespace(id=999),
        answer=AsyncMock(),
        bot=bot,
    )
    await handlers.start(msg)

    database.record_referral.assert_awaited_once_with(888, 999)
    bot.send_message.assert_awaited_once()
    assert "По вашей ссылке зарегистрировался" in bot.send_message.call_args[0][1]


async def test_share_deal_callback():
    offer = Offer(
        thread_id="1",
        title="Bose QC Headphones",
        current_price=199.0,
        currency="€",
    )
    database = SimpleNamespace(
        get_session=AsyncMock(return_value={"offers": [offer]}),
    )
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    handlers = TelegramHandlers(settings, database, None, None)

    callback = SimpleNamespace(
        data="share:session123",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock()),
    )
    await handlers.share_deal_callback(callback)

    callback.message.answer.assert_awaited_once()
    args, kwargs = callback.message.answer.call_args
    assert "Поделиться скидкой на <b>Bose QC Headphones</b>" in args[0]
    markup = kwargs["reply_markup"]
    share_button = markup.inline_keyboard[0][0]
    assert "t.me/share/url" in share_button.url
    assert "ref_42" in share_button.url


async def test_channel_publisher_auto_posts_hot_deals():
    bot = SimpleNamespace(send_message=AsyncMock())
    publisher = ChannelPublisher(bot, channel_id="@test_deals", min_temperature=300.0)

    # 1. Cold deal (temperature 150 < 300) should NOT be published
    cold_offer = Offer("1", "Cheap mug", temperature=150, current_price=5.0)
    assert await publisher.maybe_publish(cold_offer) is False
    bot.send_message.assert_not_awaited()

    # 2. Hot deal (temperature 450 >= 300) SHOULD be published
    hot_offer = Offer(
        "2",
        "PS5 Slim Console",
        temperature=450,
        current_price=399.0,
        published_at=datetime.now(UTC),
    )
    assert await publisher.maybe_publish(hot_offer) is True
    bot.send_message.assert_awaited_once()
    post_text = bot.send_message.call_args[0][1]
    assert "PS5 Slim Console" in post_text
    assert "@loot_hunt_bot" in post_text

    # 3. Duplicate publish attempt should be prevented
    assert await publisher.maybe_publish(hot_offer) is False
    assert bot.send_message.await_count == 1
