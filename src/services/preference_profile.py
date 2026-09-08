from collections import defaultdict
from datetime import datetime

from src.models import LoanStatus


def _score(kind, occurred_at, now, status=None):
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=now.tzinfo)
    age_days = max(0, (now - occurred_at).total_seconds() / 86400)
    factor = 1.5 if age_days <= 30 else 1.25 if age_days <= 90 else 1.0 if age_days <= 180 else 0.7
    weight = 2.0 if kind == 'loan' else 1.0
    if kind == 'loan' and status == LoanStatus.RETURNED:
        weight *= 1.25
    return weight * factor


def calculate_genre_preferences(interactions, now: datetime):
    """Build an ordered, reusable genre preference profile.

    Each item is ``(genre_name, interaction_kind, occurred_at, status)``.
    """
    scores = defaultdict(float)
    for genre_name, kind, occurred_at, status in interactions:
        scores[genre_name] += _score(kind, occurred_at, now, status)
    return [
        {'genre': name, 'score': round(score, 2)}
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
