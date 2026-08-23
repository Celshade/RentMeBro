import hashlib

from django.db import migrations, models


def _hash_existing_tokens(apps, schema_editor):
    """Converts rows carrying a raw token value into their SHA-256 hash.

    Runs once, right after the rename below, while the column still
    holds whatever `token` held (plaintext). Any row here is already
    within its (15-minute) expiry window at best, but converting them
    keeps `find_valid` working for tokens issued moments before deploy.
    """
    MagicLinkToken = apps.get_model('accounts', 'MagicLinkToken')
    for magic_link in MagicLinkToken.objects.all():
        magic_link.token_hash = hashlib.sha256(
            magic_link.token_hash.encode()
        ).hexdigest()
        magic_link.save(update_fields=['token_hash'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_btc_payments_enabled_user_btc_terms_accepted_at'),
    ]

    operations = [
        migrations.RenameField(
            model_name='magiclinktoken',
            old_name='token',
            new_name='token_hash',
        ),
        migrations.RunPython(
            _hash_existing_tokens, migrations.RunPython.noop
        ),
    ]
