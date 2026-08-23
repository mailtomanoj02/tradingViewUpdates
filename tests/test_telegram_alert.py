from src.telegram_alert import (
    bot_token,
    chat_ids,
    format_telegram_message,
    send_telegram_notification,
)


def _eurusd_signal():
    return {
        "symbol": "EURUSD",
        "direction": "LONG",
        "entry": 1.0842,
        "stop_loss": 1.0821,
    }


def test_bot_token_empty_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert bot_token() == ""


def test_bot_token_empty_string_env_var_is_safe_not_a_crash(monkeypatch):
    # A GitHub Actions workflow referencing a never-added secret sets the
    # env var to "" rather than leaving it absent (CLAUDE.md section 12).
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    assert bot_token() == ""


def test_chat_ids_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111111111, -100222222222")
    assert chat_ids() == ["111111111", "-100222222222"]


def test_chat_ids_empty_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)
    assert chat_ids() == []


def test_format_telegram_message_includes_symbol_direction_and_prices():
    message = format_telegram_message(_eurusd_signal())
    assert "EURUSD" in message
    assert "LONG" in message
    assert "1.0842" in message
    assert "1.0821" in message


def test_send_telegram_notification_posts_to_each_chat_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111111111,-100222222222")

    requests_made = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=None):
        requests_made.append(request)
        return FakeResponse()

    monkeypatch.setattr("src.telegram_alert.urllib.request.urlopen", fake_urlopen)

    send_telegram_notification("test message")

    assert len(requests_made) == 2
    assert requests_made[0].full_url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert requests_made[0].get_method() == "POST"
    assert b'"chat_id": "111111111"' in requests_made[0].data
    assert b'"test message"' in requests_made[0].data
    assert b'"chat_id": "-100222222222"' in requests_made[1].data


def test_send_telegram_notification_never_raises_on_failure(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111111111")

    def failing_urlopen(request, timeout=None):
        raise OSError("Telegram unreachable")

    monkeypatch.setattr("src.telegram_alert.urllib.request.urlopen", failing_urlopen)

    send_telegram_notification("test message")  # must not raise

    assert "111111111" in capsys.readouterr().err


def test_send_telegram_notification_is_a_noop_with_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111111111")

    def unexpected_urlopen(request, timeout=None):
        raise AssertionError("should not be called with no bot token configured")

    monkeypatch.setattr("src.telegram_alert.urllib.request.urlopen", unexpected_urlopen)

    send_telegram_notification("test message")  # must not raise / not call urlopen
