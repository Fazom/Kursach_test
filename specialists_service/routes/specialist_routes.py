from fastapi import APIRouter, HTTPException, Depends
from ..database import db
from ..models.specialist import SpecialistCreate, SpecialistOut, SpecialistUpdate
from pydantic import BaseModel
from shared.auth import hash_password, create_access_token,verify_password, get_admin_specialist, get_current_user
from datetime import datetime
import httpx
import logging
import asyncpg
# Настройка логирования
logger = logging.getLogger("specialist_service")
logger.setLevel(logging.INFO)

# Обработчик для записи в файл с кодировкой UTF-8
file_handler = logging.FileHandler("specialist_service.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Обработчик для вывода в консоль с кодировкой UTF-8
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))

# Добавление обработчиков к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

USERS_SERVICE_URL = "http://127.0.0.1:8000/api/v1"

class AppointmentCreateRequest(BaseModel):
    specialist_id: int
    appointment_time: str
    service: str

class LoginRequest(BaseModel):
    name: str
    password: str

class ScheduleCreateRequest(BaseModel):
    specialist_id: int
    appointment_time: str
    service: str

class UpdateScheduleRequest(BaseModel):
    new_time: str

class Service(BaseModel):
    service_name: str
    price: float


router = APIRouter()

# 1. Регистрация специалиста
@router.post("/specialists", response_model=SpecialistOut)
async def create_specialist(specialist: SpecialistCreate):
    logger.info(f"Attempting to create specialist: {specialist.name}")
    
    query = """
    INSERT INTO specialists (name, specialty, hashed_password)
    VALUES ($1, $2, $3)
    RETURNING id, name, specialty;
    """
    hashed_password = hash_password(specialist.password)
    
    try:
        record = await db.pool.fetchrow(query, specialist.name, specialist.specialty, hashed_password)
        logger.info(f"Specialist {specialist.name} created successfully")
        return SpecialistOut(**record)
    except asyncpg.UniqueViolationError:
        logger.error(f"Error: Specialist with name {specialist.name} already exists")
        raise HTTPException(status_code=400, detail="Specialist with this name already exists")
    except Exception as e:
        logger.error(f"Error creating specialist: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to create specialist")

# 2. Получение списка специалистов
@router.get("/specialists", response_model=list[SpecialistOut])
async def get_specialists(current_user=Depends(get_admin_specialist)):
    logger.info("Attempting to retrieve all specialists")
    
    query = "SELECT id, name, specialty FROM specialists"
    try:
        records = await db.pool.fetch(query)
        logger.info(f"Retrieved {len(records)} specialists from the database")
        return [SpecialistOut(**dict(record)) for record in records]
    except Exception as e:
        logger.error(f"Error retrieving specialists: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve specialists")

# 3. Получение специалиста по ID
@router.get("/specialists/{specialist_id}")
async def get_specialist(specialist_id: int):
    logger.info(f"Attempting to retrieve specialist with ID: {specialist_id}")
    
    query = """
    SELECT id, name, specialty
    FROM specialists
    WHERE id = $1
    """
    record = await db.pool.fetchrow(query, specialist_id)
    if not record:
        logger.error(f"Specialist with ID {specialist_id} not found")
        raise HTTPException(status_code=404, detail="Specialist not found")
    
    logger.info(f"Specialist {specialist_id} found")
    return dict(record)

# 4. Удаление специалиста
@router.delete("/specialists/{specialist_id}")
async def delete_specialist(specialist_id: int, current_user=Depends(get_admin_specialist)):
    logger.info(f"Attempting to delete specialist with ID: {specialist_id}")
    
    try:
        # Удаление всех записей специалиста из таблицы schedules
        delete_schedules_query = "DELETE FROM schedules WHERE specialist_id = $1 RETURNING id, appointment_time"
        schedules = await db.pool.fetch(delete_schedules_query, specialist_id)

        # Удаление записей в базе данных пользователей
        async with httpx.AsyncClient() as client:
            for schedule in schedules:
                await client.delete(
                    f"{USERS_SERVICE_URL}/appointments",
                    params={
                        "specialist_id": specialist_id,
                        "appointment_time": schedule["appointment_time"].isoformat()
                    }
                )

        # Удаление специалиста
        delete_specialist_query = "DELETE FROM specialists WHERE id = $1 RETURNING id"
        specialist = await db.pool.fetchrow(delete_specialist_query, specialist_id)
        
        if not specialist:
            logger.error(f"Specialist with ID {specialist_id} not found")
            raise HTTPException(status_code=404, detail="Specialist not found")
        
        logger.info(f"Specialist {specialist_id} and all related schedules deleted successfully")
        return {"detail": "Specialist and all related schedules deleted"}
    
    except Exception as e:
        logger.error(f"Error deleting specialist {specialist_id}: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to delete specialist")

