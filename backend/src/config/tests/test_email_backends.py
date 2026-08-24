"""Tests for PlainTextConsoleEmailBackend."""

import io

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.test import override_settings

from config.email_backends import PlainTextConsoleEmailBackend

BACKEND_PATH = "config.email_backends.PlainTextConsoleEmailBackend"


def _send_and_capture(subject: str, message: str, to: list[str]) -> str:
    """Sends an email through the plaintext backend and captures stdout.

    Args:
        subject: The email subject.
        message: The email body.
        to: The list of recipient addresses.

    Returns:
        Everything written to the backend's stream.
    """
    stream = io.StringIO()
    with override_settings(DEBUG=True, EMAIL_BACKEND=BACKEND_PATH):
        backend = PlainTextConsoleEmailBackend(stream=stream)
        send_mail(
            subject=subject,
            message=message,
            from_email="noreply@rentmebro.local",
            recipient_list=to,
            connection=backend,
        )
    return stream.getvalue()


class TestPlainTextConsoleEmailBackend:
    """Verifies the console output stays copy-pasteable and readable."""

    def test_url_survives_unmodified(self) -> None:
        """A long URL with a query string prints verbatim, unmangled."""
        url = (
            "http://localhost:5173/auth/verify?token="
            "abcdef0123456789abcdef0123456789abcdef01"
        )
        output = _send_and_capture(
            subject="Your RentMeBro sign-in link",
            message=f"Sign in here: {url}",
            to=["nftcel@proton.me"],
        )
        assert url in output
        assert "=3D" not in output

    def test_recipient_and_subject_still_shown(self) -> None:
        """The header block still shows recipient and subject."""
        output = _send_and_capture(
            subject="Your RentMeBro sign-in link",
            message="Sign in here: http://localhost:5173",
            to=["nftcel@proton.me"],
        )
        assert "nftcel@proton.me" in output
        assert "Your RentMeBro sign-in link" in output

    def test_refuses_to_load_outside_debug(self) -> None:
        """Instantiating the backend with DEBUG=False raises."""
        with override_settings(DEBUG=False):
            with pytest.raises(ImproperlyConfigured):
                PlainTextConsoleEmailBackend()
