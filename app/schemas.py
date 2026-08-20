from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str
    member_names: list[str] = Field(..., min_length=1)


class GroupOut(BaseModel):
    id: str
    name: str
    invite_code: str
    members: list["MemberOut"]

    class Config:
        from_attributes = True


class MemberOut(BaseModel):
    id: str
    name: str

    class Config:
        from_attributes = True


class MemberAdd(BaseModel):
    name: str


class ExpenseCreate(BaseModel):
    description: str
    amount_rupees: float  # convenience: user-facing amount in rupees
    paid_by_member_id: str
    split_among_member_ids: list[str] | None = None  # None = split among all members


class ExpenseOut(BaseModel):
    id: str
    description: str
    amount_rupees: float
    paid_by_member_id: str

    class Config:
        from_attributes = True


class TransactionOut(BaseModel):
    payer_id: str
    payer_name: str
    payee_id: str
    payee_name: str
    amount_rupees: float


class GraphEdge(BaseModel):
    from_id: str
    from_name: str
    to_id: str
    to_name: str
    amount_rupees: float


class SettlementResponse(BaseModel):
    group_id: str
    transactions: list[TransactionOut]
    transaction_count: int
    naive_transaction_count: int
    naive_edges: list[GraphEdge]
    members: list["MemberOut"]
