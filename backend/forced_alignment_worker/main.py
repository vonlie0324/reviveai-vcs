"""Private CPU WhisperX alignment service. Deploy with Cloud Run authentication required."""
import os
import tempfile
import wave
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
lock=Lock()
_model=None

def run_alignment(audio_path, transcript):
    global _model
    import whisperx
    import soundfile as sf
    import numpy as np
    with lock:
        if _model is None:
            _model, metadata=whisperx.load_align_model(language_code='en',device='cpu')
            app.state.metadata=metadata
        signal,sample_rate=sf.read(str(audio_path),dtype='float32')
        if sample_rate != 16000 or signal.ndim != 1:
            raise ValueError('Expected 16 kHz mono WAV')
        # The supplied transcript is approved; no generative transcription step.
        segment={'text':transcript,'start':0.0,'end':len(signal)/sample_rate}
        result=whisperx.align([segment],_model,app.state.metadata,signal,'cpu',return_char_alignments=False)
        words=[]
        for w in result.get('word_segments',[]):
            if not all(k in w for k in ('word','start','end')):
                raise ValueError('Aligner omitted a required word boundary')
            words.append({'word':w['word'],'start':float(w['start']),'end':float(w['end'])})
        return {'words':words,'model':'whisperx-align-en-cpu'}

@app.post('/align')
async def align(audio: UploadFile=File(...),transcript: str=Form(...)):
    if not 1 <= len(transcript.strip()) <= 1000:
        raise HTTPException(422,'Invalid transcript')
    blob=await audio.read(2_000_001)
    if len(blob)>2_000_000:
        raise HTTPException(413,'WAV too large')
    with tempfile.TemporaryDirectory() as tmp:
        f=Path(tmp)/'narration.wav';f.write_bytes(blob)
        try:
            with wave.open(str(f),'rb') as w:
                if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000) or w.getnframes()/16000>30:
                    raise ValueError('Bad WAV format or duration')
            return await run_in_threadpool(run_alignment,f,transcript)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
