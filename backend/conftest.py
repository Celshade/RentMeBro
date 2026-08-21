"""Root pytest conftest.

Its presence here (next to pyproject.toml) anchors pytest's rootdir at
backend/, matching where manage.py lives and where DATABASE_URL/.env
resolution (BASE_DIR) is computed from. Fixtures shared across every
app's test suite live here; app-specific fixtures live in each app's
tests/conftest.py.
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Throttle counters live in Django's cache; clear between tests so
    one test's requests don't count against another's rate limit.
    """
    cache.clear()
    yield
    cache.clear()
