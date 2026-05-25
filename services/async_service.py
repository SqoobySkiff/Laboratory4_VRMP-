import asyncio
from datetime import date
from typing import Optional

from sqlalchemy import and_, or_, select, update, delete, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from models.database import (
    Base, Hotel, Room, Client, Booking, Service, BookingService,
    BookingStatus, RoomType,
)

ASYNC_DB_URL = "sqlite+aiosqlite:///hotel_booking_async.db"

async def init_async_db(db_url: str = ASYNC_DB_URL):
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)

    return engine

def get_async_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class AsyncBookingService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_booking(
        self,
        client_id: int,
        room_id: int,
        check_in: date,
        check_out: date,
        notes: str = "",
    ) -> Booking:
        if check_out <= check_in:
            raise ValueError("Дата виїзду має бути пізніше дати заїзду.")

        result = await self.session.execute(
            select(Room).where(Room.id == room_id)
        )
        room = result.scalar_one_or_none()
        if not room:
            raise ValueError(f"Кімнату id={room_id} не знайдено.")
        if not room.is_available:
            raise ValueError(f"Кімната {room.room_number} недоступна.")

        conflict_result = await self.session.execute(
            select(Booking).where(
                Booking.room_id == room_id,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                and_(
                    Booking.check_in  < check_out,
                    Booking.check_out > check_in,
                ),
            )
        )
        conflict = conflict_result.scalar_one_or_none()
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
        await self.session.commit()
        await self.session.refresh(booking)

        print(f"[ASYNC] Бронювання #{booking.id} створено. Вартість: {total_price:.2f} грн.")
        return booking

    async def cancel_booking(self, booking_id: int) -> bool:
        result = await self.session.execute(
            select(Booking).where(Booking.id == booking_id)
        )
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(f"Бронювання #{booking_id} не знайдено.")

        if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
            print(f"Не можна скасувати (статус: {booking.status}).")
            return False

        await self.session.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(status=BookingStatus.CANCELLED)
        )
        await self.session.commit()
        print(f"[ASYNC] Бронювання #{booking_id} скасовано.")
        return True

    async def get_booking_with_details(self, booking_id: int) -> Optional[Booking]:
        result = await self.session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client),
                selectinload(Booking.room).selectinload(Room.hotel),
                selectinload(Booking.services).selectinload(BookingService.service),
            )
            .where(Booking.id == booking_id)
        )
        return result.scalar_one_or_none()

class AsyncRoomService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_available_rooms(
        self,
        hotel_id: Optional[int] = None,
        check_in: Optional[date] = None,
        check_out: Optional[date] = None,
        room_type: Optional[RoomType] = None,
        max_price: Optional[float] = None,
        min_capacity: Optional[int] = None,
    ) -> list[Room]:
        stmt = select(Room).where(Room.is_available == True)

        if hotel_id:
            stmt = stmt.where(Room.hotel_id == hotel_id)
        if room_type:
            stmt = stmt.where(Room.room_type == room_type)
        if max_price:
            stmt = stmt.where(Room.price_per_night <= max_price)
        if min_capacity:
            stmt = stmt.where(Room.capacity >= min_capacity)

        if check_in and check_out:
            booked_subq = (
                select(Booking.room_id)
                .where(
                    Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                    and_(
                        Booking.check_in  < check_out,
                        Booking.check_out > check_in,
                    ),
                )
                .scalar_subquery()
            )
            stmt = stmt.where(Room.id.not_in(booked_subq))

        stmt = stmt.order_by(Room.price_per_night)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_hotel_statistics(self, hotel_id: int) -> dict:
        total_rooms_q    = select(func.count(Room.id)).where(Room.hotel_id == hotel_id)
        available_rooms_q = select(func.count(Room.id)).where(
            Room.hotel_id == hotel_id, Room.is_available == True
        )
        avg_price_q = select(func.avg(Room.price_per_night)).where(Room.hotel_id == hotel_id)

        total_r, avail_r, avg_r = await asyncio.gather(
            self.session.execute(total_rooms_q),
            self.session.execute(available_rooms_q),
            self.session.execute(avg_price_q),
        )

        return {
            "hotel_id":        hotel_id,
            "total_rooms":     total_r.scalar() or 0,
            "available_rooms": avail_r.scalar() or 0,
            "avg_price":       round(avg_r.scalar() or 0, 2),
        }

async def async_demo():
    engine = await init_async_db()
    AsyncSession_ = get_async_session_factory(engine)

    async with AsyncSession_() as session:
        hotel = Hotel(
            name="Grand Palace", address="вул. Хрещатик, 1",
            city="Київ", country="Україна", stars=5,
            phone="+380441234567", email="grand@palace.ua",
        )
        session.add(hotel)
        await session.commit()
        await session.refresh(hotel)

        rooms = [
            Room(hotel_id=hotel.id, room_number=f"10{i}", room_type=RoomType.DOUBLE,
                 floor=1, capacity=2, price_per_night=1200.0 + i * 100)
            for i in range(1, 4)
        ]
        session.add_all(rooms)
        await session.commit()

        client = Client(
            first_name="Іван", last_name="Франко",
            email="ivan@franko.ua", phone="+380991112233",
            passport_num="AA123456",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)

        booking_svc = AsyncBookingService(session)
        booking = await booking_svc.add_booking(
            client_id=client.id,
            room_id=rooms[0].id,
            check_in=date(2025, 8, 1),
            check_out=date(2025, 8, 5),
        )

        room_svc = AsyncRoomService(session)
        available = await room_svc.get_available_rooms(
            hotel_id=hotel.id,
            check_in=date(2025, 8, 1),
            check_out=date(2025, 8, 5),
        )
        print(f"Доступних кімнат: {len(available)}")

        stats = await room_svc.get_hotel_statistics(hotel.id)
        print(f"Статистика: {stats}")

        details = await booking_svc.get_booking_with_details(booking.id)
        if details:
            print(f"Бронювання клієнта: {details.client.full_name}, "
                  f"готель: {details.room.hotel.name}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(async_demo())
