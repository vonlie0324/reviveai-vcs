"""V9B offline contracts. No GCP import, network calls, or production writes."""
from __future__ import annotations
import gzip, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

JOB = 'audio_821f2a568f804076b10fa4364793385c'
VISUAL = 'final_f9c1a20be9ca4526a42f4d112c9efb46'

class UnsafeRecovery(ValueError): pass

def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()

def local_artifacts(preview: Path):
    report=json.loads((preview/'recovery-report.json').read_text(encoding='utf-8'))
    if report.get('job_id')!=JOB or report.get('source_visual_asset_id')!=VISUAL:
        raise UnsafeRecovery('job or visual master mismatch')
    if report.get('music',{}).get('preset')!='CINEMATIC_AMBIENT':
        raise UnsafeRecovery('soundtrack approval preset mismatch')
    output={}
    for name in ('local-preview-mix.m4a','local-preview-delivery.mp4'):
        data=(preview/name).read_bytes()
        record=report.get(name, {})
        if sha(data)!=record.get('sha256') or len(data)!=record.get('size_bytes') or abs(float(record.get('duration',0))-15)>0.35:
            raise UnsafeRecovery('invalid artifact: '+name)
        output[name]=data
    return report,output

def validate_live(snapshot):
    job=snapshot.get('audio_job') or {}
    session=(snapshot.get('autopilot') or {}).get('session') or {}
    if job.get('job_id')!=JOB or job.get('stage')!='RENDERING' or job.get('result') is not None:
        raise UnsafeRecovery('unexpected job state')
    if (job.get('detail') or {}).get('source_visual_asset_id')!=VISUAL or (job.get('detail') or {}).get('render_checkpoint'):
        raise UnsafeRecovery('unexpected job lineage/checkpoint')
    if session.get('currentAudioJobId')!=JOB or session.get('currentPublicationId'):
        raise UnsafeRecovery('publication or active audio mismatch')
    return job

def build_result(job, assembly_result, production_audio_direction, artifacts, *, now=None):
    """Build a full schema-compatible AudioFinishingResult dictionary; caller validates with Pydantic.
    Production publishing package is copied verbatim from approved assembly, never invented.
    """
    if job.get('job_id')!=JOB or job.get('stage')!='RENDERING': raise UnsafeRecovery('job changed')
    if assembly_result.get('review_status')!='APPROVED': raise UnsafeRecovery('assembly not approved')
    final=assembly_result.get('final_video') or {}
    if final.get('asset_id')!=VISUAL: raise UnsafeRecovery('assembly visual mismatch')
    if job.get('assembly_job_id')!=artifacts['assembly_job_id']:raise UnsafeRecovery('assembly relation mismatch')
    if job.get('production_brief_job_id')!=artifacts['production_brief_job_id']:raise UnsafeRecovery('brief relation mismatch')
    if not isinstance(assembly_result.get('publishing'),dict):raise UnsafeRecovery('publishing package unavailable')
    options=dict(job.get('options') or {})
    if not options.get('voiceover_enabled') or not options.get('music_enabled'): raise UnsafeRecovery('original audio options mismatch')
    options.update(music_source='REVIVEAI',music_preset='CINEMATIC_AMBIENT',youtube_audio_library_track_id=None,trending_track_id=None)
    cues=[]; cursor=0.0
    stems=(job.get('detail') or {}).get('narration_stems') or []
    timeline=assembly_result.get('timeline') or []
    if len(stems)!=4 or len(timeline)!=4:raise UnsafeRecovery('unexpected narration/timeline count')
    for item,stem in zip(timeline,stems):
        duration=float(item['output_duration_seconds'])
        if item['shot_number']!=stem['shot_number'] or abs(duration-float(stem['duration_seconds']))>0.01:
            raise UnsafeRecovery('shot alignment mismatch')
        cues.append({'shot_number':item['shot_number'],'start_seconds':cursor,'duration_seconds':duration,'text':stem['text'],'synthesized':True})
        cursor+=duration
    if abs(cursor-15)>0.35 or abs(float(assembly_result['total_duration_seconds'])-cursor)>0.35:
        raise UnsafeRecovery('timeline duration mismatch')
    timestamp=(now or datetime.now(timezone.utc)).isoformat()
    def asset(prefix, kind, filename, mime):
        entry=artifacts[prefix]
        return {'asset_id':entry['asset_id'],'kind':kind,'created_at':timestamp,'filename':filename,'mime_type':mime,'asset_url':f'/api/v1/youtube/audio-jobs/{JOB}/assets/{entry["asset_id"]}','gcs_uri':entry['gcs_uri']}
    result={
        'assembly_job_id':job['assembly_job_id'],'production_brief_job_id':job['production_brief_job_id'],
        'media_job_id':job['media_job_id'],'working_title':assembly_result['working_title'],
        'rendered_at':timestamp,'total_duration_seconds':cursor,
        'delivery_video':asset('delivery','FINAL_VIDEO',artifacts['delivery']['filename'],'video/mp4'),
        'audio_mix':asset('mix','AUDIO_MIX',artifacts['mix']['filename'],'audio/mp4'),
        'subtitles':None,'publishing':assembly_result['publishing'],'options':options,
        'layers':[{'key':'music','label':'ReviveAI generated music bed','enabled':True,'generated':True,'detail':'CINEMATIC_AMBIENT; operator approved for production QC and potential publication'},
                  {'key':'ambience','label':'Ambience + SFX','enabled':True,'generated':True,'detail':'ROOM generated ambience; specific SFX not verified'},
                  {'key':'voiceover','label':'Voiceover','enabled':True,'generated':True,'detail':'Original saved TTS narration stems reused; no new TTS'}],
        'voiceover_cues':cues,'audio_direction':production_audio_direction,'ambience_profile':'ROOM',
        'effective_tts_voice':str((job.get('detail') or {}).get('tts_voice') or ''),
        'effective_music_preset':'CINEMATIC_AMBIENT','effective_music_source':'REVIVEAI',
        'selected_trending_track':None,'selected_youtube_audio_library_track':None,
        'review_status':'NEEDS_REVIEW','reviewed_at':None,
        'warnings':['Speech alignment for shots 2/3 UNVERIFIED; do not label subtitles speech verified',
                    'No reconstructed SRT attached; caption delivery must be reviewed',
                    'Generated CINEMATIC_AMBIENT replacement authorized for QC/potential publication; final rights/QC checks required'],
    }
    return result

