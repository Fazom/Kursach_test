from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str
 # Добавляем chat_id для хранения информации о пользователе в базе