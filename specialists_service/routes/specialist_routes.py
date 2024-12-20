from fastapi import APIRouter, HTTPException, Depends
from ..database import db
from ..models.specialist import SpecialistCreate, SpecialistOut, SpecialistUpdate
from pydantic import BaseModel
from shared.auth import hash_password, create_access_token,verify_password, get_admin_specialist, get_current_user
from datetime import datetime
import httpx


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

# Регистрация специалиста
@router.post("/specialists", response_model=SpecialistOut)
async def create_specialist(specialist: SpecialistCreate):
    query = """
    INSERT INTO specialists (name, specialty, hashed_password)
    VALUES ($1, $2, $3)
    RETURNING id, name, specialty;
    """
    hashed_password = hash_password(specialist.password)
    record = await db.pool.fetchrow(query, specialist.name, specialist.specialty, hashed_password)
    return SpecialistOut(**record)

# Получение списка специалистов
@router.get("/specialists", response_model=list[SpecialistOut])
async def get_specialists(current_user=Depends(get_admin_specialist)):
    query = "SELECT id, name, specialty FROM specialists"
    records = await db.pool.fetch(query)
    return [SpecialistOut(**dict(record)) for record in records]

# Получение специалиста по ID
@router.get("/specialists/{specialist_id}")
async def get_specialist(specialist_id: int):
    """
    Возвращает данные специалиста по ID
    """
    query = """
    SELECT id, name, specialty
    FROM specialists
    WHERE id = $1
    """
    record = await db.pool.fetchrow(query, specialist_id)
    
    if not record:
        raise HTTPException(status_code=404, detail="Specialist not found")
    
    return dict(record)



# Удаление специалиста
@router.delete("/specialists/{specialist_id}")
async def delete_specialist(specialist_id: int, current_user=Depends(get_admin_specialist)):
    """
    Удаление специалиста и всех его записей
    """
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

    # Удаление самого специалиста
    delete_specialist_query = "DELETE FROM specialists WHERE id = $1 RETURNING id"
    specialist = await db.pool.fetchrow(delete_specialist_query, specialist_id)
    if not specialist:
        raise HTTPException(status_code=404, detail="Specialist not found")

    return {"detail": "Specialist and all related schedules deleted"}


@router.post("/auth/login")
async def login(credentials: LoginRequest):
    query = "SELECT id, name, specialty, hashed_password FROM specialists WHERE name = $1"
    specialist = await db.pool.fetchrow(query, credentials.name)
    
    if not specialist or not verify_password(credentials.password, specialist["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token_data = {"id": specialist["id"], "specialty": specialist["specialty"]}
    token = create_access_token(token_data)
    
    return {"access_token": token, "token_type": "bearer"}

@router.put("/specialists/{specialist_id}", response_model=SpecialistOut)
async def update_specialist(
    specialist_id: int,
    specialist_data: SpecialistUpdate,
    current_user=Depends(get_admin_specialist)
):
    update_fields = [f"{key} = ${i + 1}" for i, key in enumerate(specialist_data.dict(exclude_unset=True))]
    if not update_fields:
        raise HTTPException(status_code=400, detail="No data to update")
    
    query = f"UPDATE specialists SET {', '.join(update_fields)} WHERE id = ${len(update_fields) + 1} RETURNING id, name, specialty"
    values = list(specialist_data.dict(exclude_unset=True).values()) + [specialist_id]
    record = await db.pool.fetchrow(query, *values)
    
    if not record:
        raise HTTPException(status_code=404, detail="Specialist not found")
    return SpecialistOut(**record)

@router.get("/schedules/check")
async def check_schedule(specialist_id: int, appointment_time: str):
    """
    Проверяет доступность времени у специалиста
    """
    try:
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    query = """
    SELECT * FROM schedules
    WHERE specialist_id = $1 AND appointment_time = $2
    """
    record = await db.pool.fetchrow(query, specialist_id, appointment_time)
    if record:
        raise HTTPException(status_code=400, detail="Time slot is already booked")

    return {"detail": "Time slot is available"}


@router.post("/schedules", status_code=201)
async def add_schedule(request: ScheduleCreateRequest):
    """
    Добавляет запись в расписание специалиста
    """
    try:
        appointment_time = datetime.fromisoformat(request.appointment_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    query = """
    INSERT INTO schedules (specialist_id, appointment_time, service)
    VALUES ($1, $2, $3)
    RETURNING id, specialist_id, appointment_time, service
    """
    record = await db.pool.fetchrow(query, request.specialist_id, appointment_time, request.service)

    if not record:
        raise HTTPException(status_code=500, detail="Failed to add appointment to schedule")

    return dict(record)

@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, update_request: UpdateScheduleRequest):
    """
    Обновление времени в расписании специалиста
    """
    try:
        new_time = datetime.fromisoformat(update_request.new_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid new_time format")

    query = """
    UPDATE schedules
    SET appointment_time = $1
    WHERE id = $2
    RETURNING id, specialist_id, appointment_time, service
    """
    record = await db.pool.fetchrow(query, new_time, schedule_id)

    if not record:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return dict(record)



@router.delete("/schedules")
async def delete_schedule(specialist_id: int, appointment_time: str):
    """
    Удаление записи из расписания специалиста
    """
    try:
        appointment_time = datetime.fromisoformat(appointment_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment_time format")

    # Удаление записи из таблицы schedules
    query = """
    DELETE FROM schedules
    WHERE specialist_id = $1 AND appointment_time = $2
    """
    result = await db.pool.execute(query, specialist_id, appointment_time)

    if result == "DELETE 0":
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
            raise HTTPException(status_code=500, detail="Failed to delete related appointments")

    return {"detail": "Schedule and related appointments deleted"}




@router.post("/specialists/{specialist_id}/services", status_code=201)
async def add_service(specialist_id: int, service: Service, current_user=Depends(get_admin_specialist)):
    """
    Добавление услуги к специалисту
    """
    # Проверка, существует ли специалист
    query_check_specialist = "SELECT id FROM specialists WHERE id = $1"
    specialist = await db.pool.fetchrow(query_check_specialist, specialist_id)
    if not specialist:
        raise HTTPException(status_code=404, detail="Specialist not found")

    # Добавление услуги
    query_add_service = """
    INSERT INTO services (specialist_id, service_name, price)
    VALUES ($1, $2, $3)
    RETURNING id, specialist_id, service_name, price
    """
    new_service = await db.pool.fetchrow(query_add_service, specialist_id, service.service_name, service.price)

    if not new_service:
        raise HTTPException(status_code=500, detail="Failed to add service")

    return dict(new_service)




@router.delete("/specialists/{specialist_id}/services/{service_id}")
async def delete_service(specialist_id: int, service_id: int, current_user=Depends(get_admin_specialist)):
    """
    Удаление услуги у специалиста
    """
    # Проверка, существует ли услуга
    query_check_service = "SELECT service_name FROM services WHERE id = $1 AND specialist_id = $2"
    service = await db.pool.fetchrow(query_check_service, service_id, specialist_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found or does not belong to the specialist")

    # Удаление услуги
    query_delete_service = """
    DELETE FROM services
    WHERE id = $1 AND specialist_id = $2
    """
    await db.pool.execute(query_delete_service, service_id, specialist_id)

    return {"detail": f"Service '{service['service_name']}' deleted"}



@router.get("/specialists/{specialist_id}/services")
async def get_services(specialist_id: int):
    """
    Получение всех услуг специалиста
    """
    query_get_services = "SELECT id, service_name, price FROM services WHERE specialist_id = $1"
    services = await db.pool.fetch(query_get_services, specialist_id)

    return [dict(service) for service in services]
