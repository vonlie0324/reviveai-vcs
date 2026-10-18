"""
Merge recovered checkpoint costs into existing production cost transactions.

Usage:
    python -m scripts.merge_recovered_costs
"""

from pathlib import Path
import sys
from datetime import datetime, timezone

from google.cloud import firestore


DATABASE = "reviveai-prod"


def add_backend_root():
    root = Path(__file__).resolve().parents[1]

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main():
    add_backend_root()

    db = firestore.Client(database=DATABASE)

    collection = db.collection(
        "production_cost_transactions"
    )

    recovered = []

    print("Scanning recovered cost records...")

    for doc in collection.stream():
        data = doc.to_dict()

        if data.get("source") != "checkpoint_rebuild":
            continue

        recovered.append(
            {
                "id": doc.id,
                "data": data,
            }
        )

    print(
        f"Recovered transactions found: {len(recovered)}"
    )

    updated = 0

    for item in recovered:

        data = item["data"]

        production_id = data.get(
            "productionId"
        )

        if not production_id:
            continue


        recovered_cost = float(
            data.get(
                "estimatedCostUsd",
                0
            )
            or 0
        )


        if recovered_cost <= 0:
            continue


        # Find legacy migration record
        legacy_query = (
            collection
            .where(
                "productionId",
                "==",
                production_id
            )
            .stream()
        )


        found = False

        for legacy_doc in legacy_query:

            legacy = legacy_doc.to_dict()

            # Update legacy record
            collection.document(
                legacy_doc.id
            ).set(
                {
                    "estimatedCost":
                        recovered_cost,

                    "actualCost":
                        recovered_cost,

                    "status":
                        "CHECKPOINT_RECOVERED",

                    "provider":
                        data.get(
                            "provider",
                            "google_veo"
                        ),

                    "model":
                        data.get(
                            "model"
                        ),

                    "providerOperationName":
                        data.get(
                            "providerOperationName"
                        ),

                    "source":
                        "checkpoint_rebuild",

                    "updatedAt":
                        datetime.now(
                            timezone.utc
                        ),
                },
                merge=True,
            )

            updated += 1
            found = True
            break


        if not found:
            # Create normalized transaction
            collection.document(
                f"recovered_{production_id}"
            ).set(
                {
                    "productionId":
                        production_id,

                    "estimatedCost":
                        recovered_cost,

                    "actualCost":
                        recovered_cost,

                    "status":
                        "CHECKPOINT_RECOVERED",

                    "provider":
                        "google_veo",

                    "model":
                        data.get(
                            "model"
                        ),

                    "providerOperationName":
                        data.get(
                            "providerOperationName"
                        ),

                    "source":
                        "checkpoint_rebuild",

                    "updatedAt":
                        datetime.now(
                            timezone.utc
                        ),
                },
                merge=True,
            )

            updated += 1


    print("")
    print(
        "Merge completed"
    )
    print(
        "----------------"
    )
    print(
        "Records updated:",
        updated
    )


if __name__ == "__main__":
    main()