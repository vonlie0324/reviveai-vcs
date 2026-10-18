#!/usr/bin/env python3
"""One-time, LOCAL-ONLY recovery preview. No app import, Firestore or GCS writes."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import os
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

JOB = 'audio_821f2a568f804076b10fa4364793385c'
TENANT = '61cf44d3ae8277b1f9d2aa781d87e52d'
BASE = f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}'
ASSET_BASE = f'{BASE}/audio_finishing/{JOB}/assets'
VISUAL_NAME = 'final_f9c1a20be9ca4526a42f4d112c9efb46.mp4'
VISUAL_URI = f'{BASE}/final_assembly/assembly_46ec7d635b884406b41761be3261c22b/assets/{VISUAL_NAME}'
DURATIONS = (3., 3., 4., 5.)

class BackgroundMusicPreset(Enum):
    AUTO = 'AUTO'
    CINEMATIC_AMBIENT = 'CINEMATIC_AMBIENT'
    WARM_INSPIRATIONAL = 'WARM_INSPIRATIONAL'
    MODERN_PULSE = 'MODERN_PULSE'
    REFLECTIVE = 'REFLECTIVE'
    BRIGHT_UPBEAT = 'BRIGHT_UPBEAT'

def resolve_gcloud():
    """Resolve the Windows .cmd shim explicitly; never use shell=True."""
    candidates = ('gcloud.cmd', 'gcloud.exe', 'gcloud') if os.name == 'nt' else ('gcloud',)
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(
        'Google Cloud CLI not found from Python. In Git Bash run: '
        'where.exe gcloud ; where.exe gcloud.cmd. '
        'You may alternatively download the five assets yourself and use --source-dir.'
    )

def cmd(args, timeout=240):
    args = [str(a) for a in args]
    if args and args[0] == 'gcloud':
        args[0] = resolve_gcloud()
    try:
        subprocess.run(args, check=True, timeout=timeout, stdout=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(f'Executable not found: {args[0]}. Check Windows PATH.') from exc

def probe(path, ffprobe):
    result = subprocess.run([ffprobe, '-v','error','-show_streams','-show_format','-of','json',str(path)], capture_output=True,text=True,check=True,timeout=30)
    data = json.loads(result.stdout)
    duration = float(data.get('format',{}).get('duration') or 0)
    return duration, {s.get('codec_type') for s in data.get('streams', [])}

def load_original_audio_functions(root):
    """Compile only selected pure media functions; do not import ReviveAI application."""
    src = root / 'app/services/audio_finishing_job_service.py'
    tree = ast.parse(src.read_text(encoding='utf-8'))
    names = {'_music_preset_spec','_generate_music_bed','_prepare_trending_music_bed','_generate_ambience','_mix_audio_buses','_mux_delivery'}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {f.name for f in functions} == names, 'Original mixer functions changed; refusing'
    # Construct an isolated namespace, without module imports or runtime clients.
    env = {'Path':Path, 'Optional':__import__('typing').Optional, 'BackgroundMusicPreset':BackgroundMusicPreset,'_run':cmd}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(src),'exec'),env)
    return env

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main(argv=None):
    p=argparse.ArgumentParser(description='ReviveAI V6 offline preview ONLY. Never writes cloud data.')
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--source-dir',type=Path, help='Use already downloaded visual and stems instead of gcloud cp')
    choice=p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--music-file',type=Path,help='Locally supplied approved/licensed soundtrack, chosen by operator')
    choice.add_argument('--generated-music-preset',choices=[x.value for x in BackgroundMusicPreset if x != BackgroundMusicPreset.AUTO],help='EXPLICITLY approve a generated instrumental as SUBSTITUTE, not original selection')
    p.add_argument('--approved-music-note',required=True,help='Track ID/license confirmation, or approval note for generated substitution')
    p.add_argument('--ffmpeg',default=shutil.which('ffmpeg'))
    p.add_argument('--ffprobe',default=shutil.which('ffprobe'))
    a=p.parse_args(argv)
    if not a.ffmpeg or not a.ffprobe:p.error('ffmpeg and ffprobe are required')
    if len(a.approved_music_note.strip())<8:p.error('Provide a meaningful music choice/rights note')
    dest=a.output_dir.resolve()
    if dest.exists() and any(dest.iterdir()):p.error('output-dir must be empty to avoid overwriting assets')
    dest.mkdir(parents=True,exist_ok=True)
    src=a.source_dir.resolve() if a.source_dir else dest/'downloaded'
    src.mkdir(parents=True,exist_ok=True)
    assets=[(VISUAL_NAME,VISUAL_URI)]+[(f'narration-shot-{i:02d}.wav',f'{ASSET_BASE}/narration-shot-{i:02d}.wav') for i in range(1,5)]
    for name,uri in assets:
        path=src/name
        if not a.source_dir:
            cmd(['gcloud','storage','cp',uri,str(path)],timeout=180)
        if not path.is_file() or path.stat().st_size<1000:raise RuntimeError(f'Missing or empty source: {name}')
    manifest={'job_id':JOB,'mode':'LOCAL_DRY_RUN_NO_CLOUD_WRITES','source_visual_asset_id':VISUAL_NAME[:-4], 'sources':{},'warnings':['Original auto-selected music ID was not persisted; preview music requires operator approval','Speech word alignment for shots 2 and 3 remains UNVERIFIED; never label reconstructed captions speech verified','This preview does not update the Autopilot, job checkpoint, or asset registry.']}
    for name,_ in assets:
        duration,streams=probe(src/name,a.ffprobe)
        required='video' if name.endswith('.mp4') else 'audio'
        if duration<=0 or required not in streams:raise RuntimeError(f'Invalid source {name}: {duration}, {streams}')
        if name.startswith('narration-shot-'):
            shot=int(name[len('narration-shot-'):len('narration-shot-')+2])
            if abs(duration-DURATIONS[shot-1])>0.5:
                raise RuntimeError(f'Unexpected narration duration for shot {shot}: {duration}s')
        manifest['sources'][name]={'duration':duration,'size_bytes':(src/name).stat().st_size,'sha256':checksum(src/name)}
    vdur=manifest['sources'][VISUAL_NAME]['duration']
    if abs(vdur-sum(DURATIONS))>1.0:raise RuntimeError(f'Visual duration {vdur} differs from shot timeline 15s')
    root=Path(__file__).resolve().parents[1]
    audio=load_original_audio_functions(root)
    voice_segments=[]
    for i,shot_duration in enumerate(DURATIONS,1):
        stem=src/f'narration-shot-{i:02d}.wav'
        out=dest/f'voice-segment-{i:02d}.wav'
        cmd([a.ffmpeg,'-y','-i',str(stem),'-af',f'apad,atrim=0:{shot_duration:.3f},afade=t=out:st={shot_duration-0.12:.3f}:d=0.12','-ar','44100','-ac','2','-c:a','pcm_s16le',str(out)])
        voice_segments.append(out)
    # Concat in exact shot order, using decoded audio filter; no additional TTS calls.
    voice=dest/'voiceover.wav'
    cmd([a.ffmpeg,'-y', *sum((['-i',str(f)] for f in voice_segments),[]), '-filter_complex', ''.join(f'[{i}:a]' for i in range(4))+'concat=n=4:v=0:a=1[out]','-map','[out]','-ar','44100','-ac','2','-c:a','pcm_s16le',str(voice)])
    ambience=dest/'ambience.wav'
    audio['_generate_ambience'](a.ffmpeg,ambience,15.,'ROOM')
    music=dest/'music-bed.wav'
    if a.music_file:
        music_file=a.music_file.resolve()
        if not music_file.is_file():raise RuntimeError('Approved music file not found')
        md,streams=probe(music_file,a.ffprobe)
        if md<=0 or 'audio' not in streams:raise RuntimeError('Invalid selected music file')
        audio['_prepare_trending_music_bed'](a.ffmpeg,music_file,music,15.)
        manifest['music']={'type':'operator_selected_licensed_file','file_sha256':checksum(music_file),'approval_note':a.approved_music_note}
    else:
        audio['_generate_music_bed'](a.ffmpeg,music,15.,BackgroundMusicPreset(a.generated_music_preset))
        manifest['music']={'type':'explicitly_approved_generated_substitute','preset':a.generated_music_preset,'approval_note':a.approved_music_note}
    mix=dest/'local-preview-mix.m4a'
    opts=SimpleNamespace(music_volume=.55,voice_volume=1.,ambience_volume=.7,duck_music_during_voiceover=True)
    audio['_mix_audio_buses'](a.ffmpeg,mix,15.,-16.,opts,music_path=music,voice_path=voice,ambience_path=ambience)
    preview=dest/'local-preview-delivery.mp4'
    audio['_mux_delivery'](a.ffmpeg,src/VISUAL_NAME,mix,preview)
    for path,required in ((mix,{'audio'}),(preview,{'audio','video'})):
        dur,streams=probe(path,a.ffprobe)
        if abs(dur-15.)>0.8 or not required.issubset(streams):raise RuntimeError(f'Output validation failed: {path.name}: {dur}, {streams}')
        manifest[path.name]={'duration':dur,'sha256':checksum(path),'size_bytes':path.stat().st_size}
    (dest/'recovery-report.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('PASS: LOCAL ONLY preview validated; no Firestore writes, uploads, or provider generation')
    print('Preview:',preview)
    print('Report:',dest/'recovery-report.json')
    print('STOP: No commit workflow is included. Human review of preview and QC is mandatory.')

if __name__=='__main__':main()
