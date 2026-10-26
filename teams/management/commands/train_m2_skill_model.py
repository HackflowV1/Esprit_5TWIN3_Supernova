"""Reproducible offline training. Never imported by a normal web request."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from teams import matching
from teams.skill_suggestions import classify, mentions, combine

LABELS = sorted(['API REST','Cybersécurité','Data Science','DevOps','Django','Figma',
    'JavaScript','Machine Learning','Mobile','PostgreSQL','Python','React','UI/UX'])


def read_dataset(directory):
    groups,seen_ids,seen_text = set(),set(),set()
    result = {}
    digest = sha256()
    for split in ('train','validation','test'):
        paths = [directory/f'{split}.jsonl']
        if split in ('train','validation') and (directory/f'{split}_extra.jsonl').exists():
            paths.append(directory/f'{split}_extra.jsonl')
        if split=='test' and (directory/'final_test.jsonl').exists():
            paths = [directory/'final_test.jsonl']
        raw = b'\n'.join(path.read_bytes() for path in paths)
        digest.update(raw)
        rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
        split_groups = set()
        for row in rows:
            text = row['text'].strip()
            normalized = re.sub(r'\W+',' ',text.casefold()).strip()
            if not text or len(text)>1200 or row['id'] in seen_ids or normalized in seen_text:
                raise ValueError('Invalid text, duplicate row ID or duplicate text across dataset.')
            if not isinstance(row['labels'],list) or set(row['labels'])-set(LABELS) or len(set(row['labels']))!=len(row['labels']):
                raise ValueError('Unknown or duplicate skill label.')
            if row['group'] in groups:
                raise ValueError('Scenario group crosses dataset splits.')
            if row.get('source')!='gpt-6-luna-synthetic' or row.get('review_status')!='unreviewed':
                raise ValueError('Keep synthetic provenance and unreviewed status explicit.')
            seen_ids.add(row['id']); seen_text.add(normalized); split_groups.add(row['group'])
        if not rows:
            raise ValueError('Empty dataset split.')
        groups.update(split_groups)
        support = Counter(label for row in rows for label in row['labels'])
        if any(not support[label] for label in LABELS):
            raise ValueError(f'{split}: every skill needs positive examples.')
        result[split] = rows
    return result,digest.hexdigest()


def thresholds_for(y,probabilities):
    import numpy as np
    from sklearn.metrics import fbeta_score
    thresholds = []
    for i in range(len(LABELS)):
        # Conservative suggestions: optimize F0.5 on validation only. Ties choose
        # the higher threshold. These scores are NOT calibrated confidence.
        choices = [(fbeta_score(y[:,i],probabilities[:,i]>=t,beta=.5,zero_division=0),t)
            for t in np.arange(.55,.96,.05)]
        best,threshold = max(choices)
        thresholds.append(float(threshold) if best else 1.0)
    return thresholds


def metrics(y,predictions):
    from sklearn.metrics import precision_recall_fscore_support, accuracy_score
    result = {'exact_set_accuracy':float(accuracy_score(y,predictions))}
    for average in ('micro','macro'):
        p,r,f,_ = precision_recall_fscore_support(y,predictions,average=average,zero_division=0)
        result[average] = {'precision':float(p),'recall':float(r),'f1':float(f)}
    p,r,f,support = precision_recall_fscore_support(y,predictions,average=None,zero_division=0)
    result['per_skill'] = {label:dict(precision=float(p[i]),recall=float(r[i]),f1=float(f[i]),support=int(support[i])) for i,label in enumerate(LABELS)}
    negatives = y.sum(axis=1)==0
    result['empty_description_cases'] = int(negatives.sum())
    result['false_suggestions_on_empty_cases'] = int((predictions[negatives].sum(axis=1)>0).sum())
    return result


class Command(BaseCommand):
    help = 'Train and evaluate the M2 skill-needs classifier offline on explicit synthetic train/validation/test splits.'

    def add_arguments(self,parser):
        parser.add_argument('--dataset',default=str(settings.BASE_DIR/'datasets'/'team_skill_needs'))
        parser.add_argument('--output',default=str(settings.M2_SKILL_MODEL_PATH.parent))

    def handle(self,**options):
        import numpy as np
        import psutil
        import sklearn
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        from sklearn.preprocessing import MultiLabelBinarizer
        started = perf_counter()
        try:
            data,fingerprint = read_dataset(Path(options['dataset']))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise CommandError(f'Dataset audit failed: {exc}') from exc
        labeler = MultiLabelBinarizer(classes=LABELS)
        targets = {split:labeler.fit_transform([row['labels'] for row in rows]) for split,rows in data.items()}
        texts = {split:[row['text'].strip() for row in rows] for split,rows in data.items()}
        self.stdout.write('Dataset audited. Encoding synthetic descriptions with frozen local MiniLM...')
        encoded = {}
        encoding_start = perf_counter()
        for split in data:
            vectors,state = matching.vectors(texts[split],background=False)
            if state!='ready':
                raise CommandError('Prepare MiniLM first: python scripts/download_m2_model.py. No inference was fabricated.')
            x = np.asarray(vectors,dtype=np.float64)
            encoded[split] = x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-12)
        encoding_seconds = perf_counter()-encoding_start
        def estimator():
            return OneVsRestClassifier(LogisticRegression(C=10,class_weight='balanced',max_iter=2000,random_state=26),n_jobs=1)
        model = estimator()
        train_start = perf_counter()
        model.fit(encoded['train'],targets['train'])
        training_seconds = perf_counter()-train_start
        thresholds = thresholds_for(targets['validation'],model.predict_proba(encoded['validation']))
        artifact = {'schema':1,'version':'m2-skill-needs-pilot-1','embedding_model':settings.M2_MODEL_NAME,
            'dimension':384,'normalization':'l2','labels':LABELS,'thresholds':thresholds,'max_suggestions':5,
            'coefficients':[est.coef_[0].tolist() for est in model.estimators_],
            'intercepts':[float(est.intercept_[0]) for est in model.estimators_],
            'dataset_sha256':fingerprint,'sklearn_version':sklearn.__version__,
            'evaluation_scope':'synthetic held-out only; no human validation; not measured real-world accuracy'}
        # Serving and evaluation use exactly the same normalization, thresholds and cap.
        predictions = labeler.transform([[r['label'] for r in classify(artifact,vector)] for vector in encoded['test']])
        keyword_predictions = labeler.transform([sorted(mentions(text)[0]) for text in texts['test']])
        hybrid_predictions = labeler.transform([[r['label'] for r in combine(text,classify(artifact,vector))] for text,vector in zip(texts['test'],encoded['test'])])
        tfidf = TfidfVectorizer(ngram_range=(1,2),strip_accents='unicode',sublinear_tf=True,max_features=12000)
        tx = tfidf.fit_transform(texts['train'])
        baseline = estimator().fit(tx,targets['train'])
        bt = thresholds_for(targets['validation'],baseline.predict_proba(tfidf.transform(texts['validation'])))
        scores = baseline.predict_proba(tfidf.transform(texts['test']))
        tfidf_predictions = np.zeros_like(targets['test'])
        for i,row in enumerate(scores):
            selected = [j for j in np.argsort(-row) if row[j]>=bt[j]][:5]
            tfidf_predictions[i,selected]=1
        timings=[]
        for vector in encoded['test']:
            start=perf_counter(); classify(artifact,vector); timings.append((perf_counter()-start)*1000)
        counts = {split:{'rows':len(rows),'languages':dict(Counter(r.get('language','unknown') for r in rows)),
            'empty_labels':sum(not r['labels'] for r in rows),'support':dict(Counter(label for r in rows for label in r['labels']))} for split,rows in data.items()}
        report = {'evaluation_scope':artifact['evaluation_scope'],'dataset_sha256':fingerprint,'splits':counts,
            'threshold_selection':'per-label validation F0.5, floor .55, ties choose higher threshold; final test never used for tuning',
            'models':{'frozen_minilm_logistic':metrics(targets['test'],predictions),
                'tfidf_logistic':metrics(targets['test'],tfidf_predictions),'keyword_alias':metrics(targets['test'],keyword_predictions),
                'hybrid_served':metrics(targets['test'],hybrid_predictions)},
            'performance':{'embedding_all_splits_seconds':round(encoding_seconds,3),'head_training_seconds':round(training_seconds,3),
                'head_warm_mean_ms':round(float(np.mean(timings)),3),'head_warm_p95_ms':round(float(np.percentile(timings,95)),3),
                'training_process_rss_mb':round(psutil.Process().memory_info().rss/1024**2,1),
                'total_seconds':round(perf_counter()-started,3)},
            'test_predictions':[{'id':row['id'],'expected':row['labels'],'predicted':[LABELS[j] for j in np.flatnonzero(predictions[i])],
                'served':[LABELS[j] for j in np.flatnonzero(hybrid_predictions[i])]} for i,row in enumerate(data['test'])]}
        out = Path(options['output']); out.mkdir(parents=True,exist_ok=True)
        (out/'classifier.json').write_text(json.dumps(artifact,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        (out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        self.stdout.write(json.dumps({'counts':{k:v['rows'] for k,v in counts.items()},
            'scores':{name:result['micro'] for name,result in report['models'].items()},'performance':report['performance']},indent=2))
        self.stdout.write(self.style.SUCCESS('JSON classifier and synthetic evaluation saved. Human review remains pending.'))
