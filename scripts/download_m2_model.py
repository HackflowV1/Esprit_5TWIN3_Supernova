"""Build-time model preparation without a database or Django settings import."""
import os
from pathlib import Path
from fastembed import TextEmbedding

root = Path(__file__).resolve().parents[1]
directory = Path(os.environ.get('M2_MODEL_CACHE',str(root/'.cache'/'m2-model')))
name = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
directory.mkdir(parents=True,exist_ok=True)
model = TextEmbedding(model_name=name,cache_dir=str(directory),threads=2,providers=['CPUExecutionProvider'])
list(model.embed(['Préparer les modèles au build, sans données utilisateur.']))
(directory/'READY').write_text(name,encoding='utf-8')
print('M2 model prepared:',directory)
