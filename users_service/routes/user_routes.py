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
import logging


# Настройка логирования
logger = logging.getLogger("users_service")
logger.setLevel(logging.INFO)

# Обработчик для записи в файл с кодировкой UTF-8
file_handler = logging.FileHandler("user_service.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Обработчик для вывода в консоль с кодировкой UTF-8
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))

# Добавление обработчиков к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)


SPECIALISTS_SERVICE_URL = "http://127.0.0.1:8001/api/v1"
PAYMENT_SERVICE_URL = "http://127.0.0.1:8002/api/v1"





router = APIRouter()

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
    logger.info(f"Attempt to create user: {user.username}")  
    query = """
    INSERT INTO users (username, email, hashed_password)
    VALUES ($1, $2, $3)
    RETURNING id, username, email, role;
    """
    hashed_password = hash_password(user.password)
    try:
        # Выполнение запроса на добавление пользователя в базу данных
        record = await db.pool.fetchrow(query, user.username, user.email, hashed_password)
        logger.info(f"User {user.username} successfully created")  
        return UserOut(**record)
    except asyncpg.UniqueViolationError:
        logger.error(f"Error: User with username {user.username} already exists")  
        raise HTTPException(status_code=400, detail="Username or email already exists")



# 1. Получение всех пользователей
@router.get("/users", response_model=List[UserOut])
async def get_users(current_user=Depends(get_admin_user)):
    logger.info("Attempting to retrieve all users") 
    
    try:
        query = "SELECT id, username, email, role FROM users"
        records = await db.pool.fetch(query)
        
        logger.info(f"Retrieved {len(records)} users from the database") 
        return [UserOut(**dict(record)) for record in records]
    
    except Exception as e:
        logger.error(f"Error occurred while retrieving users: {e}")
        raise HTTPException(status_code=400, detail="Failed to retrieve users")

# 2. Получение пользователя по ID
@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, current_user=Depends(get_current_user)):
    try:
        logger.info(f"Attempting to retrieve user with ID: {user_id}")
        query = "SELECT id, username, email, role FROM users WHERE id = $1"
        record = await db.pool.fetchrow(query, user_id)
        
        if not record:
            logger.warning(f"User with ID {user_id} not found")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"User with ID {user_id} retrieved successfully")
        return UserOut(**record)
    
    except Exception as e:
        logger.error(f"Error occurred while retrieving user with ID {user_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to retrieve user")

# 3. Изменение данных пользователя
@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, user_data: UserUpdate, current_user=Depends(get_current_user)):
    try:
        logger.info(f"Attempting to update user with ID: {user_id}")
        if current_user["id"] != user_id and current_user["role"] != "admin":
            logger.warning(f"User {current_user['username']} is not authorized to update user {user_id}")
            raise HTTPException(status_code=403, detail="Forbidden")
        
        # Фильтрация только предоставленных данных
        update_fields = [f"{key} = ${i + 1}" for i, key in enumerate(user_data.dict(exclude_unset=True))]
        if not update_fields:
            logger.warning(f"No data provided to update for user ID {user_id}")
            raise HTTPException(status_code=400, detail="No data to update")
        
        query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ${len(update_fields) + 1} RETURNING id, username, email, role"
        values = list(user_data.dict(exclude_unset=True).values()) + [user_id]
        
        record = await db.pool.fetchrow(query, *values)
        if not record:
            logger.warning(f"User with ID {user_id} not found for update")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"User with ID {user_id} updated successfully")
        return UserOut(**record)

    except Exception as e:
        logger.error(f"Error occurred while updating user with ID {user_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to update user")

# 4. Удаление пользователя
@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user=Depends(get_admin_user)):
    try:
        logger.info(f"Attempting to delete user with ID: {user_id}")
        
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
        
        # Удаление пользователя
        delete_user_query = "DELETE FROM users WHERE id = $1 RETURNING id"
        user = await db.pool.fetchrow(delete_user_query, user_id)
        if not user:
            logger.warning(f"User with ID {user_id} not found for deletion")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"User with ID {user_id} and all related appointments deleted successfully")
        return {"detail": "User and all related appointments deleted"}
    
    except Exception as e:
        logger.error(f"Error occurred while deleting user with ID {user_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to delete user")



