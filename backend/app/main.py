from fastapi import FastAPI

from app.api.health import router as health_router
from app.errors import register_error_handlers
from app.logging_config import configure_logging
from app.settings import get_settings

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="SIH26154 Content Transformation MVP", version="0.1.0")
register_error_handlers(app)
app.include_router(health_router, prefix="/api")
