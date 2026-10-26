"""Measure a fresh local serving process without importing scikit-learn."""
import json
import os
from pathlib import Path
import statistics
import sys
from time import perf_counter

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
import psutil
from django.core.cache import caches
from teams import matching
from teams.skill_suggestions import suggest

probe = 'Nous voulons automatiser les déploiements du service et surveiller les erreurs de production.'
caches['m2_embeddings'].delete(matching.cache_key(probe))
start = perf_counter()
result = suggest(probe,background=False)
cold_ms = (perf_counter()-start)*1000
warm = []
for _ in range(20):
    start=perf_counter(); suggest(probe,background=False); warm.append((perf_counter()-start)*1000)
uncached=[]
for i in range(5):
    text=probe+f' Édition technique {i}.'
    caches['m2_embeddings'].delete(matching.cache_key(text))
    start=perf_counter(); suggest(text,background=False); uncached.append((perf_counter()-start)*1000)
report = {'state':result['state'],'cold_first_inference_ms':round(cold_ms,2),
    'warm_cached_mean_ms':round(statistics.mean(warm),2),'warm_cached_p95_ms':round(sorted(warm)[18],2),
    'warm_model_uncached_text_mean_ms':round(statistics.mean(uncached),2),
    'serving_process_rss_mb':round(psutil.Process().memory_info().rss/1024**2,1),
    'machine_ram_gb':round(psutil.virtual_memory().total/1024**3,1),'logical_cpu_count':os.cpu_count(),
    'sklearn_imported':'sklearn' in sys.modules,
    'scope':'fresh Python + Django setup + one local ONNX model; not HTTP concurrency or a Render deployment benchmark'}
output=root/'artifacts'/'team-skill-needs'/'v1'/'serving_benchmark.json'
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
