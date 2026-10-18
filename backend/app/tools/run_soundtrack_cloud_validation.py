
"""
CLI foundation for running soundtrack cloud validation.
"""


def validate_all(track_ids, validation_service):
    results = []

    for track_id in track_ids:
        results.append(
            validation_service.validate_track(
                track_id
            )
        )

    return results


if __name__ == "__main__":
    print(
        "Inject Firestore and Cloud Storage services before running."
    )
