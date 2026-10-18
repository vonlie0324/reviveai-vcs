"""Static integration-contract checks for autonomous motion-correction wiring.

These intentionally do not call Google providers or Firestore. Run the project's
existing runtime tests as well before any paid recovery attempt.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app'


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_autonomous_regeneration_default_enabled_but_configurable():
    code = read('core/config.py')
    assert 'autopilot_allow_regeneration: bool = True' in code
    assert 'video_budget_enforced' in code


def test_corrective_instruction_is_passed_into_generation_prompt():
    code = read('services/media_generation_service.py')
    tree = ast.parse(code)
    methods = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    video_prompt = next(n for n in methods if n.name == 'video_prompt')
    generation = next(n for n in methods if n.name == 'generate_video_clip')
    assert 'corrective_instruction' in [n.arg for n in video_prompt.args.args]
    assert 'corrective_instruction' in [n.arg for n in generation.args.kwonlyargs]
    assert 'REGENERATION CORRECTION' in code
    assert 'prompt = self.video_prompt(source, shot, corrective_instruction=corrective_instruction)' in code


def test_rejected_clip_regeneration_does_not_get_short_circuited_by_adoption():
    code = read('services/media_studio_job_service.py')
    assert 'if old is None and recover_existing_veo_clip(job_id, shot_number, settings):' in code
    assert 'corrective_instruction=creator_note' in code


def test_legacy_exhaustion_resume_checks_verdict_and_attempt_budget():
    code = read('services/autopilot_supervisor_service.py')
    assert 'verdict == "REGENERATE"' in code
    assert 'int(unapproved.generation_attempt) < 3' in code
    assert 'await self._regenerate_clip(media_job.job_id, unapproved.shot_number, instruction)' in code


def test_review_disabled_branch_records_terminal_operation():
    code = read('api/routes/ai_review.py')
    branch = code.split('if not settings.autopilot_allow_regeneration:', 1)[1].split('if clip.generation_attempt >= MAX_CLIP_ATTEMPTS:', 1)[0]
    assert '"status": "BLOCKED"' in branch
    assert '"finished_at": now' in branch
