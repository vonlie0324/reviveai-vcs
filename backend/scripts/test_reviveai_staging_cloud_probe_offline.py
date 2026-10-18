import importlib.util
from pathlib import Path
p=Path(__file__).with_name('reviveai_staging_cloud_probe.py')
spec=importlib.util.spec_from_file_location('safeprobe',p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for args in [('ai-projects-250716','reviveai-staging','reviveai-staging-bucket','reviveai-recovery-staging-tests/x/'),('separate-staging-project','reviveai-prod','reviveai-staging-bucket','reviveai-recovery-staging-tests/x/'),('separate-staging-project','reviveai-staging','reviveai','reviveai-recovery-staging-tests/x/'),('separate-staging-project','(default)','reviveai-staging-bucket','reviveai-recovery-staging-tests/x/'),('separate-staging-project','reviveai-staging','reviveai-staging-bucket','audio_finishing/audio_real/')]:
    try: m.ensure_safe(*args)
    except ValueError: pass
    else: raise AssertionError('expected fail closed: '+repr(args))
from argparse import Namespace
import os
old=os.environ.pop('FIRESTORE_EMULATOR_HOST',None)
try:
    a=Namespace(project='separate-staging-project',database='reviveai-staging',bucket='reviveai-staging-bucket',prefix='reviveai-recovery-staging-tests/offline/',execute_staging_writes=False,confirm='',report=None)
    result=m.run(a)
    assert result['status']=='DRY_RUN_NO_CLOUD_CLIENTS' and result['executed_cloud_writes']==0
finally:
    if old is not None: os.environ['FIRESTORE_EMULATOR_HOST']=old
print('PASS: production-resource and default-db denial, unsafe-prefix denial, no-client dry run')
print('STAGING CLOUD PROBE: OFFLINE SAFETY PASSED; NO NETWORK OR WRITES')
