from google.cloud import firestore

databases = [
    "(default)",
    "routes",
    "routes-staging",
    "tactic-db",
    "sherlock-memory",
]

for database_id in databases:
    print("\n========================")
    print("DATABASE:", database_id)
    print("========================")

    try:
        db = firestore.Client(
            project="ai-projects-250716",
            database=database_id,
        )

        collections = list(db.collections())

        if not collections:
            print("No collections")

        for c in collections:
            docs = list(c.limit(3).stream())

            print(
                f"Collection: {c.id}, "
                f"sample_count={len(docs)}"
            )

            for doc in docs[:1]:
                print(
                    " Fields:",
                    list(doc.to_dict().keys())
                )

    except Exception as e:
        print("ERROR:", e)