
"""
Execute soundtrack migration.

Uploads local soundtrack files and creates registry records.
"""


def execute(files, migration_service):
    results = []

    for file in files:
        results.append(
            migration_service.migrate_local_track(
                file
            )
        )

    return {
        "processed": len(results),
        "results": results,
    }


if __name__ == "__main__":
    print(
        "Configure migration service before execution."
    )
