"""Frozen MiniLM + our trained linear multilabel head. Local inference only.

Only JSON coefficients are loaded in Django; scikit-learn is a training dependency.
Model output is a proposed team need, never a personal ability or inferred level.
"""
from functools import lru_cache
import json
import math
import re
from pathlib import Path

from django.conf import settings
from . import matching

SCHEMA = 1
MAX_TEXT = 1200
ALIASES = {
    'API REST':[r'\b(?:api\s+rest|rest(?:ful)?\s+api|restful|endpoints?\s+rest)\b'],
    'Cybersécurité':[r'cybers[eé]curit[eé]',r'cybersecurity'],
    'Data Science':[r'data science'], 'DevOps':[r'\bdevops\b'], 'Django':[r'\bdjango\b'],
    'Figma':[r'\bfigma\b'], 'JavaScript':[r'\bjavascript\b',r'\bjs\b'],
    'Machine Learning':[r'machine learning',r'apprentissage automatique'],
    'Mobile':[r'\bmobile\b',r'\bandroid\b',r'\bios\b'], 'PostgreSQL':[r'\bpostgres(?:ql)?\b'],
    'Python':[r'\bpython\b'], 'React':[r'\breact(?:js)?\b'], 'UI/UX':[r'ui\s*[/&-]\s*ux',r'\bux\b'],
}


def mentions(text):
    """Small, explicit alias baseline, including common FR/EN exclusions.

    These are deterministic mentions, never credited to the learned classifier.
    This is deliberately not a complete natural-language negation parser.
    """
    included,excluded = set(),set()
    for label,patterns in ALIASES.items():
        for pattern in patterns:
            for match in re.finditer(pattern,text,re.I):
                before = re.split(r'[.;,!?:]|\b(?:but|mais)\b',text[max(0,match.start()-65):match.start()],flags=re.I)[-1]
                after = text[match.end():match.end()+45]
                negated = re.search(r'\b(?:sans|not|no|avoid|exclude|excluding|pas(?: de)?)\b',before,re.I) and not re.search(r'(?:not only|pas seulement)',before,re.I)
                negated = negated or re.match(r"\s+(?:n['’]est pas|is not|isn['’]t|not needed|non requis)",after,re.I)
                (excluded if negated else included).add(label)
    return included-excluded,excluded


def combine(text, learned):
    explicit,excluded = mentions(text)
    learned = {r['label']:r for r in learned if r['label'] not in excluded}
    rows = [{'label':label,'source':'explicit','score':learned.get(label,{}).get('score',0.)} for label in sorted(explicit)]
    rows += [{'label':label,'source':'ml','score':r['score']} for label,r in learned.items() if label not in explicit]
    return rows[:8]


@lru_cache(maxsize=2)
def _read_artifact(path, modified):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema') != SCHEMA or data.get('embedding_model') != settings.M2_MODEL_NAME:
        raise ValueError('Incompatible skill model artifact.')
    labels = data['labels']
    if not 1 <= len(labels) <= 100 or not all(isinstance(label,str) and 0<len(label)<=100 for label in labels) or len(set(labels)) != len(labels):
        raise ValueError('Invalid labels.')
    for name in ('coefficients','intercepts','thresholds'):
        if len(data[name]) != len(labels):
            raise ValueError('Invalid classifier dimensions.')
    if data.get('dimension') != 384 or any(len(row) != 384 for row in data['coefficients']):
        raise ValueError('Invalid embedding dimension.')
    values = [v for row in data['coefficients'] for v in row] + data['intercepts'] + data['thresholds']
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
        raise ValueError('Invalid classifier values.')
    if any(not 0 < x <= 1 for x in data['thresholds']):
        raise ValueError('Invalid thresholds.')
    return data


def artifact():
    path = Path(settings.M2_SKILL_MODEL_PATH)
    try:
        return _read_artifact(str(path),path.stat().st_mtime_ns)
    except (OSError,ValueError,KeyError,TypeError):
        return None


def unit_vector(vector):
    norm = math.sqrt(sum(float(v)**2 for v in vector))
    return [float(v)/norm for v in vector] if norm else [0.]*len(vector)


def classify(data, vector):
    if len(vector) != data['dimension']:
        raise ValueError('Unexpected embedding size.')
    normalized = unit_vector(vector)
    results = []
    for label,weights,intercept,threshold in zip(data['labels'],data['coefficients'],data['intercepts'],data['thresholds']):
        logit = max(-40.,min(40.,sum(x*w for x,w in zip(normalized,weights))+intercept))
        score = 1/(1+math.exp(-logit))
        if score >= threshold:
            results.append({'label':label,'score':score})
    return sorted(results,key=lambda row:(-row['score'],row['label']))[:data.get('max_suggestions',5)]


def suggest(text, *, background=True):
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        return {'state':'invalid','suggestions':[]}
    data = artifact()
    if data is None:
        return {'state':'untrained','suggestions':[]}
    embeddings,state = matching.vectors([text],background=background)
    if embeddings is None:
        return {'state':state,'suggestions':[]}
    try:
        suggestions = combine(text,classify(data,embeddings[0]))
    except (ValueError,TypeError,OverflowError):
        return {'state':'unavailable','suggestions':[]}
    return {'state':'ready','suggestions':suggestions,'version':data.get('version','pilot')}
