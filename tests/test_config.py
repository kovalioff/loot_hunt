from loot_hunt.config import Settings


def test_defaults_and_admins(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1, 2,bad")
    monkeypatch.delenv("WATCHER_INTERVAL_SECONDS", raising=False)
    settings = Settings.from_env(load_env=False)
    assert settings.watcher_interval_seconds == 3600
    assert settings.admin_ids == {1, 2}
    assert settings.search_result_cap <= 30
