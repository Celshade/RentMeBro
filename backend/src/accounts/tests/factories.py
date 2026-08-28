import secrets

import factory
from factory.django import DjangoModelFactory

from accounts.models import MagicLinkToken, User, _hash_token


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = "Test"
    last_name = "User"
    role = User.Role.RENTER


class LandlordFactory(UserFactory):
    role = User.Role.LANDLORD


class MagicLinkTokenFactory(DjangoModelFactory):
    """Builds a `MagicLinkToken` with a real raw token behind its hash.

    The raw value is attached to the built instance as `.raw_token`
    (not a model field) so tests can exercise the same verify flow a
    real request would, without the factory storing plaintext.
    """

    class Meta:
        model = MagicLinkToken

    user = factory.SubFactory(UserFactory)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        raw_token = secrets.token_urlsafe(32)
        kwargs["token_hash"] = _hash_token(raw_token)
        magic_link = super()._create(model_class, *args, **kwargs)
        magic_link.raw_token = raw_token
        return magic_link
