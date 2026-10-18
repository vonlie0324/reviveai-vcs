"""Self-contained fake GCS tests: NO network or cloud imports."""
from __future__ import annotations
import hashlib,tempfile
from pathlib import Path
from reviveai_recovery_gcs_adapter import stage_verified,ArtifactMismatch,parse_gs_uri

class Conflict(Exception):
    code=412
class Bucket:
    name='reviveai'
    def __init__(self):self.data={};self.next=2;self.corrupt=False
    def blob(self,name,generation=None):return Blob(self,name,generation)
    def get_blob(self,name):return Blob(self,name,self.data[name][0]) if name in self.data else None
class Blob:
    def __init__(self,bucket,name,generation):self.bucket=bucket;self.name=name;self.generation=generation
    def upload_from_string(self,data,content_type,if_generation_match):
        assert if_generation_match==0
        if self.name in self.bucket.data:raise Conflict()
        self.bucket.data[self.name]=(self.bucket.next,data)
        self.bucket.next+=1
    def download_as_bytes(self):
        current,data=self.bucket.data[self.name]
        if self.generation!=current:raise ArtifactMismatch('Generation changed during read')
        return data+b'corrupted' if self.bucket.corrupt else data

def refuse(fn):
    try:fn()
    except (ArtifactMismatch,ValueError):return
    raise AssertionError('Unsafe input was accepted')

def main():
    raw=b'recovered audio, immutable';sha=hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/'mix.m4a';p.write_bytes(raw)
        b=Bucket();prefix='videos/runtime-artifacts/tenants/test/audio_finishing/synthetic/assets/'
        uri='gs://reviveai/'+prefix+'mix.m4a'
        kw=dict(uri=uri,path=p,expected_sha256=sha,expected_size=len(raw),prefix=prefix,content_type='audio/mp4')
        x=stage_verified(b,**kw);assert x['status']=='CREATED' and x['generation']==2
        x=stage_verified(b,**kw);assert x['status']=='EXISTING_VERIFIED' and x['generation']==2
        refuse(lambda:stage_verified(b,**{**kw,'expected_sha256':'0'*64}))
        refuse(lambda:stage_verified(b,**{**kw,'prefix':'videos/runtime-artifacts/tenants/other/'}))
        b.corrupt=True;refuse(lambda:stage_verified(b,**kw));b.corrupt=False
        refuse(lambda:parse_gs_uri('gs://reviveai/x/../y'))
        refuse(lambda:parse_gs_uri('gs://reviveai/x\\evil'))
        # Not a 412: must propagate rather than pretend we can reconcile.
        class Unauthorized(Exception):code=403
        def fail(*a,**k):raise Unauthorized()
        blob=b.blob; b.blob=lambda *a,**k: type('ErrBlob',(),{'upload_from_string':fail})()
        try:stage_verified(b,**kw)
        except Unauthorized: pass
        else:raise AssertionError('403 swallowed')
        b.blob=blob
    print('PASS: create-only, exact generation, remote hashes, idempotency, tenant scope, corruption, 403 fail closed')
    print('OFFLINE GCS ADAPTER: 8 SAFETY SCENARIOS PASSED; NO CLOUD CLIENTS OR NETWORK')
if __name__=='__main__':main()
