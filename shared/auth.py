from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from passlib.hash import bcrypt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_admin_user(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return current_user

def hash_password(password: str) -> str:
    """Хеширование пароля с использованием bcrypt."""
    return bcrypt.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля на соответствие хешу."""
    return bcrypt.verify(plain_password, hashed_password)

async def get_admin_specialist(current_user=Depends(get_current_user)):
    if current_user["specialty"] != "admin":
        raise HTTPException(status_code=403, detail="Access forbidden: Admins only")
    return current_user
