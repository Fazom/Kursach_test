from fastapi import FastAPI
from .routes.payment_routes import router
from .database import db

app = FastAPI()

@app.on_event("startup")
async def startup():
    """
    Подключение к базе данных при запуске сервера
    """
    await db.connect()

@app.on_event("shutdown")
async def shutdown():
    """
    Отключение от базы данных при завершении работы сервера
    """
    await db.disconnect()

app.include_router(router, prefix="/api/v1")
