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
    category: str | None = None  # None = auto-detected from description


class ExpenseOut(BaseModel):
    id: str
    description: str
    amount_rupees: float
    paid_by_member_id: str
    category: str
    category_emoji: str

    class Config:
        from_attributes = True


class ExpenseListItem(BaseModel):
    id: str
    description: str
    amount_rupees: float
    category: str
    category_emoji: str
    paid_by_member_id: str
    paid_by_name: str
    created_at: str


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


class PersonBar(BaseModel):
    member_id: str
    name: str
    paid_rupees: float
    fair_share_rupees: float
    net_rupees: float  # positive = owed money, negative = owes money


class CategoryBreakdownItem(BaseModel):
    category: str
    emoji: str
    amount_rupees: float
    pct: int


class InsightsResponse(BaseModel):
    group_id: str
    person_bars: list[PersonBar]
    category_breakdown: list[CategoryBreakdownItem]
    tips: list[str]
    ai_powered: bool
