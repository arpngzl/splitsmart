from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str
    member_names: list[str] = Field(..., min_length=1)
    emoji: str | None = None


class MemberOut(BaseModel):
    id: str
    name: str
    avatar_color: str

    class Config:
        from_attributes = True


class GroupOut(BaseModel):
    id: str
    name: str
    emoji: str
    invite_code: str
    members: list[MemberOut]

    class Config:
        from_attributes = True


class MemberAdd(BaseModel):
    name: str


class ExpenseCreate(BaseModel):
    description: str
    amount_rupees: float
    paid_by_member_id: str
    split_among_member_ids: list[str] | None = None
    category: str | None = None
    notes: str | None = None


class ExpenseUpdate(BaseModel):
    description: str | None = None
    amount_rupees: float | None = None
    paid_by_member_id: str | None = None
    split_among_member_ids: list[str] | None = None
    category: str | None = None
    notes: str | None = None


class ExpenseOut(BaseModel):
    id: str
    description: str
    amount_rupees: float
    paid_by_member_id: str
    category: str
    category_emoji: str
    notes: str | None = None

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
    notes: str | None = None
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
    members: list[MemberOut]


class PersonBar(BaseModel):
    member_id: str
    name: str
    paid_rupees: float
    fair_share_rupees: float
    net_rupees: float


class CategoryBreakdownItem(BaseModel):
    category: str
    emoji: str
    amount_rupees: float
    pct: int


class TrendPoint(BaseModel):
    label: str
    amount_rupees: float


class InsightsResponse(BaseModel):
    group_id: str
    person_bars: list[PersonBar]
    category_breakdown: list[CategoryBreakdownItem]
    tips: list[str]
    ai_powered: bool
    total_spent_rupees: float
    trend: list[TrendPoint]
    recap: str
    recap_ai_powered: bool


class PaymentCreate(BaseModel):
    from_member_id: str
    to_member_id: str
    amount_rupees: float
    note: str | None = None


class PaymentOut(BaseModel):
    id: str
    from_member_id: str
    from_name: str
    to_member_id: str
    to_name: str
    amount_rupees: float
    note: str | None = None
    created_at: str


class BudgetSet(BaseModel):
    monthly_limit_rupees: float


class BudgetStatus(BaseModel):
    monthly_limit_rupees: float | None
    spent_this_month_rupees: float
    pct_used: int
    alert: str | None
    ai_powered: bool


class SmartParseRequest(BaseModel):
    text: str


class SmartParseResult(BaseModel):
    description: str
    amount_rupees: float
    paid_by_member_id: str | None
    paid_by_name: str | None
    split_among_member_ids: list[str] | None
    category: str | None
    category_emoji: str | None
    ai_powered: bool


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    ai_powered: bool


class Achievement(BaseModel):
    emoji: str
    title: str
    description: str


class AchievementsResponse(BaseModel):
    achievements: list[Achievement]
