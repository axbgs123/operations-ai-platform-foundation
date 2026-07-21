from fastapi import FastAPI

app = FastAPI(title="Operations AI Platform API")


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
