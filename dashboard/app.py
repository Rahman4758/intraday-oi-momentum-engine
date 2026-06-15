from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dashboard.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title='Intraday Momentum System', version='1.0')
    app.mount('/static', StaticFiles(directory='dashboard/static'), name='static')
    app.include_router(router)
    return app
