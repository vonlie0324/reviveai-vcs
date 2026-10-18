from fastapi import APIRouter, Depends, HTTPException

from app.core.firebase_auth import require_tenant_context
from app.services.production_cost_dashboard_service import ProductionCostDashboardService


router = APIRouter(
    prefix="/api/v1/production-costs",
    tags=["production-costs"],
    dependencies=[Depends(require_tenant_context)],
)


@router.get("/dashboard")
async def dashboard():
    """Return the authenticated tenant's production/release cost dashboard."""
    return ProductionCostDashboardService().get_dashboard()


@router.get("/debug/firestore")
async def firestore_debug():
    """Authenticated schema-only Firestore discovery helper.

    Values are deliberately omitted. This endpoint remains useful in development
    without exposing another tenant's data through the production-cost API.
    """
    service = ProductionCostDashboardService()
    result = []
    try:
        for collection in service.db.collections():
            count = 0
            fields = set()
            sample_id = None
            for snap in collection.limit(5).stream():
                count += 1
                sample_id = sample_id or snap.id
                fields.update((snap.to_dict() or {}).keys())
            result.append(
                {
                    "collection": collection.id,
                    "sample_count": count,
                    "sample_id": sample_id,
                    "fields": sorted(fields),
                }
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Firestore discovery failed: {exc}") from exc
    return {"collections": result}


@router.get("/{production_id}/timeline")
async def production_cost_timeline(production_id: str):
    return ProductionCostDashboardService().get_timeline(production_id)


@router.get("/{production_id}")
async def production_cost_detail(production_id: str):
    return ProductionCostDashboardService().get_detail(production_id)
