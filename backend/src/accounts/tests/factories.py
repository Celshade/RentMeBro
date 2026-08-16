import factory
from factory.django import DjangoModelFactory

from accounts.models import MagicLinkToken, User


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
    class Meta:
        model = MagicLinkToken

    user = factory.SubFactory(UserFactory)