class FakeCreateOnlyObjects:
    def __init__(self):self.objects={}
    def upload(self,key: str,data: bytes,*,if_generation_match: int,expected_sha: str):
        if if_generation_match!=0:raise UnsafeRecovery('create-only precondition required')
        if sha(data)!=expected_sha:raise UnsafeRecovery('upload bytes differ')
        if key in self.objects:raise UnsafeRecovery('object already exists')
        self.objects[key]=(bytes(data),1)
        return {'generation':1,'sha256':sha(data)}

class FakeChunkedJobCAS:
    """Offline simulation of parent manifest fencing. Not a production Firestore transaction."""
    def __init__(self, job: dict, *, chunked: bool=False):
        self.version=1;self.chunked=chunked;self.payload=json.loads(json.dumps(job));self.chunks={}
    def snapshot(self):return (self.version,json.loads(json.dumps(self.payload)))
    def update(self,version,expected_job_id,result,owner_valid=True):
        if not owner_valid or version!=self.version:raise UnsafeRecovery('ownership/CAS conflict')
        if self.payload.get('job_id')!=expected_job_id or self.payload.get('stage')!='RENDERING' or self.payload.get('result') is not None:
            raise UnsafeRecovery('state conflict')
        next_payload=json.loads(json.dumps(self.payload));next_payload['result']=result;next_payload['stage']='COMPLETED'
        next_payload['progress_current']=next_payload.get('progress_total',5)
        next_payload['detail']={**next_payload.get('detail',{}),'render_checkpoint':{'version':1,'state':'COMPLETED','recovery':'V9B_SIMULATED'}}
        serialized=json.dumps(next_payload,separators=(',',':')).encode()
        if self.chunked:
            comp=gzip.compress(serialized)
            gen=uuid4().hex
            # stage independently; only parent switch makes bytes authoritative
            self.chunks[gen]=comp
            if gzip.decompress(comp)!=serialized:raise UnsafeRecovery('chunk integrity')
        self.payload=next_payload;self.version+=1
        return self.snapshot()
