from email.message import EmailMessage

from app import email_delivery


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=10, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = False
        self.login_args = None
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage):
        self.message = message


def configure(monkeypatch):
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("OPYT50_SMTP_PORT", "587")
    monkeypatch.setenv("OPYT50_SMTP_USER", "mailer")
    monkeypatch.setenv("OPYT50_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "no-reply@example.invalid")
    monkeypatch.setenv("OPYT50_SMTP_STARTTLS", "1")


def test_delivery_disabled_without_environment(monkeypatch):
    for name in ("OPYT50_SMTP_HOST", "OPYT50_MAIL_FROM"):
        monkeypatch.delenv(name, raising=False)
    assert email_delivery.delivery_mode() == "outbox_only"
    assert email_delivery.send_email("user@example.invalid", "Subject", "Body") is False


def test_smtp_delivery_uses_tls_and_credentials(monkeypatch):
    FakeSMTP.instances.clear()
    configure(monkeypatch)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)

    assert email_delivery.delivery_mode() == "smtp"
    assert email_delivery.send_email("user@example.invalid", "Тема", "Текст") is True

    smtp = FakeSMTP.instances[-1]
    assert smtp.host == "smtp.example.invalid"
    assert smtp.port == 587
    assert smtp.started_tls is True
    assert smtp.login_args == ("mailer", "secret")
    assert smtp.message["From"] == "no-reply@example.invalid"
    assert smtp.message["To"] == "user@example.invalid"
    assert smtp.message["Subject"] == "Тема"
    assert "Текст" in smtp.message.get_content()


def test_smtp_failure_does_not_break_business_action(monkeypatch):
    configure(monkeypatch)

    class BrokenSMTP(FakeSMTP):
        def __enter__(self):
            raise OSError("mail server unavailable")

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", BrokenSMTP)
    assert email_delivery.send_email("user@example.invalid", "Subject", "Sensitive token body") is False
