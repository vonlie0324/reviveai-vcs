"""
Restores soundtrack context when a job resumes.
"""


def restore_soundtrack_context(
    job,
    soundtrack_reference,
):
    if not soundtrack_reference:
        return job

    job.soundtrack_id = (
        soundtrack_reference.soundtrack_id
    )

    job.soundtrack_storage_path = (
        soundtrack_reference.storage_path
    )

    return job
