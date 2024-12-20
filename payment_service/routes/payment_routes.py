from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
from ..database import db
import logging

router = APIRouter()

logger = logging.getLogger("payment_service")
logger.setLevel(logging.INFO)

# Обработчик для записи в файл с кодировкой UTF-8
file_handler = logging.FileHandler("payment_service.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Обработчик для вывода в консоль с кодировкой UTF-8
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))

# Добавление обработчиков к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

class PaymentRequest(BaseModel):
    user_id: int
    specialist_id: int
    service_name: str
    amount: float
    card_number: str = Field(..., pattern=r"^\d{16}$")  # 16 цифр
    card_cvv: str = Field(..., pattern=r"^\d{3}$")      # 3 цифры
    card_expiry: str = Field(..., pattern=r"^\d{2}/\d{4}$")  # Формат MM/YYYY



import logging
from fastapi import HTTPException, APIRouter, Depends
from datetime import datetime
import httpx

# Создание логгера
logger = logging.getLogger("payment_service")
logger.setLevel(logging.INFO)

# Обработчик для записи в файл с кодировкой UTF-8
file_handler = logging.FileHandler("payment_service.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Обработчик для вывода в консоль с кодировкой UTF-8
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))

# Добавление обработчиков к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

router = APIRouter()

def luhn_check(card_number: str) -> bool: # Проверка номера карты с использованием алгоритма Луна
    digits = [int(d) for d in card_number]
    checksum = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        if i % 2 == 1:  
            digit *= 2
            if digit > 9:
                digit -= 9  
        checksum += digit
    return checksum % 10 == 0

@router.post("/pay")
async def process_payment(payment: PaymentRequest): #Фиктивная обработка платежа с сохранением транзакции
    logger.info(f"Attempting to process payment for user {payment.user_id} with service {payment.service_name}")
    # Проверка даты истечения карты
    try:
        expiry_month, expiry_year = map(int, payment.card_expiry.split('/'))
        expiry_date = datetime(year=expiry_year, month=expiry_month, day=1)
        if expiry_date < datetime.now():
            logger.error(f"Card expired for user {payment.user_id}. Expiry date: {expiry_date}")
            raise HTTPException(status_code=400, detail="Card is expired")
    except ValueError:
        logger.error(f"Invalid expiry date format for user {payment.user_id}: {payment.card_expiry}")
        raise HTTPException(status_code=400, detail="Invalid expiry date format")

    # Проверка номера карты
    if not luhn_check(payment.card_number):
        logger.error(f"Invalid card number for user {payment.user_id}: {payment.card_number}")
        raise HTTPException(status_code=400, detail="Invalid card number")

    # Логика фиктивной оплаты
    transaction_status = "success" if payment.amount > 0 else "failed"

    # Сохранение транзакции в базе данных
    query = """
    INSERT INTO transactions (user_id, specialist_id, service_name, amount, card_number, transaction_status)
    VALUES ($1, $2, $3, $4, $5, $6)
    RETURNING id
    """
    try:
        async with db.pool.acquire() as conn:
            transaction_id = await conn.fetchval(
                query,
                payment.user_id,
                payment.specialist_id,
                payment.service_name,
                payment.amount,
                payment.card_number[-4:], 
                transaction_status
            )
        
        if transaction_status == "failed":
            logger.error(f"Payment failed for user {payment.user_id}. Service: {payment.service_name}")
            raise HTTPException(status_code=400, detail="Payment failed")
        
        logger.info(f"Payment processed successfully for user {payment.user_id}. Transaction ID: {transaction_id}")
        return {
            "success": True,
            "message": "Payment processed successfully",
            "transaction_id": transaction_id
        }

    except Exception as e:
        logger.error(f"Error while processing payment for user {payment.user_id}: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to process payment")

@router.get("/transactions")
async def get_transactions(): # Получение всех транзакций
    logger.info("Retrieving all transactions")

    query = """
    SELECT id, user_id, specialist_id, service_name, amount, card_number, transaction_status, transaction_time
    FROM transactions
    ORDER BY transaction_time DESC
    """
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        transactions = [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "specialist_id": row["specialist_id"],
                "service_name": row["service_name"],
                "amount": float(row["amount"]),
                "card_number": f"**** **** **** {row['card_number']}",  
                "transaction_status": row["transaction_status"],
                "transaction_time": row["transaction_time"].isoformat()
            }
            for row in rows
        ]

        logger.info(f"Retrieved {len(transactions)} transactions successfully")
        return transactions
    
    except Exception as e:
        logger.error(f"Error while retrieving transactions: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to retrieve transactions")
