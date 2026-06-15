from fastapi import FastAPI

app = FastAPI(title="personal-hub Cloud Run PoC")


@app.get("/")
async def root():
    return {"status": "ok", "version": "poc"}


@app.get("/healthz")
async def healthz():
    return {"healthy": True}