# 5. Авторизация специалиста
@router.post("/auth/login")
async def login(credentials: LoginRequest):
    logger.info(f"Attempting login for specialist: {credentials.name}")
    
    query = "SELECT id, name, specialty, hashed_password FROM specialists WHERE name = $1"
    specialist = await db.pool.fetchrow(query, credentials.name)
    
    if not specialist or not verify_password(credentials.password, specialist["hashed_password"]):
        logger.warning(f"Invalid credentials for specialist: {credentials.name}")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token_data = {"id": specialist["id"], "specialty": specialist["specialty"]}
    token = create_access_token(token_data)
    
    logger.info(f"Specialist {credentials.name} logged in successfully")
    return {"access_token": token, "token_type": "bearer"}

# 6. Проверка расписания специалиста
@router.get("/schedules/check")
async def check_schedule(specialist_id: int, appointment_time: str):
    logger.info(f"Checking schedule for specialist {specialist_id} at time {appointment_time}")
    
    try:
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        logger.error(f"Invalid appointment_time format: {appointment_time}")
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    query = """
    SELECT * FROM schedules
    WHERE specialist_id = $1 AND appointment_time = $2
    """
    record = await db.pool.fetchrow(query, specialist_id, appointment_time)
    if record:
        logger.warning(f"Time slot for specialist {specialist_id} at {appointment_time} is already booked")
        raise HTTPException(status_code=400, detail="Time slot is already booked")

    logger.info(f"Time slot for specialist {specialist_id} at {appointment_time} is available")
    return {"detail": "Time slot is available"}

# 7. Добавление записи в расписание специалиста
@router.post("/schedules", status_code=201)
async def add_schedule(request: ScheduleCreateRequest):
    logger.info(f"Adding schedule for specialist {request.specialist_id} at time {request.appointment_time}")
    
    try:
        appointment_time = datetime.fromisoformat(request.appointment_time)
    except ValueError:
        logger.error(f"Invalid appointment_time format: {request.appointment_time}")
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    query = """
    INSERT INTO schedules (specialist_id, appointment_time, service)
    VALUES ($1, $2, $3)
    RETURNING id, specialist_id, appointment_time, service
    """
    try:
        record = await db.pool.fetchrow(query, request.specialist_id, appointment_time, request.service)
        logger.info(f"Schedule added successfully for specialist {request.specialist_id} at time {appointment_time}")
        return dict(record)
    except Exception as e:
        logger.error(f"Failed to add schedule: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to add schedule")

# 8. Обновление времени в расписании специалиста
@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, update_request: UpdateScheduleRequest):
    logger.info(f"Attempting to update schedule with ID: {schedule_id}")
    
    try:
        new_time = datetime.fromisoformat(update_request.new_time)
    except ValueError:
        logger.error(f"Invalid new_time format: {update_request.new_time}")
        raise HTTPException(status_code=400, detail="Invalid new_time format")

    query = """
    UPDATE schedules
    SET appointment_time = $1
    WHERE id = $2
    RETURNING id, specialist_id, appointment_time, service
    """
    record = await db.pool.fetchrow(query, new_time, schedule_id)

    if not record:
        logger.error(f"Schedule with ID {schedule_id} not found")
        raise HTTPException(status_code=404, detail="Schedule not found")

    logger.info(f"Schedule with ID {schedule_id} updated successfully")
    return dict(record)

