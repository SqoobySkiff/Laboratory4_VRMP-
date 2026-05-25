from datetime import date
from typing import Optional
from sqlalchemy import create_engine, and_, or_, event
from sqlalchemy.orm import sessionmaker, Session

from models.database import (
    Base, Hotel, Room, Client, Booking, Service, BookingService,
    BookingStatus, RoomType, ServiceCategory, init_db,
)

def get_session_factory(db_url: str = "sqlite:///hotel_booking.db"):
    engine = init_db(db_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)

class BookingService_:

    def __init__(self, session: Session):
        self.session = session

    def add_booking(
        self,
        client_id: int,
        room_id: int,
        check_in: date,
        check_out: date,
        notes: str = "",
    ) -> Booking:

        if check_out <= check_in:
            raise ValueError("Дата виїзду має бути пізніше дати заїзду.")

        room = self.session.get(Room, room_id)
        if not room:
            raise ValueError(f"Кімнату з id={room_id} не знайдено.")
        if not room.is_available:
            raise ValueError(f"Кімната {room.room_number} недоступна.")

        conflict = (
            self.session.query(Booking)
            .filter(
                Booking.room_id == room_id,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                and_(
                    Booking.check_in  < check_out,
                    Booking.check_out > check_in,
                ),
            )
            .first()
        )
        if conflict:
            raise ValueError(
                f"Кімната вже заброньована з {conflict.check_in} по {conflict.check_out}."
            )

        nights = (check_out - check_in).days
        total_price = nights * room.price_per_night

        booking = Booking(
            client_id=client_id,
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            total_price=total_price,
            status=BookingStatus.CONFIRMED,
            notes=notes,
        )
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)

        print(f"Бронювання #{booking.id} створено. Вартість: {total_price:.2f} грн.")
        return booking

    def cancel_booking(self, booking_id: int) -> bool:
        booking = self.session.get(Booking, booking_id)
        if not booking:
            raise ValueError(f"Бронювання #{booking_id} не знайдено.")

        if booking.status == BookingStatus.CANCELLED:
            print(f"Бронювання #{booking_id} вже скасовано.")
            return False

        if booking.status == BookingStatus.COMPLETED:
            raise ValueError("Не можна скасувати завершене бронювання.")

        booking.status = BookingStatus.CANCELLED
        self.session.commit()
        print(f"Бронювання #{booking_id} скасовано.")
        return True

    def delete_booking(self, booking_id: int) -> bool:
        booking = self.session.get(Booking, booking_id)
        if not booking:
            raise ValueError(f"Бронювання #{booking_id} не знайдено.")

        if booking.status != BookingStatus.CANCELLED:
            raise ValueError("Можна видаляти лише скасовані бронювання.")

        self.session.delete(booking)
        self.session.commit()
        print(f"Бронювання #{booking_id} видалено.")
        return True

    def get_booking(self, booking_id: int) -> Optional[Booking]:
        return self.session.get(Booking, booking_id)

    def get_client_bookings(self, client_id: int) -> list[Booking]:
        return (
            self.session.query(Booking)
            .filter(Booking.client_id == client_id)
            .order_by(Booking.check_in.desc())
            .all()
        )

    def get_active_bookings(self) -> list[Booking]:
        return (
            self.session.query(Booking)
            .filter(Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]))
            .all()
        )


    def add_service_to_booking(
        self, booking_id: int, service_id: int, quantity: int = 1
    ) -> BookingService:
        booking = self.session.get(Booking, booking_id)
        if not booking:
            raise ValueError(f"Бронювання #{booking_id} не знайдено.")

        service = self.session.get(Service, service_id)
        if not service or not service.is_active:
            raise ValueError(f"Послугу #{service_id} не знайдено або вона неактивна.")

        total = service.price * quantity
        bs = BookingService(
            booking_id=booking_id,
            service_id=service_id,
            quantity=quantity,
            price=total,
        )
        booking.total_price += total
        self.session.add(bs)
        self.session.commit()
        print(f"Послугу '{service.name}' додано до бронювання #{booking_id}.")
        return bs


class RoomService:

    def __init__(self, session: Session):
        self.session = session

    def get_available_rooms(
        self,
        hotel_id: Optional[int] = None,
        check_in: Optional[date] = None,
        check_out: Optional[date] = None,
        room_type: Optional[RoomType] = None,
        max_price: Optional[float] = None,
        min_capacity: Optional[int] = None,
    ) -> list[Room]:
        query = self.session.query(Room).filter(Room.is_available == True)

        if hotel_id:
            query = query.filter(Room.hotel_id == hotel_id)
        if room_type:
            query = query.filter(Room.room_type == room_type)
        if max_price:
            query = query.filter(Room.price_per_night <= max_price)
        if min_capacity:
            query = query.filter(Room.capacity >= min_capacity)

        if check_in and check_out:
            booked_ids = (
                self.session.query(Booking.room_id)
                .filter(
                    Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                    and_(
                        Booking.check_in  < check_out,
                        Booking.check_out > check_in,
                    ),
                )
                .subquery()
            )
            query = query.filter(Room.id.not_in(booked_ids))

        rooms = query.order_by(Room.price_per_night).all()
        return rooms

    def add_room(
        self,
        hotel_id: int,
        room_number: str,
        room_type: RoomType,
        floor: int,
        capacity: int,
        price_per_night: float,
        description: str = "",
    ) -> Room:
        room = Room(
            hotel_id=hotel_id,
            room_number=room_number,
            room_type=room_type,
            floor=floor,
            capacity=capacity,
            price_per_night=price_per_night,
            description=description,
        )
        self.session.add(room)
        self.session.commit()
        self.session.refresh(room)
        print(f"Кімнату #{room.room_number} додано до готелю #{hotel_id}.")
        return room

    def set_availability(self, room_id: int, is_available: bool) -> None:
        room = self.session.get(Room, room_id)
        if not room:
            raise ValueError(f"Кімнату #{room_id} не знайдено.")
        room.is_available = is_available
        self.session.commit()
        status = "доступна" if is_available else "недоступна"
        print(f"Кімната #{room.room_number} тепер {status}.")


class ClientService:

    def __init__(self, session: Session):
        self.session = session

    def add_client(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        passport_num: str,
        date_of_birth: Optional[date] = None,
        nationality: str = "",
    ) -> Client:
        existing = (
            self.session.query(Client)
            .filter(
                or_(
                    Client.email == email,
                    Client.phone == phone,
                    Client.passport_num == passport_num,
                )
            )
            .first()
        )
        if existing:
            raise ValueError(f"Клієнт з такими даними вже існує (id={existing.id}).")

        client = Client(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            passport_num=passport_num,
            date_of_birth=date_of_birth,
            nationality=nationality,
        )
        self.session.add(client)
        self.session.commit()
        self.session.refresh(client)
        print(f"Клієнта '{client.full_name}' зареєстровано (id={client.id}).")
        return client

    def get_client_by_email(self, email: str) -> Optional[Client]:
        return self.session.query(Client).filter(Client.email == email).first()
