from types import SimpleNamespace
from unittest.mock import AsyncMock

from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.search.service import SearchResult, SearchService
from loot_hunt.telegram.handlers import START_TEXT, TelegramHandlers


def handlers(database=None):
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    return TelegramHandlers(settings, database, None, None)


async def test_find_offers_exposes_live_category_entry_point():
    message = SimpleNamespace(answer=AsyncMock())
    instance = handlers()
    await instance.ask_search(message)
    text = message.answer.await_args.args[0]
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert "Можно написать запрос" in text and "Или выбрать категорию" in text
    assert len(keyboard.inline_keyboard) == len(instance.catalog)
    assert all(row[0].callback_data.startswith("cat:") for row in keyboard.inline_keyboard)


async def test_existing_category_subscription_remains_manageable():
    database = SimpleNamespace(
        subscriptions=AsyncMock(
            return_value=[{"id": 3, "kind": "category", "label": "Gaming", "active": 1}]
        )
    )
    message = SimpleNamespace(from_user=SimpleNamespace(id=7), answer=AsyncMock())
    await handlers(database).subscriptions(message)
    rendered = message.answer.await_args_list[-1].args[0]
    assert rendered == "📁 Gaming · активна"


async def test_subscription_label_is_html_escaped():
    database = SimpleNamespace(
        subscriptions=AsyncMock(
            return_value=[{"id": 3, "kind": "search", "label": 'TV <50" & <b>', "active": 1}]
        )
    )
    message = SimpleNamespace(from_user=SimpleNamespace(id=7), answer=AsyncMock())
    await handlers(database).subscriptions(message)
    rendered = message.answer.await_args_list[-1].args[0]
    assert "&lt;b&gt;" in rendered and "<b>" not in rendered


def test_start_text_explains_new_navigation():
    assert "🔎 Найти предложения" in START_TEXT
    assert "🔔 Отслеживать этот поиск" in START_TEXT
    assert "📋 Мои подписки" in START_TEXT
    assert "Через Отслеживание" not in START_TEXT


async def test_zero_result_search_creates_trackable_session():
    plan = SearchPlan(
        original_query="Rare Model XZ-999", intent="exact", queries=[PlannedQuery(query="XZ-999")]
    )
    search = SimpleNamespace(
        search=AsyncMock(return_value=SearchResult(plan, [])),
        page=SearchService.page,
    )
    database = SimpleNamespace(
        upsert_offers=AsyncMock(),
        create_session=AsyncMock(return_value="empty-session"),
    )
    settings = SimpleNamespace(
        admin_ids=frozenset(),
        timezone="Europe/Warsaw",
        search_session_ttl_seconds=600,
    )
    instance = TelegramHandlers(settings, database, search, None)
    status = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(
        text="Rare Model XZ-999",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(return_value=status),
    )
    await instance.search_text(message)
    database.create_session.assert_awaited_once_with(42, message.text, plan, [], 600)
    text = status.edit_text.await_args.args[0]
    keyboard = status.edit_text.await_args.kwargs["reply_markup"]
    assert "Активных предложений сейчас нет" in text
    assert keyboard.inline_keyboard[0][0].text == "🔔 Отслеживать этот поиск"
    assert keyboard.inline_keyboard[0][0].callback_data == "ws:empty-session"


async def test_uncertain_search_discloses_lack_of_confident_results():
    plan = SearchPlan(original_query="ноутбук", queries=[PlannedQuery(query="laptop")])
    offer = Offer("1", "Lenovo laptop")
    search = SimpleNamespace(
        search=AsyncMock(return_value=SearchResult(plan, [offer], has_confident_matches=False)),
        page=SearchService.page,
    )
    database = SimpleNamespace(
        upsert_offers=AsyncMock(), create_session=AsyncMock(return_value="session")
    )
    settings = SimpleNamespace(
        admin_ids=frozenset(), timezone="Europe/Warsaw", search_session_ttl_seconds=600
    )
    status = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(
        text="ноутбук", from_user=SimpleNamespace(id=42), answer=AsyncMock(return_value=status)
    )
    await TelegramHandlers(settings, database, search, None).search_text(message)
    assert "Точных совпадений пока нет" in status.edit_text.await_args.args[0]


