import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class BatteryStatus(str, enum.Enum):
    active = "active"
    maintenance = "maintenance"
    retired = "retired"


class ActionType(str, enum.Enum):
    created = "created"
    machine_change = "machine_change"
    end_user_change = "end_user_change"
    cell_replacement = "cell_replacement"
    capacity_check = "capacity_check"
    status_change = "status_change"
    note = "note"


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    division: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Battery(Base):
    __tablename__ = "batteries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    machine_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_cell_replacement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_capacity_mah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[BatteryStatus] = mapped_column(
        Enum(BatteryStatus), default=BatteryStatus.active
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    logs: Mapped[list["BatteryLog"]] = relationship(
        "BatteryLog",
        back_populates="battery",
        cascade="all, delete-orphan",
        order_by="desc(BatteryLog.timestamp)",
    )
    tests: Mapped[list["BatteryTest"]] = relationship(
        "BatteryTest",
        back_populates="battery",
        cascade="all, delete-orphan",
        order_by="desc(BatteryTest.test_date), desc(BatteryTest.id)",
    )


class BatteryTest(Base):
    __tablename__ = "battery_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battery_id: Mapped[int] = mapped_column(ForeignKey("batteries.id"))
    test_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Time/duration fields are stored as free text so any format the technician
    # keys in (clock time HH:MM or a duration like "2:37 hr") is preserved.
    charge_full_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capacity_after_charge_mah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_bar_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    second_bar_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alert_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shutdown_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_runtime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_to_zero_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    battery: Mapped["Battery"] = relationship("Battery", back_populates="tests")


class BatteryLog(Base):
    __tablename__ = "battery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battery_id: Mapped[int] = mapped_column(ForeignKey("batteries.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    action_type: Mapped[ActionType] = mapped_column(Enum(ActionType))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text)

    battery: Mapped["Battery"] = relationship("Battery", back_populates="logs")
