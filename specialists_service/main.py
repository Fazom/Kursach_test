from fastapi import FastAPI
from .database import init_db
from .routes.specialist_routes import router as specialist_router

app = FastAPI()

# Инициализация базы данных
init_db(app)

# Подключение маршрутов
app.include_router(specialist_router, prefix="/api/v1", tags=["Specialists"])

@app.get("/")
async def root():
    return {"message": "Specialists Service is running!"}