# 5. Авторизация
@router.post("/auth/login")
async def login(credentials: LoginRequest):
    logger.info(f"Attempting to login user: {credentials.username}")
    try:
        query = "SELECT id, username, hashed_password, role FROM users WHERE username = $1"
        user = await db.pool.fetchrow(query, credentials.username)
        
        if not user or not bcrypt.verify(credentials.password, user["hashed_password"]):
            logger.warning(f"Invalid credentials for user: {credentials.username}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        token = create_access_token({"id": user["id"], "role": user["role"]})
        logger.info(f"User {credentials.username} successfully authenticated")
        
        return {"access_token": token, "token_type": "bearer"}
    
    except Exception as e:
        logger.error(f"Error occurred during login attempt for user {credentials.username}: {e}")
        raise HTTPException(status_code=400, detail="Login failed")

# 9. Получение всех записей пользователя
@router.get("/appointments")
async def get_user_appointments(current_user=Depends(get_current_user)):
    logger.info(f"Attempting to retrieve appointments for user ID: {current_user['id']}")
    
    try:
        query = "SELECT * FROM appointments WHERE user_id = $1"
        records = await db.pool.fetch(query, current_user["id"])
        
        if not records:
            logger.warning(f"No appointments found for user ID: {current_user['id']}")
            raise HTTPException(status_code=404, detail="No appointments found")
        
        logger.info(f"Retrieved {len(records)} appointments for user ID: {current_user['id']}")
        return records
    
    except Exception as e:
        logger.error(f"Error occurred while retrieving appointments for user ID {current_user['id']}: {e}")
        raise HTTPException(status_code=400, detail="Failed to retrieve appointments")

# Создание записи к специалисту
@router.post("/appointments")
async def create_appointment(appointment_request: AppointmentCreateRequest, current_user=Depends(get_current_user)):
    logger.info(f"Attempting to create appointment for user ID: {current_user['id']} with specialist ID: {appointment_request.specialist_id}")
    
    specialist_id = appointment_request.specialist_id
    appointment_time = appointment_request.appointment_time
    service = appointment_request.service

    try:
        # Проверка формата времени
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        logger.error(f"Invalid appointment_time format: {appointment_request.appointment_time}")
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")
    
    try:
        # Проверка существования специалиста
        async with httpx.AsyncClient() as client:
            specialist_response = await client.get(f"{SPECIALISTS_SERVICE_URL}/specialists/{specialist_id}")
            if specialist_response.status_code != 200:
                logger.warning(f"Specialist with ID {specialist_id} not found")
                raise HTTPException(status_code=404, detail="Specialist not found")

        # Проверка существования услуги
        async with httpx.AsyncClient() as client:
            services_response = await client.get(f"{SPECIALISTS_SERVICE_URL}/specialists/{specialist_id}/services")
            if services_response.status_code != 200:
                logger.error(f"Failed to fetch services for specialist ID {specialist_id}")
                raise HTTPException(status_code=404, detail="Failed to fetch services")

            services = services_response.json()
            matching_service = next((s for s in services if s["service_name"] == service), None)
            if not matching_service:
                logger.warning(f"Service '{service}' not provided by specialist ID {specialist_id}")
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
                    "amount": price,
                    "card_number": appointment_request.card_number,
                    "card_cvv": appointment_request.card_cvv,
                    "card_expiry": appointment_request.card_expiry
                }
            )
            if payment_response.status_code != 200:
                logger.error(f"Payment failed for user ID {current_user['id']} for service {service}")
                raise HTTPException(status_code=400, detail="Payment failed")
            
            payment_data = payment_response.json()
            if not payment_data.get("success"):
                logger.error(f"Payment was not successful for user ID {current_user['id']} for service {service}")
                raise HTTPException(status_code=400, detail="Payment was not successful")

        # Проверка доступности времени
        async with httpx.AsyncClient() as client:
            schedule_response = await client.get(
                f"{SPECIALISTS_SERVICE_URL}/schedules/check",
                params={"specialist_id": specialist_id, "appointment_time": appointment_time.isoformat()}
            )
            if schedule_response.status_code != 200:
                logger.warning(f"Time slot is not available for specialist ID {specialist_id} at {appointment_time}")
                raise HTTPException(status_code=400, detail="Time slot is not available")

        # Добавление записи в расписание специалиста
        async with httpx.AsyncClient() as client:
            add_schedule_response = await client.post(
                f"{SPECIALISTS_SERVICE_URL}/schedules",
                json={"specialist_id": specialist_id, "appointment_time": appointment_time.isoformat(), "service": service}
            )
            if add_schedule_response.status_code != 201:
                logger.error(f"Failed to add appointment to specialist's schedule for specialist ID {specialist_id}")
                raise HTTPException(status_code=400, detail="Failed to add appointment to specialist's schedule")

        # Добавление записи в базу данных appointments
        query = """
        INSERT INTO appointments (user_id, specialist_id, appointment_time, service)
        VALUES ($1, $2, $3, $4)
        RETURNING id, user_id, specialist_id, appointment_time, service
        """
        record = await db.pool.fetchrow(query, current_user["id"], specialist_id, appointment_time, service)
        if not record:
            logger.error(f"Failed to create appointment for user ID {current_user['id']} with specialist ID {specialist_id}")
            raise HTTPException(status_code=400, detail="Failed to create appointment")

        logger.info(f"Appointment created successfully for user ID {current_user['id']} with specialist ID {specialist_id}")
        return dict(record)

    except Exception as e:
        logger.error(f"Error occurred while creating appointment for user ID {current_user['id']}: {e}")
        raise HTTPException(status_code=400, detail="Failed to create appointment")




