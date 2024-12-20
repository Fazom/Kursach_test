import asyncpg
from fastapi import FastAPI

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user="postgres",  
            password="yalokin4002",  
            database="transactions_db",  
            host="localhost",  
            port=5432  
        )

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()
