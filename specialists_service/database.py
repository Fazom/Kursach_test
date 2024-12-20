import asyncpg
from fastapi import FastAPI

DATABASE_URL = "postgresql://postgres:yalokin4002@localhost/specialists_db"

class Database:
    def __init__(self, database_url):
        self.database_url = database_url
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.database_url)

    async def disconnect(self):
        await self.pool.close()

db = Database(DATABASE_URL)

def init_db(app: FastAPI):
    @app.on_event("startup")
    async def startup():
        await db.connect()

    @app.on_event("shutdown")
    async def shutdown():
        await db.disconnect()
