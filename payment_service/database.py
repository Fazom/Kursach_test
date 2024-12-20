import asyncpg
from fastapi import FastAPI

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user="postgres",  # Замените на ваше имя пользователя PostgreSQL
            password="yalokin4002",  # Замените на ваш пароль
            database="transactions_db",  # Имя базы данных
            host="localhost",  # Адрес сервера базы данных
            port=5432  # Порт PostgreSQL
        )

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()
