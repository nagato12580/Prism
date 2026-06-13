# prism/backend/run.py
import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        host=settings.KMC_HOST,
        port=settings.KMC_PORT,
        reload=False,
    )