# 9. Удаление записи из расписания специалиста
@router.delete("/schedules")
async def delete_schedule(specialist_id: int, appointment_time: str):
    logger.info(f"Attempting to delete schedule for specialist {specialist_id} at time {appointment_time}")
    
    try:
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        logger.error(f"Invalid appointment_time format: {appointment_time}")
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    # Удаление записи из таблицы schedules
    query = """
    DELETE FROM schedules
    WHERE specialist_id = $1 AND appointment_time = $2
    """
    result = await db.pool.execute(query, specialist_id, appointment_time)

    if result == "DELETE 0":
        logger.error(f"Schedule for specialist {specialist_id} at {appointment_time} not found")
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Удаление записи из базы данных пользователей
    async with httpx.AsyncClient() as client:
        user_response = await client.delete(
            f"{USERS_SERVICE_URL}/appointments",
            params={
                "specialist_id": specialist_id,
                "appointment_time": appointment_time.isoformat()
            }
        )
        if user_response.status_code != 200:
            logger.error(f"Failed to delete related appointments for specialist {specialist_id} at {appointment_time}")
            raise HTTPException(status_code=400, detail="Failed to delete related appointments")

    logger.info(f"Schedule for specialist {specialist_id} at {appointment_time} and related appointments deleted successfully")
    return {"detail": "Schedule and related appointments deleted"}

# 10. Добавление услуги к специалисту
@router.post("/specialists/{specialist_id}/services", status_code=201)
async def add_service(specialist_id: int, service: Service, current_user=Depends(get_admin_specialist)):
    logger.info(f"Attempting to add service '{service.service_name}' to specialist {specialist_id}")
    
    # Проверка, существует ли специалист
    query_check_specialist = "SELECT id FROM specialists WHERE id = $1"
    specialist = await db.pool.fetchrow(query_check_specialist, specialist_id)
    if not specialist:
        logger.error(f"Specialist {specialist_id} not found")
        raise HTTPException(status_code=404, detail="Specialist not found")

    # Добавление услуги
    query_add_service = """
    INSERT INTO services (specialist_id, service_name, price)
    VALUES ($1, $2, $3)
    RETURNING id, specialist_id, service_name, price
    """
    try:
        new_service = await db.pool.fetchrow(query_add_service, specialist_id, service.service_name, service.price)
        logger.info(f"Service '{service.service_name}' added successfully to specialist {specialist_id}")
        return dict(new_service)
    except Exception as e:
        logger.error(f"Failed to add service to specialist {specialist_id}: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to add service")

# 11. Удаление услуги у специалиста
@router.delete("/specialists/{specialist_id}/services/{service_id}")
async def delete_service(specialist_id: int, service_id: int, current_user=Depends(get_admin_specialist)):
    logger.info(f"Attempting to delete service with ID {service_id} for specialist {specialist_id}")
    
    # Проверка, существует ли услуга
    query_check_service = "SELECT service_name FROM services WHERE id = $1 AND specialist_id = $2"
    service = await db.pool.fetchrow(query_check_service, service_id, specialist_id)
    if not service:
        logger.error(f"Service {service_id} not found for specialist {specialist_id}")
        raise HTTPException(status_code=404, detail="Service not found or does not belong to the specialist")

    # Удаление услуги
    query_delete_service = """
    DELETE FROM services
    WHERE id = $1 AND specialist_id = $2
    """
    await db.pool.execute(query_delete_service, service_id, specialist_id)

    logger.info(f"Service '{service['service_name']}' deleted successfully for specialist {specialist_id}")
    return {"detail": f"Service '{service['service_name']}' deleted"}

# 12. Получение всех услуг специалиста
@router.get("/specialists/{specialist_id}/services")
async def get_services(specialist_id: int):
    logger.info(f"Retrieving services for specialist {specialist_id}")
    
    query_get_services = "SELECT id, service_name, price FROM services WHERE specialist_id = $1"
    services = await db.pool.fetch(query_get_services, specialist_id)

    logger.info(f"Retrieved {len(services)} services for specialist {specialist_id}")
    return [dict(service) for service in services]