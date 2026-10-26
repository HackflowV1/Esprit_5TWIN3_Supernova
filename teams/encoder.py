"""Small English MiniLM ONNX encoder; local-only serving, single-text batches."""
from pathlib import Path
from threading import Lock

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REPOSITORY = 'Xenova/all-MiniLM-L6-v2'
REVISION = '751bff37182d3f1213fa05d7196b954e230abad9'
FILES = ('onnx/model_quantized.onnx','tokenizer.json','config.json')


def model_directory(cache):
    return Path(cache)/'english-minilm-l6-q8'


def prepare(cache):
    import shutil
    from huggingface_hub import hf_hub_download
    target=model_directory(cache)
    target.mkdir(parents=True,exist_ok=True)
    for filename in FILES:
        cached=hf_hub_download(REPOSITORY,filename,revision=REVISION,cache_dir=str(Path(cache)/'downloads'),token=False)
        destination=target/filename
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(cached,destination)
    Path(cache,'READY').write_text(MODEL,encoding='utf-8')
    return target


class Encoder:
    def __init__(self,cache):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        directory=model_directory(cache)
        self.np=np
        self.tokenizer=Tokenizer.from_file(str(directory/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=128)
        options=ort.SessionOptions()
        options.intra_op_num_threads=1
        options.inter_op_num_threads=1
        options.enable_cpu_mem_arena=False
        options.enable_mem_pattern=False
        self.session=ort.InferenceSession(str(directory/'onnx/model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.input_names=[item.name for item in self.session.get_inputs()]
        self.lock=Lock()

    def embed(self,texts,batch_size=1):
        # Ignore larger requested batches: bound activation memory on 512 MB hosts.
        for text in texts:
            with self.lock:
                encoded=self.tokenizer.encode(text)
                values={'input_ids':self.np.array([encoded.ids],dtype=self.np.int64),
                    'attention_mask':self.np.array([encoded.attention_mask],dtype=self.np.int64),
                    'token_type_ids':self.np.array([encoded.type_ids],dtype=self.np.int64)}
                hidden=self.session.run(None,{name:values[name] for name in self.input_names})[0]
                mask=values['attention_mask'].astype(self.np.float32)[...,None]
                vector=(hidden*mask).sum(axis=1)/self.np.maximum(mask.sum(axis=1),1e-9)
                normalized=vector[0]/max(self.np.linalg.norm(vector[0]),1e-12)
            yield normalized
