from pydantic import BaseModel, EmailStr
from typing import Optional

class SpecialistCreate(BaseModel):
    name: str
    specialty: str
    password: str

class SpecialistUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    password: Optional[str] = None

class SpecialistOut(BaseModel):
    id: int
    name: str
    specialty: str
