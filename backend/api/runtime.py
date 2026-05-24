from __future__ import annotations

import os
from dataclasses import dataclass

import uvicorn

from backend.config import load_dotenv_if_exists
from backend.workers.asyncio_compat import run_async_worker


@dataclass(frozen=True)
class ApiRuntimeSettings:
    host: str = "127.0.0.1"
    port: int = 8000


def load_api_runtime_settings() -> ApiRuntimeSettings:
    load_dotenv_if_exists()
    return ApiRuntimeSettings(
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
    )


async def main_async() -> None:
    settings = load_api_runtime_settings()
    config = uvicorn.Config(
        "backend.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    run_async_worker(main_async())


if __name__ == "__main__":
    main()