# Перенос записи на другое время
@router.put("/appointments/{appointment_id}")
async def reschedule_appointment(
    appointment_id: int,
    reschedule_request: RescheduleRequest,
    current_user=Depends(get_current_user)
):
    logger.info(f"Attempting to reschedule appointment {appointment_id} for user {current_user['id']}")

    try:
        new_time = datetime.fromisoformat(reschedule_request.new_time)
    except ValueError:
        logger.error(f"Invalid new_time format: {reschedule_request.new_time}")
        raise HTTPException(status_code=400, detail="Invalid new_time format")

    try:
        # Проверка существования записи
        query = "SELECT * FROM appointments WHERE id = $1 AND user_id = $2"
        record = await db.pool.fetchrow(query, appointment_id, current_user["id"])
        if not record:
            logger.warning(f"Appointment {appointment_id} not found or user does not have permission to modify")
            raise HTTPException(status_code=404, detail="Appointment not found or access denied")

        specialist_id = record["specialist_id"]

        # Проверка доступности нового времени
        async with httpx.AsyncClient() as client:
            schedule_response = await client.get(
                f"{SPECIALISTS_SERVICE_URL}/schedules/check",
                params={"specialist_id": specialist_id, "appointment_time": new_time.isoformat()}
            )
            if schedule_response.status_code != 200:
                logger.warning(f"New time slot {new_time} for specialist ID {specialist_id} is not available")
                raise HTTPException(status_code=400, detail="New time slot is not available")

        # Обновление расписания специалиста
        async with httpx.AsyncClient() as client:
            update_schedule_response = await client.put(
                f"{SPECIALISTS_SERVICE_URL}/schedules/{appointment_id}",
                json={"new_time": new_time.isoformat()}
            )
            if update_schedule_response.status_code != 200:
                logger.error(f"Failed to update specialist's schedule for appointment ID {appointment_id}")
                raise HTTPException(status_code=400, detail="Failed to update specialist's schedule")

        # Обновление записи в appointments
        update_query = """
        UPDATE appointments
        SET appointment_time = $1
        WHERE id = $2
        RETURNING id, user_id, specialist_id, appointment_time, service
        """
        updated_record = await db.pool.fetchrow(update_query, new_time, appointment_id)
        logger.info(f"Appointment {appointment_id} rescheduled successfully to {new_time}")
        return dict(updated_record)

    except Exception as e:
        logger.error(f"Error occurred while rescheduling appointment {appointment_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to reschedule appointment")


# Удаление записи
@router.delete("/appointments/{appointment_id}")
async def delete_appointment(appointment_id: int, current_user=Depends(get_current_user)):
    logger.info(f"Attempting to delete appointment {appointment_id} for user {current_user['id']}")

    try:
        # Проверка существования записи
        query = "SELECT * FROM appointments WHERE id = $1 AND user_id = $2"
        record = await db.pool.fetchrow(query, appointment_id, current_user["id"])
        if not record:
            logger.warning(f"Appointment {appointment_id} not found or user does not have permission to delete")
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
                logger.error(f"Failed to delete appointment from specialist's schedule for appointment ID {appointment_id}")
                raise HTTPException(status_code=400, detail="Failed to delete appointment from specialist's schedule")

        # Удаление записи из appointments
        delete_query = "DELETE FROM appointments WHERE id = $1"
        await db.pool.execute(delete_query, appointment_id)
        logger.info(f"Appointment {appointment_id} deleted successfully")
        return {"detail": "Appointment deleted"}

    except Exception as e:
        logger.error(f"Error occurred while deleting appointment {appointment_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to delete appointment")


# Удаление записей пользователя по специалисту
@router.delete("/appointments")
async def delete_appointments_by_specialist(
    specialist_id: int,
    appointment_time: str
):
    logger.info(f"Attempting to delete appointments for specialist ID {specialist_id} at time {appointment_time}")

    try:
        delete_query = """
        DELETE FROM appointments
        WHERE specialist_id = $1 AND appointment_time = $2
        """
        await db.pool.execute(delete_query, specialist_id, datetime.fromisoformat(appointment_time))
        logger.info(f"Appointments for specialist ID {specialist_id} at time {appointment_time} deleted successfully")
        return {"detail": "Appointments deleted"}
    
    except Exception as e:
        logger.error(f"Error occurred while deleting appointments for specialist ID {specialist_id}: {e}")
        raise HTTPException(status_code=400, detail="Failed to delete appointments")



