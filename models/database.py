from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date,
    ForeignKey, Text, Enum, CheckConstraint, UniqueConstraint,
    create_engine, event
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()

class RoomType(str, enum.Enum):
    SINGLE   = "single"
    DOUBLE   = "double"
    SUITE    = "suite"
    DELUXE   = "deluxe"

class BookingStatus(str, enum.Enum):
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class ServiceCategory(str, enum.Enum):
    FOOD     = "food"
    SPA      = "spa"
    TRANSFER = "transfer"
    LAUNDRY  = "laundry"
    OTHER    = "other"

class Hotel(Base):
    __tablename__ = "hotels"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(200), nullable=False)
    address     = Column(String(500), nullable=False)
    city        = Column(String(100), nullable=False)
    country     = Column(String(100), nullable=False)
    stars       = Column(Integer, nullable=False)
    phone       = Column(String(20),  unique=True, nullable=False)
    email       = Column(String(150), unique=True, nullable=False)
    description = Column(Text)
    created_at  = Column(DateTime, default=func.now())

    __table_args__ = (
        CheckConstraint("stars >= 1 AND stars <= 5", name="ck_hotel_stars"),
    )

    rooms    = relationship("Room",    back_populates="hotel", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="hotel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Hotel id={self.id} name='{self.name}' stars={self.stars}>"

class Room(Base):
    __tablename__ = "rooms"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    hotel_id     = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    room_number  = Column(String(10), nullable=False)
    room_type    = Column(Enum(RoomType), nullable=False)
    floor        = Column(Integer, nullable=False)
    capacity     = Column(Integer, nullable=False)
    price_per_night = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    description  = Column(Text)
    created_at   = Column(DateTime, default=func.now())

    __table_args__ = (
        CheckConstraint("price_per_night > 0",    name="ck_room_price"),
        CheckConstraint("capacity >= 1",           name="ck_room_capacity"),
        CheckConstraint("floor >= 0",              name="ck_room_floor"),
        UniqueConstraint("hotel_id", "room_number", name="uq_hotel_room"),
    )

    hotel     = relationship("Hotel",    back_populates="rooms")
    bookings  = relationship("Booking",  back_populates="room")

    def __repr__(self):
        return f"<Room id={self.id} number='{self.room_number}' type={self.room_type}>"

class Client(Base):
    __tablename__ = "clients"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    first_name   = Column(String(100), nullable=False)
    last_name    = Column(String(100), nullable=False)
    email        = Column(String(150), unique=True, nullable=False)
    phone        = Column(String(20),  unique=True, nullable=False)
    passport_num = Column(String(50),  unique=True, nullable=False)
    date_of_birth = Column(Date)
    nationality  = Column(String(100))
    created_at   = Column(DateTime, default=func.now())

    bookings = relationship("Booking", back_populates="client")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __repr__(self):
        return f"<Client id={self.id} name='{self.full_name}'>"

class Booking(Base):
    __tablename__ = "bookings"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(Integer, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    room_id      = Column(Integer, ForeignKey("rooms.id",   ondelete="RESTRICT"), nullable=False)
    check_in     = Column(Date, nullable=False)
    check_out    = Column(Date, nullable=False)
    total_price  = Column(Float, nullable=False)
    status       = Column(Enum(BookingStatus), default=BookingStatus.PENDING, nullable=False)
    notes        = Column(Text)
    created_at   = Column(DateTime, default=func.now())
    updated_at   = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("check_out > check_in", name="ck_booking_dates"),
        CheckConstraint("total_price >= 0",     name="ck_booking_price"),
    )

    client   = relationship("Client",  back_populates="bookings")
    room     = relationship("Room",    back_populates="bookings")
    services = relationship("BookingService", back_populates="booking", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Booking id={self.id} status={self.status} check_in={self.check_in}>"

class Service(Base):
    __tablename__ = "services"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    hotel_id    = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(200), nullable=False)
    category    = Column(Enum(ServiceCategory), nullable=False)
    price       = Column(Float, nullable=False)
    description = Column(Text)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=func.now())

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_service_price"),
    )

    hotel    = relationship("Hotel",          back_populates="services")
    bookings = relationship("BookingService", back_populates="service")

    def __repr__(self):
        return f"<Service id={self.id} name='{self.name}' category={self.category}>"

class BookingService(Base):
    __tablename__ = "booking_services"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id",  ondelete="CASCADE"),  nullable=False)
    service_id = Column(Integer, ForeignKey("services.id",  ondelete="RESTRICT"), nullable=False)
    quantity   = Column(Integer, default=1, nullable=False)
    price      = Column(Float,   nullable=False)
    added_at   = Column(DateTime, default=func.now())

    __table_args__ = (
        CheckConstraint("quantity >= 1", name="ck_bs_quantity"),
        CheckConstraint("price >= 0",    name="ck_bs_price"),
    )
    booking = relationship("Booking", back_populates="services")
    service = relationship("Service", back_populates="bookings")

    def __repr__(self):
        return f"<BookingService booking_id={self.booking_id} service_id={self.service_id}>"


def init_db(db_url: str = "sqlite:///hotel_booking.db"):
    engine = create_engine(db_url, echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine