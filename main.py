import asyncio
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db, RoomType, ServiceCategory
from services.booking_service import (
    get_session_factory,
    BookingService_ as SyncBookingService,
    RoomService,
    ClientService,
)
from services.async_service import (
    AsyncBookingService,
    AsyncRoomService,
    init_async_db,
    get_async_session_factory,
)
from utils.security import (
    SecureBookingService,
    InputValidator,
    ValidationError,
    demonstrate_sql_injection_protection,
)
from models.database import Hotel, Service

for db_file in ["demo.db", "demo_async.db", "demo_secure.db"]:
    if os.path.exists(db_file):
        os.remove(db_file)
        print(f"Видалено: {db_file}")

def demo_sync():
    print("\n" + "═" * 60)
    print("  РІВНІ 1–2")

    engine = init_db("sqlite:///demo.db")
    SessionFactory = get_session_factory("sqlite:///demo.db")

    with SessionFactory() as session:
        hotel = Hotel(
            name="Hotel Ukraine", address="пл. Незалежності, 1",
            city="Київ", country="Україна", stars=4,
            phone="+380441000001", email="ukraine@hotel.ua",
        )
        session.add(hotel)
        session.commit()
        session.refresh(hotel)
        print(f"\nГотель створено: {hotel}")

        services = [
            Service(hotel_id=hotel.id, name="Сніданок",       category=ServiceCategory.FOOD,     price=250.0),
            Service(hotel_id=hotel.id, name="СПА",  category=ServiceCategory.SPA,      price=800.0),
            Service(hotel_id=hotel.id, name="Перевозка з/до аеропорту", category=ServiceCategory.TRANSFER, price=600.0),
        ]
        session.add_all(services)
        session.commit()
        print(f"Послуги додано: {[s.name for s in services]}")

        room_svc = RoomService(session)
        rooms = []
        for i in range(1, 6):
            r = room_svc.add_room(
                hotel_id=hotel.id,
                room_number=f"20{i}",
                room_type=RoomType.DOUBLE if i <= 3 else RoomType.SUITE,
                floor=2, capacity=2,
                price_per_night=1500.0 + i * 200,
                description=f"Просторий номер",
            )
            rooms.append(r)

        client_svc = ClientService(session)
        client = client_svc.add_client(
            first_name="Леся", last_name="Лесівна",
            email="lesya@lesya.ua", phone="+380501234567",
            passport_num="UA7890",
            date_of_birth=date(1990, 5, 20),
            nationality="Українка",
        )

        booking_svc = SyncBookingService(session)
        today = date.today()
        booking = booking_svc.add_booking(
            client_id=client.id,
            room_id=rooms[0].id,
            check_in=today + timedelta(days=7),
            check_out=today + timedelta(days=10),
            notes="Тихий номер",
        )

        session.refresh(services[0])
        booking_svc.add_service_to_booking(booking.id, services[0].id, quantity=3)

        available = room_svc.get_available_rooms(
            hotel_id=hotel.id,
            check_in=today + timedelta(days=7),
            check_out=today + timedelta(days=10),
        )
        print(f"\nДоступних кімнат на 7–10 день: {len(available)}")
        for r in available:
            print(f"Кімната {r.room_number} | {r.room_type.value} | {r.price_per_night} грн/ніч")

        booking_svc.cancel_booking(booking.id)

        all_b = booking_svc.get_client_bookings(client.id)
        print(f"\nБронювань клієнта: {len(all_b)}, статуси: {[b.status.value for b in all_b]}")

    print("\nРівні 1–2 виконано успішно")


async def demo_async():
    print("\n" + "═" * 60)
    print(" РІВЕНЬ 3")

    engine = await init_async_db("sqlite+aiosqlite:///demo_async.db")
    AsyncSessionFactory = get_async_session_factory(engine)

    async with AsyncSessionFactory() as session:
        hotel = Hotel(
            name="Async Hotel", address="вул. Цифрова, 66",
            city="Харків", country="Україна", stars=5,
            phone="+380572000001", email="hotel@async.ua",
        )
        session.add(hotel)
        await session.commit()
        await session.refresh(hotel)

        from models.database import Room
        rooms = [
            Room(hotel_id=hotel.id, room_number=f"3{i:02d}",
                 room_type=RoomType.DOUBLE, floor=3,
                 capacity=2, price_per_night=2000.0 + i * 150)
            for i in range(1, 5)
        ]
        session.add_all(rooms)
        await session.commit()

        from models.database import Client as C
        client = C(
            first_name="Тарас", last_name="Тарасенко",
            email="taras@tarasenko.ua", phone="+380632223344",
            passport_num="TT9999",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        for r in rooms:
            await session.refresh(r)

        booking_svc = AsyncBookingService(session)
        today = date.today()
        booking = await booking_svc.add_booking(
            client_id=client.id,
            room_id=rooms[0].id,
            check_in=today + timedelta(days=14),
            check_out=today + timedelta(days=17),
        )

        room_svc = AsyncRoomService(session)
        available = await room_svc.get_available_rooms(
            hotel_id=hotel.id,
            check_in=today + timedelta(days=14),
            check_out=today + timedelta(days=17),
        )
        print(f"\n[ASYNC] Доступних кімнат: {len(available)}")

        stats = await room_svc.get_hotel_statistics(hotel.id)
        print(f"[ASYNC] Статистика готелю: {stats}")

        details = await booking_svc.get_booking_with_details(booking.id)
        if details:
            print(f"[ASYNC] Клієнт: {details.client.full_name}, "
                  f"Готель: {details.room.hotel.name}, "
                  f"Сума: {details.total_price:.2f} грн")

        await booking_svc.cancel_booking(booking.id)

    await engine.dispose()
    print("\nРівень 3 виконано успішно")

def demo_security():
    print("\n" + "═" * 60)
    print(" РІВЕНЬ 4")

    demonstrate_sql_injection_protection()

    engine = init_db("sqlite:///demo_secure.db")
    from sqlalchemy.orm import sessionmaker
    SessionFactory = sessionmaker(bind=engine)

    with SessionFactory() as session:
        hotel = Hotel(
            name="Secure Hotel", address="вул. Безпечна, 66",
            city="Львів", country="Україна", stars=3,
            phone="+3803053600", email="hotel@hotel.ua",
        )
        session.add(hotel)
        session.commit()
        session.refresh(hotel)

        svc = SecureBookingService(session)

        print("....Захищене додавання клієнта....")

        try:
            client = svc.add_client_safe(
                first_name="Марія",
                last_name="Марієнко",
                email="maria@marienko.ua",
                phone="+38020000000",
                passport_num="MM6566",
            )
            print(f"Клієнт доданий: {client.full_name}")
        except ValidationError as e:
            print(f"Error {e}")

        print("\n....Спроба ін'єкції через email....")
        try:
            svc.add_client_safe(
                first_name="Hacker'; DROP TABLE clients; --",
                last_name="Hack",
                email="hack@hack.com",
                phone="+3801000000",
                passport_num="001",
            )
            print("Ін'єкція пройшла! ")
        except ValidationError as e:
            print(f"Заблоковано: {e}")

        print("\nБезпечний пошук")
        results = svc.search_clients_safe("Марія")
        print(f"Знайдено клієнтів: {len(results)}")

    print("\nРівень 4 виконано успішно")

if __name__ == "__main__":
    print(" Lab4: система бронювання готелів ")

    demo_sync()
    asyncio.run(demo_async())
    demo_security()

    print("ВСІ РІВНІ ВИКОНАНО УСПІШНО")
