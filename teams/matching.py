"""Explainable M2 ranking. No model download, API, or recruitment side effect here.

Identity/eligibility stay in services. Embeddings never establish a skill or level.
HTTP cache misses are computed by one bounded background worker, not by the request.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import sha256
import logging
import math
from pathlib import Path
from threading import Lock
from time import monotonic

from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)
VERSION = 'm2-hybrid-3-english-q8'
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='m2-embeddings')
_lock = Lock()
_busy = False
_retry_after = 0.0


def profile_text(user):
    profile = getattr(user, 'profile', None)
    # MiniLM truncates at 128 tokens. Keep project interests before potentially
    # lengthy skill experience so contextual input is not pushed off the window.
    return ' '.join(filter(None, [
        getattr(profile, 'biography', '')[:500], getattr(profile, 'interests', '')[:220],
        ', '.join(s.skill.name for s in user.user_skills.all()),
        '; '.join(s.experience[:80] for s in list(user.user_skills.all())[:3] if s.experience),
    ]))[:1200]


def team_text(team, needs):
    # Put declared needs first: the model truncates long inputs to 128 tokens.
    return (', '.join(n.skill.name for n in needs) + '. ' + team.description[:700])[:1000]


def cache_key(text):
    return sha256(f'{VERSION}|{settings.M2_MODEL_NAME}|{text}'.encode()).hexdigest()


@lru_cache(maxsize=1)
def _model():
    from .encoder import Encoder
    return Encoder(settings.M2_MODEL_CACHE)


def _compute(texts):
    cache = caches['m2_embeddings']
    model = _model()
    for text, vector in zip(texts, model.embed(texts, batch_size=16)):
        cache.set(cache_key(text), vector.tolist())


def _worker(texts):
    global _busy, _retry_after
    try:
        _compute(texts)
    except Exception:
        # Never log the biographies or model inputs.
        logger.warning('M2 semantic model unavailable; using declared-skill ranking.')
        _retry_after = monotonic() + 60
    finally:
        with _lock:
            _busy = False


def vectors(texts, *, background=True):
    """Return cached vectors + state; the request never loads a model or downloads."""
    global _busy
    if not settings.M2_MATCHING_ENABLED:
        return None, 'disabled'
    if not (Path(settings.M2_MODEL_CACHE) / 'READY').is_file():
        return None, 'unavailable'
    cache = caches['m2_embeddings']
    unique = list(dict.fromkeys(texts))
    found = {text: cache.get(cache_key(text)) for text in unique}
    missing = [text for text, value in found.items() if value is None]
    if missing and not background:
        try:
            _compute(missing)
            found = {text: cache.get(cache_key(text)) for text in unique}
        except Exception:
            return None, 'unavailable'
    elif missing:
        if monotonic() < _retry_after:
            return None, 'unavailable'
        with _lock:
            if not _busy:
                _busy = True
                # At most one submitted job, with at most 128 short texts.
                _executor.submit(_worker, missing[:128])
        return None, 'warming'
    return [found[text] for text in texts], 'ready'


def cosine(a, b):
    norm = math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))
    return max(0.0, min(1.0, sum(x*y for x, y in zip(a, b)) / norm)) if norm else 0.0


def rank(*, team, candidates, needs, background=True, mode='hybrid'):
    """Essential declared skills dominate; context refines comparable coverage.

    score preserves the V1 rules score for consumers/evaluation. rank_key is not
    a probability and is never presented as a compatibility percentage.
    """
    candidates = list(candidates)
    needs = [n for n in needs if not n.covered_by]
    state = 'no_needs' if not needs else 'skills' if mode == 'skills' else 'rules'
    embeddings = None
    if candidates and needs and mode == 'hybrid' and not team.description.strip():
        state = 'no_context'
    elif candidates and needs and mode == 'hybrid':
        embeddings, state = vectors([team_text(team, needs)] + [profile_text(r.user) for r in candidates], background=background)
    results = []
    for index, reg in enumerate(candidates):
        skills = {s.skill_id: s for s in reg.user.user_skills.all()}
        matches = [dict(skill=n.skill.name, level=skills[n.skill_id].level, requested=n.level,
            meets=skills[n.skill_id].level >= n.level, priority=n.priority)
            for n in needs if n.skill_id in skills]
        score = sum(n.priority * min(skills[n.skill_id].level, n.level) for n in needs if n.skill_id in skills)
        total = sum(n.priority * n.level for n in needs)
        coverage = score / total if total else 0
        essential_met = sum(n.priority == 3 and n.skill_id in skills and skills[n.skill_id].level >= n.level for n in needs)
        essential_present = sum(n.priority == 3 and n.skill_id in skills for n in needs)
        similarity = cosine(embeddings[0], embeddings[index+1]) if embeddings else 0
        # Never let contextual similarity endorse a candidate with no declared match.
        # Conservative UI cue, not a calibrated probability or evaluation label.
        context_signal = bool(embeddings and matches and similarity >= .65)
        if mode == 'keywords':
            import re
            terms = lambda text: set(re.findall(r'\w{3,}', text.casefold()))
            keyword_score = len(terms(team_text(team, needs)) & terms(profile_text(reg.user)))
            key = (-keyword_score,)
        elif mode == 'rules':
            key = (-score,)
        else:
            key = (-essential_met, -essential_present, -int(coverage*4), -(coverage*.85 + similarity*.15 if matches else 0), -score)
        results.append(dict(registration=reg, matches=matches, score=score,
            context_signal=context_signal, semantic_similarity=similarity,
            rank_key=key, matching_state=state))
    return sorted(results, key=lambda item: (*item['rank_key'], item['registration'].user.username.casefold()))
