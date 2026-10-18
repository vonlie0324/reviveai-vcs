from types import SimpleNamespace

from app.services.production_recommendation_eligibility import already_started, is_eligible, normalized_title


def rec(title, recommendation_id='recommendation_1', canonical_idea_id=None):
    return SimpleNamespace(title=title, recommendation_id=recommendation_id, canonical_idea_id=canonical_idea_id)


def entry(title, recovery_job_id='legacy_recovery', working_title=None, canonical_idea_id=None):
    return SimpleNamespace(recovery_job_id=recovery_job_id, working_title=working_title,
                           source_snapshot=SimpleNamespace(recommendation=rec(title, canonical_idea_id=canonical_idea_id)))


def test_legacy_title_excluded_across_recovery_runs():
    assert already_started(rec('The Royal Feast Host'), entry('The Royal Feast Host'), 'new_recovery')


def test_same_recommendation_number_is_not_global_match():
    assert is_eligible(rec('First Bark on Mars'), 'new_recovery', [entry('The Royal Feast Host')])


def test_canonical_idea_id_excludes_variant_title():
    assert already_started(rec('Mars Adventure', canonical_idea_id='idea_42'),
                           entry('First Bark on Mars', canonical_idea_id='idea_42'), 'new_recovery')


def test_normalized_title_matches_legacy_spacing():
    assert normalized_title('The Royal Feast — Host!') == normalized_title('The Royal Feast Host')


def test_active_job_from_same_recovery_is_used():
    assert already_started(rec('Other New Title'), entry('Previously Different Title', recovery_job_id='same_recovery'), 'same_recovery')
