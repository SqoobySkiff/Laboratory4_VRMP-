import re
import html
import logging
from datetime import date, datetime
from typing import Optional, Any
from functools import wraps

from sqlalchemy import text, select, and_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from models.database import Hotel, Room, Client, Booking, BookingStatus

security_logger = logging.getLogger("hotel.security")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

class ValidationError(ValueError):
    pass

class InputValidator:
    SQL_PATTERNS = re.compile(
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|"
        r"TRUNCATE|GRANT|REVOKE|SCRIPT)\b"
        r"|--|/\*|\*/|;|'|\"|\\x[0-9a-fA-F]{2}|%27|%22|%3B)",
        re.IGNORECASE,
    )

    EMAIL_RE    = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
    PHONE_RE    = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")
    PASSPORT_RE = re.compile(r"^[A-Z0-9]{5,20}$", re.IGNORECASE)

    @classmethod
    def sanitize_string(cls, value: str, field_name: str = "поле", max_len: int = 500) -> str:
        """Очищає рядок від потенційно небезпечного вмісту."""
        if not isinstance(value, str):
            raise ValidationError(f"Поле '{field_name}' має бути рядком")

        value = value.strip()

        if not value:
            raise ValidationError(f"Поле '{field_name}' не може бути порожнім")

        if len(value) > max_len:
            raise ValidationError(
                f"Поле '{field_name}' занадто довге (макс. {max_len} символів)"
            )

        if cls.SQL_PATTERNS.search(value):
            security_logger.warning(
                "Виявлено SQL-ін'єкцію в полі '%s': %.50s",
                field_name, value,
            )
            raise ValidationError(
                f"Поле '{field_name}' містить заборонені символи або SQL-ключові слова"
            )

        return html.escape(value)

    @classmethod
    def validate_email(cls, email: str) -> str:
        email = cls.sanitize_string(email, "email", max_len=150)
        if not cls.EMAIL_RE.match(email):
            raise ValidationError(f"Некоректний формат email: '{email}'")
        return email.lower()

    @classmethod
    def validate_phone(cls, phone: str) -> str:
        phone = cls.sanitize_string(phone, "phone", max_len=20)
        if not cls.PHONE_RE.match(phone):
            raise ValidationError(f"Некоректний формат телефону: '{phone}'")
        return phone

    @classmethod
    def validate_passport(cls, passport: str) -> str:
        passport = passport.strip().upper()
        if not cls.PASSPORT_RE.match(passport):
            raise ValidationError(f"Некоректний формат паспорта: '{passport}'")
        return passport

    @classmethod
    def validate_positive_float(cls, value: Any, field_name: str) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Поле '{field_name}' має бути числом")
        if v <= 0:
            raise ValidationError(f"Поле '{field_name}' має бути більше 0")
        return v

    @classmethod
    def validate_positive_int(cls, value: Any, field_name: str, min_val: int = 1) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Поле '{field_name}' має бути цілим числом")
        if v < min_val:
            raise ValidationError(f"Поле '{field_name}' має бути ≥ {min_val}")
        return v

    @classmethod
    def validate_dates(cls, check_in: date, check_out: date) -> None:
        today = date.today()
        if check_in < today:
            raise ValidationError("Дата заїзду не може бути в минулому")
        if check_out <= check_in:
            raise ValidationError("Дата виїзду має бути пізніше дати заїзду")
        max_stay = 365
        if (check_out - check_in).days > max_stay:
            raise ValidationError(f"Термін проживання не може перевищувати {max_stay} днів")

    @classmethod
    def validate_hotel_stars(cls, stars: Any) -> int:
        stars = cls.validate_positive_int(stars, "stars", min_val=1)
        if stars > 5:
            raise ValidationError("Кількість зірок має бути від 1 до 5")
        return stars