def test_category_result_keyboard_exposes_category_subscription():
    from loot_hunt.pepper.categories import PARENTS
    from loot_hunt.telegram.keyboards import categories_keyboard, result_keyboard

    keyboard = result_keyboard("cat-session", [], 0, 10, watch=True, category_key="gaming")
    assert any(
        btn.callback_data == "wc:cat-session:gaming"
        for row in keyboard.inline_keyboard
        for btn in row
    )

    sub_keyboard = categories_keyboard(PARENTS[0].children, show_back=True)
    assert any(
        btn.callback_data == "cat:root:0"
        for row in sub_keyboard.inline_keyboard
        for btn in row
    )


async def test_repeated_watch_tap_does_not_create_duplicate():
    plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="x")])
    database = SimpleNamespace(
        get_session=AsyncMock(return_value={"query": "x", "plan": plan, "offers": []}),
        find_subscription=AsyncMock(return_value=7),
        can_add_subscription=AsyncMock(return_value=True),
        create_subscription=AsyncMock(),
    )
    callback = SimpleNamespace(
        data="ws:session1",
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
        message=None,
    )
    await handlers(database).watch_search(callback)
    database.create_subscription.assert_not_awaited()
    assert "уже отслеживается" in callback.answer.await_args.args[0]


async def test_subscription_actions_update_message_instead_of_deleting():
    database = SimpleNamespace(set_subscription=AsyncMock(return_value=True))
    instance = handlers(database)

    delete_callback = SimpleNamespace(
        data="sub:delete:7",
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock(), text=""),
    )
    await instance.subscription_action(delete_callback)
    delete_callback.message.edit_text.assert_awaited_once_with("🗑 Подписка удалена.")

    pause_message = SimpleNamespace(
        text="📁 Gaming · активна", edit_text=AsyncMock(), edit_reply_markup=AsyncMock()
    )
    pause_callback = SimpleNamespace(
        data="sub:pause:7",
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
        message=pause_message,
    )
    await instance.subscription_action(pause_callback)
    assert "· на паузе" in pause_message.edit_text.await_args.args[0]


async def test_unknown_command_does_not_run_a_search():
    instance = handlers()
    message = SimpleNamespace(
        text="/nope", from_user=SimpleNamespace(id=1), answer=AsyncMock()
    )
    await instance.unknown_command(message)
    assert "Не знаю такую команду" in message.answer.await_args.args[0]


def searchable_handlers():
    search = SimpleNamespace(search=AsyncMock(), page=SearchService.page)
    database = SimpleNamespace(
        upsert_offers=AsyncMock(),
        create_session=AsyncMock(return_value="session"),
    )
    settings = SimpleNamespace(
        admin_ids=frozenset(),
        timezone="Europe/Warsaw",
        search_session_ttl_seconds=600,
    )
    return TelegramHandlers(settings, database, search, None), search


async def test_search_cooldown_blocks_rapid_repeat():
    import time

    instance, search = searchable_handlers()
    instance._last_search_at[42] = time.monotonic()
    status = SimpleNamespace(edit_text=AsyncMock())
    message = SimpleNamespace(
        text="monitor", from_user=SimpleNamespace(id=42), answer=AsyncMock(return_value=status)
    )
    await instance.search_text(message)
    search.search.assert_not_awaited()
    assert "Слишком часто" in message.answer.await_args.args[0]


async def test_search_rejects_overlong_query():
    instance, search = searchable_handlers()
    message = SimpleNamespace(
        text="x" * 201,
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
    )
    await instance.search_text(message)
    search.search.assert_not_awaited()
    assert "слишком длинный" in message.answer.await_args.args[0]


async def test_share_button_uses_viewed_page_and_deal_url():
    offers = [
        Offer(str(index), f"Offer {index}", current_price=1, pepper_url=f"https://p.example/{index}")
        for index in range(6)
    ]
    database = SimpleNamespace(get_session=AsyncMock(return_value={"offers": offers}))
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    instance = TelegramHandlers(
        settings, database, SimpleNamespace(page=SearchService.page), None
    )
    callback = SimpleNamespace(
        data="share:session:1",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock()),
    )

    await instance.share_deal_callback(callback)

    args, kwargs = callback.message.answer.call_args
    assert "Offer 5" in args[0]
    url = kwargs["reply_markup"].inline_keyboard[0][0].url
    assert "p.example%2F5" in url
    assert "Offer%205" in url
