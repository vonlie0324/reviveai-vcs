from google.cloud import firestore
from google.cloud import resourcemanager_v3
from google.api_core.exceptions import GoogleAPIError

keywords = [
    "production",
    "media",
    "video",
    "veo",
    "revive",
    "studio",
    "ai",
]

print("Loading projects...")

client = resourcemanager_v3.ProjectsClient()

projects = client.search_projects(
    request={
        "query": "state:ACTIVE"
    }
)

for project in projects:
    project_id = project.project_id
    project_name = project.display_name or ""

    search_text = (
        project_id + " " + project_name
    ).lower()

    if not any(
        k in search_text
        for k in keywords
    ):
        continue

    print("\n========================")
    print("CHECKING")
    print(project_id)
    print(project_name)
    print("========================")

    try:
        db = firestore.Client(
            project=project_id,
            database="(default)"
        )

        collections = list(db.collections())

        for collection in collections:
            name = collection.id.lower()

            if any(
                k in name
                for k in [
                    "production",
                    "media",
                    "video",
                    "veo",
                    "cost",
                    "budget",
                    "asset",
                ]
            ):
                print(
                    "FOUND COLLECTION:",
                    collection.id
                )

    except Exception as e:
        print(
            "SKIPPED:",
            project_id,
            str(e)
        )