from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.config import get_settings
from app.security import add_security_headers


def create_app() -> FastAPI:
    settings = get_settings()
    es_local = settings.entorno == "local"
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if es_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if es_local else None,
    )
    add_security_headers(app, es_local)
    app.include_router(auth_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
