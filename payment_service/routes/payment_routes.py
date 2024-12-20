from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
from ..database import db

router = APIRouter()

class PaymentRequest(BaseModel):
    user_id: int
    specialist_id: int
    service_name: str
    amount: float
    card_number: str = Field(..., pattern=r"^\d{16}$")  # 16 цифр
    card_cvv: str = Field(..., pattern=r"^\d{3}$")      # 3 цифры
    card_expiry: str = Field(..., pattern=r"^\d{2}/\d{4}$")  # Формат MM/YYYY



def luhn_check(card_number: str) -> bool:
    """
    Проверка номера карты с использованием алгоритма Луна
    """
    digits = [int(d) for d in card_number]
    checksum = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        if i % 2 == 1:  # Удваиваем каждую вторую цифру с конца
            digit *= 2
            if digit > 9:
                digit -= 9  # Если результат больше 9, вычитаем 9
        checksum += digit
    return checksum % 10 == 0

@router.post("/pay")
async def process_payment(payment: PaymentRequest):
    """
    Фиктивная обработка платежа с сохранением транзакции
    """
    # Проверка даты истечения карты
    try:
        expiry_month, expiry_year = map(int, payment.card_expiry.split('/'))
        expiry_date = datetime(year=expiry_year, month=expiry_month, day=1)
        if expiry_date < datetime.now():
            raise HTTPException(status_code=400, detail="Card is expired")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expiry date format")

    # Проверка номера карты
    if not luhn_check(payment.card_number):
        raise HTTPException(status_code=400, detail="Invalid card number")

    # Логика фиктивной оплаты
    transaction_status = "success" if payment.amount > 0 else "failed"

    # Сохранение транзакции в базе данных
    query = """
    INSERT INTO transactions (user_id, specialist_id, service_name, amount, card_number, transaction_status)
    VALUES ($1, $2, $3, $4, $5, $6)
    RETURNING id
    """
    async with db.pool.acquire() as conn:
        transaction_id = await conn.fetchval(
            query,
            payment.user_id,
            payment.specialist_id,
            payment.service_name,
            payment.amount,
            payment.card_number[-4:],  # Сохраняем последние 4 цифры карты
            transaction_status
        )

    if transaction_status == "failed":
        raise HTTPException(status_code=400, detail="Payment failed")

    return {
        "success": True,
        "message": "Payment processed successfully",
        "transaction_id": transaction_id
    }

@router.get("/transactions")
async def get_transactions():
    """
    Получение всех транзакций
    """
    query = """
    SELECT id, user_id, specialist_id, service_name, amount, card_number, transaction_status, transaction_time
    FROM transactions
    ORDER BY transaction_time DESC
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(query)
    
    transactions = [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "specialist_id": row["specialist_id"],
            "service_name": row["service_name"],
            "amount": float(row["amount"]),
            "card_number": f"**** **** **** {row['card_number']}",  # Маскируем номер карты
            "transaction_status": row["transaction_status"],
            "transaction_time": row["transaction_time"].isoformat()
        }
        for row in rows
    ]

    return transactions

