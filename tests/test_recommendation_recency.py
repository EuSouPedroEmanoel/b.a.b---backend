from datetime import datetime, timedelta, timezone

from src.models import LoanStatus
from src.routers.books import (  # noqa: PLC2701
    _interaction_affinity_score,
    _recency_factor,
)


def test_recency_bands_are_applied():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _recency_factor(now - timedelta(days=10), now) == 1.5
    assert _recency_factor(now - timedelta(days=60), now) == 1.25
    assert _recency_factor(now - timedelta(days=120), now) == 1.0
    assert _recency_factor(now - timedelta(days=365), now) == 0.7


def test_recent_interaction_outweighs_old_interaction():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent = _interaction_affinity_score('loan', now - timedelta(days=5), now)
    old = _interaction_affinity_score('loan', now - timedelta(days=365), now)
    assert recent > old


def test_completed_loan_keeps_higher_weight_than_reservation():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    loan = _interaction_affinity_score('loan', now, now, LoanStatus.RETURNED)
    reservation = _interaction_affinity_score('reservation', now, now)
    assert loan > reservation
