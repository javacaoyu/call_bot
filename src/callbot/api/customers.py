"""外呼客户 API（6.2）：外呼前选择客户，提供变量插槽数据源。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from callbot.data.models import Customer, get_engine

router = APIRouter(prefix="/api", tags=["customers"])


class CustomerIn(BaseModel):
    """新建客户请求体。"""

    name: str = Field(min_length=1, max_length=64)
    phone: str = Field(min_length=5, max_length=20)
    notes: str = ""


def _customer_dict(c: Customer) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "phone": c.phone,
        "notes": c.notes,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/customers")
async def list_customers() -> list[dict]:
    """客户列表（创建时间正序）。"""
    with Session(get_engine()) as session:
        customers = session.scalars(select(Customer).order_by(Customer.created_at)).all()
        return [_customer_dict(c) for c in customers]


@router.post("/customers")
async def create_customer(body: CustomerIn) -> dict:
    """新建客户。"""
    customer = Customer(name=body.name, phone=body.phone, notes=body.notes)
    with Session(get_engine(), expire_on_commit=False) as session:
        session.add(customer)
        session.commit()
        return _customer_dict(customer)


@router.put("/customers/{customer_id}")
async def update_customer(customer_id: str, body: CustomerIn) -> dict:
    """编辑客户。"""
    try:
        uid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法客户 ID") from None
    with Session(get_engine(), expire_on_commit=False) as session:
        customer = session.get(Customer, uid)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户不存在")
        customer.name = body.name
        customer.phone = body.phone
        customer.notes = body.notes
        session.commit()
        return _customer_dict(customer)


@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str) -> dict:
    """删除客户。"""
    try:
        uid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="非法客户 ID") from None
    with Session(get_engine()) as session:
        customer = session.get(Customer, uid)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户不存在")
        session.delete(customer)
        session.commit()
        return {"deleted": customer_id}
