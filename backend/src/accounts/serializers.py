from rest_framework import serializers

from accounts.models import User


class MagicLinkRequestSerializer(serializers.Serializer):
    """Validates a magic-link request: the email and role to sign in
    as.
    """

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=User.Role.choices)


class MagicLinkVerifySerializer(serializers.Serializer):
    """Validates a magic-link token submitted to exchange for a JWT
    pair.
    """

    token = serializers.CharField()


class UserSerializer(serializers.ModelSerializer):
    """Serializes the public-facing fields of a `User`."""

    class Meta:
        model = User
        fields = ["id", "email", "role", "first_name", "last_name"]
