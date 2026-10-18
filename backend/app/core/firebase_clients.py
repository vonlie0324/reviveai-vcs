"""
Firebase / Google Cloud client factories.

`get_firestore_client()` keeps the application's existing default-database behavior
for services that already depend on it.

`get_runtime_firestore_client()` is used by the new durable ReviveAI runtime/job
store and honors FIRESTORE_DATABASE_ID so localhost and Cloud Run can share the
same named database without changing unrelated Firestore integrations.
"""

from functools import lru_cache

from app.core.config import get_settings


@lru_cache()
def get_firestore_client():
    from google.cloud import firestore

    return firestore.Client()


@lru_cache()
def get_runtime_firestore_client():
    from google.cloud import firestore

    settings = get_settings()
    project = (settings.effective_firebase_project_id or "").strip() or None
    database = (settings.firestore_database_id or "(default)").strip() or "(default)"

    kwargs = {"database": database}
    if project:
        kwargs["project"] = project

    return firestore.Client(**kwargs)


@lru_cache()
def get_storage_client():
    from google.cloud import storage

    return storage.Client()
