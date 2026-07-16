"""routers/platform_status.py — expose the 26-module structure over the API."""
from fastapi import APIRouter
from abm_platform import registry

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/modules")
def modules():
    return registry.modules()


@router.get("/health")
def health():
    return {"platform": "ABM Enterprise (26 modules)", **registry.summary(),
            "by_status": registry.by_status()}
