from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.evidence import router as evidence_router
from app.api.generation import router as generation_router
from app.api.health import router as health_router
from app.api.media import router as media_router
from app.api.reviews import router as reviews_router
from app.api.revisions import router as revisions_router
from app.api.sources import router as sources_router
from app.api.transformations import router as transformations_router
from app.errors import register_error_handlers

app = FastAPI(title="SIH26154 Content Transformation MVP", version="0.1.0")
register_error_handlers(app)
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(sources_router, prefix="/api")
app.include_router(transformations_router, prefix="/api")
app.include_router(generation_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(evidence_router, prefix="/api")
app.include_router(revisions_router, prefix="/api")
app.include_router(media_router, prefix="/api")