def audit_log(action: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                security_logger.info("[AUDIT] Дія: %s | args=%s", action, str(args[1:])[:80])
                return result
            except ValidationError as e:
                security_logger.warning("[AUDIT] Валідація не пройшла: %s | %s", action, e)
                raise
            except SQLAlchemyError as e:
                security_logger.error("[AUDIT] Помилка БД: %s | %s", action, e)
                raise
        return wrapper
    return decorator

class SecureBookingService:

    def __init__(self, session: Session):
        self.session = session

    @audit_log("ADD_CLIENT")
    def add_client_safe(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        passport_num: str,
    ) -> Client:
        first_name   = InputValidator.sanitize_string(first_name,   "first_name",   100)
        last_name    = InputValidator.sanitize_string(last_name,     "last_name",    100)
        email        = InputValidator.validate_email(email)
        phone        = InputValidator.validate_phone(phone)
        passport_num = InputValidator.validate_passport(passport_num)

        client = Client(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            passport_num=passport_num,
        )
        self.session.add(client)
        self.session.commit()
        self.session.refresh(client)
        return client

    @audit_log("ADD_BOOKING")
    def add_booking_safe(
        self,
        client_id: int,
        room_id: int,
        check_in: date,
        check_out: date,
        notes: str = "",
    ) -> Booking:
        client_id = InputValidator.validate_positive_int(client_id, "client_id")
        room_id   = InputValidator.validate_positive_int(room_id,   "room_id")
        InputValidator.validate_dates(check_in, check_out)

        if notes:
            notes = InputValidator.sanitize_string(notes, "notes", max_len=1000)

        room = self.session.get(Room, room_id)
        if not room or not room.is_available:
            raise ValidationError(f"Кімнату #{room_id} не знайдено або вона недоступна.")

        conflict = self.session.execute(
            select(Booking).where(
                Booking.room_id == room_id,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                and_(Booking.check_in < check_out, Booking.check_out > check_in),
            )
        ).scalar_one_or_none()

        if conflict:
            raise ValidationError(
                f"Кімната вже заброньована з {conflict.check_in} по {conflict.check_out}."
            )

        nights = (check_out - check_in).days
        booking = Booking(
            client_id=client_id,
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            total_price=nights * room.price_per_night,
            status=BookingStatus.CONFIRMED,
            notes=notes,
        )
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    @audit_log("SEARCH_CLIENTS")
    def search_clients_safe(self, search_term: str) -> list[Client]:
        search_term = InputValidator.sanitize_string(search_term, "search_term", 100)

        stmt = text(
            "SELECT * FROM clients "
            "WHERE first_name LIKE :term OR last_name LIKE :term OR email LIKE :term"
        ).bindparams(term=f"%{search_term}%")

        rows = self.session.execute(stmt).fetchall()
        return [
            self.session.get(Client, row[0])
            for row in rows
            if self.session.get(Client, row[0])
        ]

    @audit_log("SEARCH_ROOMS_BY_PRICE")
    def get_rooms_in_price_range(
        self, min_price: float, max_price: float
    ) -> list[Room]:
        min_price = InputValidator.validate_positive_float(min_price, "min_price")
        max_price = InputValidator.validate_positive_float(max_price, "max_price")
        if min_price > max_price:
            raise ValidationError("min_price не може бути більше max_price.")

        stmt = text(
            "SELECT * FROM rooms "
            "WHERE price_per_night BETWEEN :min_p AND :max_p "
            "AND is_available = 1 "
            "ORDER BY price_per_night"
        ).bindparams(min_p=min_price, max_p=max_price)

        rows = self.session.execute(stmt).fetchall()
        return [
            self.session.get(Room, row[0])
            for row in rows
            if self.session.get(Room, row[0])
        ]

def demonstrate_sql_injection_protection():

    print("\n" + "═" * 60)
    print("  ДЕМОНСТРАЦІЯ ЗАХИСТУ ВІД SQL-ІН'ЄКЦІЙ")

    attack_vectors = [
        ("email",   "admin'--",                   "класична SQL-ін'єкція"),
        ("email",   "x' OR '1'='1",               "обхід авторизації"),
        ("name",    "'; DROP TABLE clients; --",   "DROP TABLE атака"),
        ("search",  "UNION SELECT * FROM clients", "UNION атака"),
        ("phone",   "+380 /* comment */ 123",      "коментар в запиті"),
        ("email",   "%27 OR %271%27=%271",         "URL-encoded ін'єкція"),
    ]

    for field, payload, attack_name in attack_vectors:
        try:
            InputValidator.sanitize_string(payload, field)
            print(f"ПРОПУСТИВ  [{attack_name}]: {payload[:40]}")
        except ValidationError as e:
            print(f"ЗАБЛОКОВАНО [{attack_name}]: {str(e)[:60]}")

    print("\n....Валідація email....")
    bad_emails = ["not-an-email", "a@", "@b.com", "user@domain", "x'OR'1'='1@evil.com"]
    for email in bad_emails:
        try:
            InputValidator.validate_email(email)
            print(f"ПРОПУСТИВ: {email}")
        except ValidationError as e:
            print(f"ЗАБЛОКОВАНО: {str(e)[:60]}")

    print("\n....Валідація дат....")
    bad_dates = [
        (date(2020, 1, 1), date(2020, 1, 5), "дата в минулому"),
        (date(2030, 1, 5), date(2030, 1, 1), "check_out < check_in"),
    ]
    for ci, co, desc in bad_dates:
        try:
            InputValidator.validate_dates(ci, co)
            print(f"ПРОПУСТИВ: {desc}")
        except ValidationError as e:
            print(f"ЗАБЛОКОВАНО [{desc}]: {str(e)[:60]}")

    print("═" * 60 + "\n")

if __name__ == "__main__":
    demonstrate_sql_injection_protection()
