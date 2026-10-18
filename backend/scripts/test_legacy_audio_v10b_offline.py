"""V10B offline regression tests. Use --records path to the downloaded authoritative JSON."""
import argparse, copy, json, tempfile
from pathlib import Path
from legacy_audio_v10b_records import validate_export, UnsafeRecovery

def main():
    p=argparse.ArgumentParser();p.add_argument('--records',required=True,type=Path);a=p.parse_args()
    original=validate_export(a.records)
    print('PASS: actual approved assembly and brief parsed by backend schemas')
    cases=[('wrong audio identity',lambda x:x.update(audio_job_id='wrong')),
           ('unapproved assembly',lambda x:x['assembly_job']['result'].update(review_status='NEEDS_REVIEW')),
           ('changed source visual',lambda x:x['assembly_job']['result']['final_video'].update(asset_id='other')),
           ('divergent publishing',lambda x:x['production_brief_job']['result']['publishing'].update(youtube_title='changed')),
           ('altered timeline',lambda x:x['assembly_job']['result']['timeline'][0].update(output_duration_seconds=12))]
    for name,mut in cases:
        data=copy.deepcopy(original);mut(data)
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'bad.json';f.write_text(json.dumps(data),encoding='utf-8')
            try:validate_export(f)
            except (UnsafeRecovery,ValueError):print('PASS: rejects '+name)
            else:raise AssertionError('Failed to block '+name)
    print('ALL 6 V10B OFFLINE CHECKS PASSED; NO CLOUD CLIENTS OR PRODUCTION WRITES')
if __name__=='__main__':main()
