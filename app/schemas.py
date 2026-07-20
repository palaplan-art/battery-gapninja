from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from .models import ActionType, BatteryStatus

HEALTH_MAX_MAH = 6000


class MachineFields(BaseModel):
    customer: str | None = None
    division: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    system: str | None = None
    install_date: date | None = None
    install_status: str | None = None
    gauge_block_sn: str | None = None
    last_calibration_date: date | None = None
    next_calibration_date: date | None = None
    wifi_model: str | None = None
    wifi_ip: str | None = None
    wifi_sn: str | None = None
    barcode_scanner_sn: str | None = None
    pc_model: str | None = None
    pc_sn_tag: str | None = None
    remark: str | None = None


class MachineCreate(MachineFields):
    code: str


class MachineUpdate(MachineFields):
    pass


class MachineOut(MachineFields):
    model_config = ConfigDict(from_attributes=True)

    code: str


class MachineLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    description: str


class MachineDetailOut(MachineOut):
    logs: list[MachineLogOut] = []
    batteries: list["BatteryOut"] = []


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


class BatteryTestBase(BaseModel):
    test_date: date | None = None
    charge_full_time: str | None = None
    capacity_after_charge_mah: int | None = None
    start_time: str | None = None
    first_bar_time: str | None = None
    second_bar_time: str | None = None
    alert_time: str | None = None
    shutdown_time: str | None = None
    total_runtime: str | None = None
    run_to_zero_time: str | None = None
    remark: str | None = None


class BatteryTestCreate(BatteryTestBase):
    pass


class BatteryTestUpdate(BatteryTestBase):
    pass


class BatteryTestOut(BatteryTestBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


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
    updated_at: datetime | None = None

    @computed_field
    @property
    def health_percent(self) -> float | None:
        if self.last_capacity_mah is None:
            return None
        return round(min(100.0, self.last_capacity_mah / HEALTH_MAX_MAH * 100), 1)


class BatteryDetailOut(BatteryOut):
    logs: list[BatteryLogOut] = []
    tests: list[BatteryTestOut] = []


class DashboardSummary(BaseModel):
    total: int
    active: int
    maintenance: int
    retired: int
    end_users: list[str] = []


# Resolve the forward reference to BatteryOut used in MachineDetailOut.
MachineDetailOut.model_rebuild()
