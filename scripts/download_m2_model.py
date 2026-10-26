"""Build-time model preparation without a database or Django settings import."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from dotenv import load_dotenv
load_dotenv(root/'.env')
from teams.encoder import prepare, Encoder
directory = Path(os.environ.get('M2_MODEL_CACHE',str(root/'.cache'/'m2-model')))
prepare(directory)
list(Encoder(directory).embed(['Prepare the model at build time, without user data.']))
print('M2 model prepared:',directory)
