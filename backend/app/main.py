from fastapi import FastAPI

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    es_local = settings.entorno == "local"
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if es_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if es_local else None,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
