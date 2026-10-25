"""Decimal only. Individual totals retain 4 places; displayed means use ROUND_HALF_UP.
Equal displayed means share competition rank (1, 1, 3); ID orders display only.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError


def weighted_total(criteria, scores):
    criteria = list(criteria)
    if not criteria or sum((c.weight for c in criteria), Decimal(0)) != Decimal(100):
        raise ValidationError('La somme des poids doit être égale à 100 %.')
    if set(scores) != {c.pk for c in criteria}:
        raise ValidationError('Toutes les notes sont requises.')
    total = Decimal(0)
    for c in criteria:
        score = Decimal(scores[c.pk])
        if not score.is_finite() or not 0 <= score <= c.max_score or c.max_score <= 0:
            raise ValidationError('Note hors limites.')
        total += score / c.max_score * c.weight
    return total.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def evaluation_total(evaluation):
    return weighted_total(evaluation.assignment.hackathon.evaluation_criteria.all(), dict(evaluation.scores.values_list('criterion_id', 'score')))


def mean_score(values):
    values = list(values)
    return (sum(values, Decimal(0)) / len(values)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if values else None
