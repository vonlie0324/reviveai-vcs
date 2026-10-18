"""
Checkpoint persistence for soundtrack execution state.
"""


def save_soundtrack_checkpoint(
    checkpoint: dict,
    execution_state: dict,
):
    return {
        **checkpoint,
        "soundtrack_execution": execution_state,
    }


def restore_soundtrack_checkpoint(
    checkpoint: dict,
):
    return checkpoint.get(
        "soundtrack_execution"
    )
