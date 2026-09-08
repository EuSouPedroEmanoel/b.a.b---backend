from datetime import datetime, timedelta, timezone

from src.models import LoanStatus
from src.services.preference_profile import calculate_genre_preferences


def test_profile_orders_genres_using_weight_and_recency():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = calculate_genre_preferences([
        ('Fantasia', 'loan', now - timedelta(days=5), LoanStatus.RETURNED),
        ('Tecnologia', 'reservation', now - timedelta(days=5), None),
    ], now)
    assert profile[0]['genre'] == 'Fantasia'
    assert profile[0]['score'] > profile[1]['score']


def test_empty_history_returns_empty_profile_for_fallback():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert calculate_genre_preferences([], now) == []


def test_recent_activity_can_overcome_old_dominant_interest():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = calculate_genre_preferences([
        *[('Fantasia', 'loan', now - timedelta(days=365), None)] * 2,
        ('Tecnologia', 'loan', now - timedelta(days=3), LoanStatus.RETURNED),
    ], now)
    assert profile[0]['genre'] == 'Tecnologia'


def test_multiple_genres_are_preserved_and_sorted():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = calculate_genre_preferences([
        ('Romance', 'reservation', now, None),
        ('Fantasia', 'loan', now, LoanStatus.RETURNED),
        ('Tecnologia', 'loan', now - timedelta(days=60), None),
    ], now)
    assert [item['genre'] for item in profile] == [
        'Fantasia', 'Tecnologia', 'Romance'
    ]
