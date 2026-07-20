from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from .models import ActionType, BatteryStatus

HEALTH_MAX_MAH = 6000


class MachineCreate(BaseModel):
    code: str
    customer: str | None = None
    division: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    install_date: date | None = None
    remark: str | None = None


class MachineUpdate(BaseModel):
    customer: str | None = None
    division: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    install_date: date | None = None
    remark: str | None = None


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    customer: str | None = None
    division: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    install_date: date | None = None
    remark: str | None = None


class BatteryCreate(BaseModel):
    serial: str | None = None
    machine_code: str | None = None
    end_user: str | None = None
    commission_date: date | None = None
    last_capacity_mah: int | None = None
    notes: str | None = None


class BatteryUpdate(BaseModel):
    machine_code: str | None = None
    end_user: str | None = None
    commission_date: date | None = None
    last_cell_replacement_date: date | None = None
    last_capacity_mah: int | None = None
    status: BatteryStatus | None = None
    notes: str | None = None


class LogCreate(BaseModel):
    description: str


class LogUpdate(BaseModel):
    description: str


class BatteryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    action_type: ActionType
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    description: str


class BatteryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    serial: str
    machine_code: str | None = None
    end_user: str | None = None
    commission_date: date | None = None
    last_cell_replacement_date: date | None = None
    last_capacity_mah: int | None = None
    status: BatteryStatus
    notes: str | None = None
    created_at: datetime

    @computed_field
    @property
    def health_percent(self) -> float | None:
        if self.last_capacity_mah is None:
            return None
        return round(min(100.0, self.last_capacity_mah / HEALTH_MAX_MAH * 100), 1)


class BatteryDetailOut(BatteryOut):
    logs: list[BatteryLogOut] = []


class DashboardSummary(BaseModel):
    total: int
    active: int
    maintenance: int
    retired: int
    needs_attention: list[BatteryOut]
