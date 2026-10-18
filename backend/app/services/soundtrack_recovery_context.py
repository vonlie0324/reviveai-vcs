"""
Recovery helper for interrupted soundtrack workflows.
"""


def restore_soundtrack_execution(
    checkpoint,
):
    if not checkpoint:
        return None

    return checkpoint.get(
        "soundtrack_execution"
    )
