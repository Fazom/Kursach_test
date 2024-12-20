from fastapi import APIRouter, HTTPException, Depends
from typing import List
from ..database import db
from ..models.user import UserCreate, UserUpdate, UserOut
from shared.auth import create_access_token, get_current_user, get_admin_user
from passlib.hash import bcrypt
import asyncpg
from pydantic import BaseModel
from datetime import datetime
import httpx 
from pydantic import Field
import requests
from typing import List

SPECIALISTS_SERVICE_URL = "http://127.0.0.1:8001/api/v1"
PAYMENT_SERVICE_URL = "http://127.0.0.1:8002/api/v1"

# Ваш Telegram Bot API токен
BOT_TOKEN = "7872240184:AAH2D1qDXKha4OLfgmBBGsM_Ox3IODvkbNc"
# URL для отправки сообщения в Telegram
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
# URL вашего API для авторизации
AUTH_API_URL = "http://127.0.0.1:8000/auth/login"



router = APIRouter()
# Модели для логина и ответа

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str

    

class LoginRequest(BaseModel):
    username: str
    password: str

class AppointmentCreateRequest(BaseModel):
    specialist_id: int
    appointment_time: str
    service: str
    card_number: str = Field(..., pattern=r"^\d{16}$")  # 16 цифр
    card_cvv: str = Field(..., pattern=r"^\d{3}$")      # 3 цифры
    card_expiry: str = Field(..., pattern=r"^\d{2}/\d{4}$")


class RescheduleRequest(BaseModel):
    new_time: str

# Функция хеширования пароля
def hash_password(password: str) -> str:
    from passlib.hash import bcrypt
    return bcrypt.hash(password)

@router.post("/users", response_model=UserOut)
async def create_user(user: UserCreate):
    query = """
    INSERT INTO users (username, email, hashed_password)
    VALUES ($1, $2, $3)
    RETURNING id, username, email, role;
    """
    hashed_password = hash_password(user.password)
    try:
        record = await db.pool.fetchrow(query, user.username, user.email, hashed_password)
        return UserOut(**record)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Username or email already exists")


# 1. Получение всех пользователей
@router.get("/users", response_model=List[UserOut])
async def get_users(current_user=Depends(get_admin_user)):
    query = "SELECT id, username, email, role FROM users"
    records = await db.pool.fetch(query)
    return [UserOut(**dict(record)) for record in records]

# 2. Получение пользователя по ID
@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, current_user=Depends(get_current_user)):
    query = "SELECT id, username, email, role FROM users WHERE id = $1"
    record = await db.pool.fetchrow(query, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**record)

# 3. Изменение данных пользователя
@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, user_data: UserUpdate, current_user=Depends(get_current_user)):
    if current_user["id"] != user_id and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # Фильтрация только предоставленных данных
    update_fields = [f"{key} = ${i + 1}" for i, key in enumerate(user_data.dict(exclude_unset=True))]
    if not update_fields:
        raise HTTPException(status_code=400, detail="No data to update")
    
    query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ${len(update_fields) + 1} RETURNING id, username, email, role"
    values = list(user_data.dict(exclude_unset=True).values()) + [user_id]
    
    record = await db.pool.fetchrow(query, *values)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserOut(**record)



# 4. Удаление пользователя
@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user=Depends(get_admin_user)):
    """
    Удаление пользователя и всех его записей
    """
    # Удаление всех записей пользователя из базы данных specialists_db
    query_appointments = "SELECT id, specialist_id, appointment_time FROM appointments WHERE user_id = $1"
    appointments = await db.pool.fetch(query_appointments, user_id)

    async with httpx.AsyncClient() as client:
        for appointment in appointments:
            await client.delete(
                f"{SPECIALISTS_SERVICE_URL}/schedules",
                params={
                    "specialist_id": appointment["specialist_id"],
                    "appointment_time": appointment["appointment_time"].isoformat()
                }
            )

    # Удаление всех записей пользователя из базы данных users_db
    delete_appointments_query = "DELETE FROM appointments WHERE user_id = $1"
    await db.pool.execute(delete_appointments_query, user_id)

    # Удаление самого пользователя
    delete_user_query = "DELETE FROM users WHERE id = $1 RETURNING id"
    user = await db.pool.fetchrow(delete_user_query, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"detail": "User and all related appointments deleted"}


