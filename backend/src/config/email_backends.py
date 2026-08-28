"""Local-development email backend that prints readable console output."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.console import (
    EmailBackend as ConsoleEmailBackend,
)
from django.core.mail.message import EmailMessage


class PlainTextConsoleEmailBackend(ConsoleEmailBackend):
    """Console email backend that prints an unencoded, readable message.

    Django's stock console backend writes the fully MIME-encoded message
    to stdout, which quoted-printable-encodes text bodies (`=` becomes
    `=3D`, long lines soft-wrap with a trailing `=`). That mangles any
    URL in the body, making it unusable when copied out of the console.

    This backend prints the message's original unencoded body instead,
    so links can be copied verbatim. It is a local-development
    convenience only, does not deliver mail anywhere, and refuses to
    load unless `settings.DEBUG` is True.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the backend, refusing to load outside local dev.

        Args:
            *args: Passed through to the parent console backend.
            **kwargs: Passed through to the parent console backend.

        Raises:
            ImproperlyConfigured: If `settings.DEBUG` is False.
        """
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "PlainTextConsoleEmailBackend is a local-development "
                "convenience and refuses to load when DEBUG is False."
            )
        super().__init__(*args, **kwargs)

    def write_message(self, message: EmailMessage) -> None:
        """Write a readable header block and the raw message body.

        Args:
            message: The email message to print.
        """
        self.stream.write("From: %s\n" % message.from_email)
        self.stream.write("To: %s\n" % ", ".join(message.to))
        self.stream.write("Subject: %s\n" % message.subject)
        self.stream.write("\n")
        self.stream.write(message.body)
        self.stream.write("\n")
        self.stream.write("-" * 79)
        self.stream.write("\n")
