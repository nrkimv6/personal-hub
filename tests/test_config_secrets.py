from app.core.config import Settings


SENSITIVE_NOTIFICATION_FIELDS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "RECIPIENT_EMAIL",
)


def test_sensitive_notification_defaults_are_empty(monkeypatch):
    for key in SENSITIVE_NOTIFICATION_FIELDS:
        monkeypatch.delenv(key, raising=False)

    config = Settings(_env_file=None)

    for key in SENSITIVE_NOTIFICATION_FIELDS:
        assert getattr(config, key) == ""


def test_sensitive_notification_settings_load_from_env(monkeypatch):
    env_values = {
        "TELEGRAM_BOT_TOKEN": "env-token",
        "TELEGRAM_CHAT_ID": "env-chat-id",
        "EMAIL_ADDRESS": "sender@example.com",
        "EMAIL_PASSWORD": "env-password",
        "RECIPIENT_EMAIL": "recipient@example.com",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    config = Settings(_env_file=None)

    for key, value in env_values.items():
        assert getattr(config, key) == value
