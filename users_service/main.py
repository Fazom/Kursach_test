from fastapi import FastAPI
from users_service.database import init_db
from .routes.user_routes import router as user_router

app = FastAPI()

# Инициализация базы данных
init_db(app)

# Подключение маршрутов
app.include_router(user_router, prefix="/api/v1", tags=["Users"])


@app.get("/")
async def root():
    return {"message": "Users Service is running!"}
