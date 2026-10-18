from pathlib import Path
import json
import sys
from datetime import datetime, timezone

from google.cloud import firestore

from app.core.config import get_settings


DATABASE = "reviveai-prod"


def add_backend_root():

    root = Path(__file__).resolve().parents[1]

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def load_json(path):

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return {}



def find_operations(obj):

    results = []

    if isinstance(obj, dict):

        if (
            "estimated_cost_usd" in obj
            or "provider_operation_name" in obj
        ):
            results.append(obj)


        for value in obj.values():
            results.extend(
                find_operations(value)
            )


    elif isinstance(obj, list):

        for item in obj:
            results.extend(
                find_operations(item)
            )

    return results



def migrate():


    add_backend_root()


    settings = get_settings()


    checkpoint_root = Path(
        settings.content_dna_checkpoint_dir
    ).resolve()


    source = checkpoint_root / "media_studio"


    print("Checkpoint:")
    print(source)



    db = firestore.Client(
        database=DATABASE
    )


    if not source.exists():

        print(
            "media_studio not found"
        )

        return



    migrated = 0



    for job_file in source.rglob(
        "job.json"
    ):


        data = load_json(
            job_file
        )


        production_id = data.get(
            "production_brief_job_id"
        )


        media_job_id = data.get(
            "job_id"
        )


        if not production_id:
            continue



        snapshot = (
            data
            .get("result", {})
            .get("source_snapshot", {})
        )


        title = (
            snapshot
            .get("working_title")
            or production_id
        )


        identity = (
            snapshot
            .get("production_identity")
            or {}
        )


        detail = (
            data.get(
                "detail"
            )
            or {}
        )


        generation = {

            "aspectRatio":
                detail.get(
                    "aspect_ratio"
                ),

            "videoModel":
                detail.get(
                    "video_model"
                ),

            "imageModel":
                detail.get(
                    "image_model"
                ),

            "fidelityModel":
                detail.get(
                    "fidelity_model"
                ),

            "identityLocked":
                detail.get(
                    "identity_locked"
                ),

            "shots":
                len(
                    snapshot
                    .get(
                        "storyboard",
                        {}
                    )
                    .get(
                        "shots",
                        []
                    )
                )

        }



        operations = find_operations(
            data
        )


        for operation in operations:


            estimated = operation.get(
                "estimated_cost_usd"
            )


            if estimated is None:
                continue



            provider_operation = (
                operation.get(
                    "provider_operation_name"
                )
            )


            document_id = (
                f"veo_{media_job_id}"
            )



            payload = {


                "productionId":
                    production_id,


                "title":
                    title,


                "productionTitle":
                    title,


                "channelId":
                    data.get(
                        "channel_id"
                    ),


                "mediaJobId":
                    media_job_id,


                "provider":
                    "google_veo",


                "model":
                    (
                        operation.get(
                            "model"
                        )
                        or detail.get(
                            "video_model"
                        )
                    ),


                "providerOperationName":
                    provider_operation,


                "estimatedCost":
                    float(
                        estimated
                    ),


                "actualCost":
                    float(
                        estimated
                    ),


                "currency":
                    "USD",


                "status":
                    "CHECKPOINT_RECOVERED",


                "stage":
                    data.get(
                        "stage"
                    ),


                "source":
                    "checkpoint_migration",


                "checkpointPath":
                    str(
                        job_file
                    ),


                "generation":
                    generation,


                "createdAt":
                    data.get(
                        "created_at"
                    ),


                "updatedAt":
                    datetime.now(
                        timezone.utc
                    )

            }



            db.collection(
                "production_cost_transactions"
            ).document(
                document_id
            ).set(
                payload
            )



            migrated += 1



    print("")
    print(
        "Migration completed"
    )

    print(
        "Records created:",
        migrated
    )



if __name__ == "__main__":

    migrate()