# 5. Авторизация
@router.post("/auth/login")
async def login(credentials: LoginRequest):
    query = "SELECT id, username, hashed_password, role FROM users WHERE username = $1"
    user = await db.pool.fetchrow(query, credentials.username)
    if not user or not bcrypt.verify(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"id": user["id"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}

# 9. Получение всех записей пользователя
@router.get("/appointments")
async def get_user_appointments(current_user=Depends(get_current_user)):
    query = "SELECT * FROM appointments WHERE user_id = $1"
    records = await db.pool.fetch(query, current_user["id"])
    return records

@router.post("/appointments")
async def create_appointment(
    appointment_request: AppointmentCreateRequest,
    current_user=Depends(get_current_user)
):
    """
    Создание записи к специалисту
    """
    specialist_id = appointment_request.specialist_id
    appointment_time = appointment_request.appointment_time
    service = appointment_request.service

    try:
        # Проверка формата времени
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    # Проверка существования специалиста
    async with httpx.AsyncClient() as client:
        specialist_response = await client.get(f"{SPECIALISTS_SERVICE_URL}/specialists/{specialist_id}")
        if specialist_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Specialist not found")

    # Проверка существования услуги
    async with httpx.AsyncClient() as client:
        services_response = await client.get(f"{SPECIALISTS_SERVICE_URL}/specialists/{specialist_id}/services")
        if services_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Failed to fetch services")

        services = services_response.json()
        matching_service = next((s for s in services if s["service_name"] == service), None)
        if not matching_service:
            raise HTTPException(status_code=400, detail="Service not provided by the specialist")

    # Получение цены услуги
    price = matching_service["price"]

    # Оплата услуги
    async with httpx.AsyncClient() as client:
        payment_response = await client.post(
        f"{PAYMENT_SERVICE_URL}/pay",
        json={
            "user_id": current_user["id"],
            "specialist_id": specialist_id,
            "service_name": service,
            "amount": matching_service["price"],
            "card_number": appointment_request.card_number,
            "card_cvv": appointment_request.card_cvv,
            "card_expiry": appointment_request.card_expiry
        }
    )
    if payment_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Payment failed")
    payment_data = payment_response.json()

    if not payment_data.get("success"):
        raise HTTPException(status_code=400, detail="Payment was not successful")

    # Проверка доступности времени
    async with httpx.AsyncClient() as client:
        schedule_response = await client.get(
            f"{SPECIALISTS_SERVICE_URL}/schedules/check",
            params={"specialist_id": specialist_id, "appointment_time": appointment_time.isoformat()}
        )
        if schedule_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Time slot is not available")

    # Добавление записи в расписание специалиста
    async with httpx.AsyncClient() as client:
        add_schedule_response = await client.post(
            f"{SPECIALISTS_SERVICE_URL}/schedules",
            json={"specialist_id": specialist_id, "appointment_time": appointment_time.isoformat(), "service": service}
        )
        if add_schedule_response.status_code != 201:
            raise HTTPException(status_code=500, detail="Failed to add appointment to specialist's schedule")

    # Добавление записи в базу данных appointments
    query = """
    INSERT INTO appointments (user_id, specialist_id, appointment_time, service)
    VALUES ($1, $2, $3, $4)
    RETURNING id, user_id, specialist_id, appointment_time, service
    """
    record = await db.pool.fetchrow(query, current_user["id"], specialist_id, appointment_time, service)
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create appointment")

    return dict(record)





@router.put("/appointments/{appointment_id}")
async def reschedule_appointment(
    appointment_id: int,
    reschedule_request: RescheduleRequest,
    current_user=Depends(get_current_user)
):
    """
    Перенос записи на другое время
    """
    try:
        new_time = datetime.fromisoformat(reschedule_request.new_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid new_time format")

    # Проверка существования записи
    query = "SELECT * FROM appointments WHERE id = $1 AND user_id = $2"
    record = await db.pool.fetchrow(query, appointment_id, current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="Appointment not found or access denied")

    specialist_id = record["specialist_id"]

    # Проверка доступности нового времени
    async with httpx.AsyncClient() as client:
        schedule_response = await client.get(
            f"{SPECIALISTS_SERVICE_URL}/schedules/check",
            params={"specialist_id": specialist_id, "appointment_time": new_time.isoformat()}
        )
        if schedule_response.status_code != 200:
            raise HTTPException(status_code=400, detail="New time slot is not available")

    # Обновление расписания специалиста
    async with httpx.AsyncClient() as client:
        update_schedule_response = await client.put(
            f"{SPECIALISTS_SERVICE_URL}/schedules/{appointment_id}",
            json={"new_time": new_time.isoformat()}
        )
        if update_schedule_response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to update specialist's schedule")

    # Обновление записи в appointments
    update_query = """
    UPDATE appointments
    SET appointment_time = $1
    WHERE id = $2
    RETURNING id, user_id, specialist_id, appointment_time, service
    """
    updated_record = await db.pool.fetchrow(update_query, new_time, appointment_id)
    return dict(updated_record)



@router.delete("/appointments/{appointment_id}")
async def delete_appointment(appointment_id: int, current_user=Depends(get_current_user)):
    """
    Удаление записи
    """
    # Проверка существования записи
    query = "SELECT * FROM appointments WHERE id = $1 AND user_id = $2"
    record = await db.pool.fetchrow(query, appointment_id, current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="Appointment not found or access denied")

    specialist_id = record["specialist_id"]
    appointment_time = record["appointment_time"]

    # Удаление записи из расписания специалиста
    async with httpx.AsyncClient() as client:
        delete_schedule_response = await client.delete(
            f"{SPECIALISTS_SERVICE_URL}/schedules",
            params={"specialist_id": specialist_id, "appointment_time": appointment_time.isoformat()}
        )
        if delete_schedule_response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to delete appointment from specialist's schedule")

    # Удаление записи из appointments
    delete_query = "DELETE FROM appointments WHERE id = $1"
    await db.pool.execute(delete_query, appointment_id)

    return {"detail": "Appointment deleted"}

@router.delete("/appointments")
async def delete_appointments_by_specialist(
    specialist_id: int,
    appointment_time: str
):
    """
    Удаление записей пользователя по специалисту
    """
    delete_query = """
    DELETE FROM appointments
    WHERE specialist_id = $1 AND appointment_time = $2
    """
    await db.pool.execute(delete_query, specialist_id, datetime.fromisoformat(appointment_time))
    return {"detail": "Appointments deleted"}




@router.post("/telegram/login")
async def telegram_login(username: str, password: str):
    """
    Авторизация пользователя через Telegram
    """
    # Отправляем запрос на авторизацию в ваше API
    login_data = {"username": username, "password": password}
    
    # Отправка запроса на авторизацию
    async with httpx.AsyncClient() as client:
        response = await client.post(AUTH_API_URL, json=login_data)
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
    login_response = response.json()
    return login_response  # Возвращаем токен, который пользователь может использовать 