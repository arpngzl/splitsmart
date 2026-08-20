from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app import models, schemas, insights, ai
from app.settlement import settle_group

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SplitSmart", description="Minimum-transaction group expense settlement, AI-powered")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RUPEES_TO_MINOR = 100
AVATAR_PALETTE = ["#ff8fa3", "#7dd3c0", "#ffd166", "#9b8cf2", "#4fc3a1", "#ff6f91", "#7d6cf0", "#ffb84d"]


def to_minor(rupees: float) -> int:
    return round(rupees * RUPEES_TO_MINOR)


def to_rupees(minor: int) -> float:
    return round(minor / RUPEES_TO_MINOR, 2)


def get_group_or_404(db: Session, group_id: str) -> models.Group:
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def compute_paid_owed(group: models.Group) -> tuple[dict[str, int], dict[str, int]]:
    paid: dict[str, int] = {m.id: 0 for m in group.members}
    owed: dict[str, int] = {m.id: 0 for m in group.members}
    for expense in group.expenses:
        paid[expense.paid_by_member_id] = paid.get(expense.paid_by_member_id, 0) + expense.amount
        for split in expense.splits:
            owed[split.member_id] = owed.get(split.member_id, 0) + split.share_amount
    return paid, owed


def apply_payments(group: models.Group, paid: dict[str, int], owed: dict[str, int]) -> None:
    """Recorded real-world payments net a debtor/creditor pair. Modeled as the
    payer's 'paid' increasing and the payee's 'owed' increasing by the same
    amount, which cancels that much balance out of the settlement math."""
    for p in group.payments:
        paid[p.from_member_id] = paid.get(p.from_member_id, 0) + p.amount
        owed[p.to_member_id] = owed.get(p.to_member_id, 0) + p.amount


def build_facts(group: models.Group, paid: dict, owed: dict, transactions, members_by_id: dict) -> dict:
    breakdown = insights.category_breakdown(group.expenses)
    return {
        "group": group.name,
        "members": [
            {
                "name": m.name,
                "paid_rupees": round(paid.get(m.id, 0) / 100, 2),
                "fair_share_rupees": round(owed.get(m.id, 0) / 100, 2),
            }
            for m in group.members
        ],
        "category_breakdown": [
            {"category": r["category"], "pct": r["pct"], "amount_rupees": round(r["amount_minor"] / 100, 2)}
            for r in breakdown
        ],
        "settlement_transaction_count": len(transactions),
        "total_spent_rupees": round(sum(e.amount for e in group.expenses) / 100, 2),
        "expense_count": len(group.expenses),
    }


# --------------------------------------------------------------- groups --

@app.post("/groups", response_model=schemas.GroupOut)
def create_group(payload: schemas.GroupCreate, db: Session = Depends(get_db)):
    group = models.Group(name=payload.name, emoji=payload.emoji or "🧾")
    db.add(group)
    db.flush()

    for i, name in enumerate(payload.member_names):
        db.add(models.Member(group_id=group.id, name=name, avatar_color=AVATAR_PALETTE[i % len(AVATAR_PALETTE)]))

    db.commit()
    db.refresh(group)
    return group


@app.get("/groups/{group_id}", response_model=schemas.GroupOut)
def get_group(group_id: str, db: Session = Depends(get_db)):
    return get_group_or_404(db, group_id)


@app.get("/groups/by-invite/{invite_code}", response_model=schemas.GroupOut)
def get_group_by_invite(invite_code: str, db: Session = Depends(get_db)):
    group = db.query(models.Group).filter(models.Group.invite_code == invite_code).first()
    if not group:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    return group


@app.post("/groups/by-invite/{invite_code}/members", response_model=schemas.MemberOut)
def join_group(invite_code: str, payload: schemas.MemberAdd, db: Session = Depends(get_db)):
    group = db.query(models.Group).filter(models.Group.invite_code == invite_code).first()
    if not group:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    color = AVATAR_PALETTE[len(group.members) % len(AVATAR_PALETTE)]
    member = models.Member(group_id=group.id, name=payload.name, avatar_color=color)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


# -------------------------------------------------------------- expenses -

@app.post("/groups/{group_id}/expenses", response_model=schemas.ExpenseOut)
def add_expense(group_id: str, payload: schemas.ExpenseCreate, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    member_ids = {m.id for m in group.members}
    if payload.paid_by_member_id not in member_ids:
        raise HTTPException(status_code=400, detail="paid_by_member_id not in group")

    split_ids = payload.split_among_member_ids or list(member_ids)
    invalid = set(split_ids) - member_ids
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown member ids: {invalid}")

    amount_minor = to_minor(payload.amount_rupees)
    category = payload.category or insights.categorize(payload.description)

    expense = models.Expense(
        group_id=group_id,
        description=payload.description,
        amount=amount_minor,
        category=category,
        paid_by_member_id=payload.paid_by_member_id,
        notes=payload.notes,
    )
    db.add(expense)
    db.flush()
    _write_splits(db, expense.id, amount_minor, split_ids)
    db.commit()
    db.refresh(expense)

    return schemas.ExpenseOut(
        id=expense.id, description=expense.description, amount_rupees=to_rupees(expense.amount),
        paid_by_member_id=expense.paid_by_member_id, category=expense.category,
        category_emoji=insights.emoji_for(expense.category), notes=expense.notes,
    )


def _write_splits(db: Session, expense_id: str, amount_minor: int, split_ids: list[str]):
    n = len(split_ids)
    base_share = amount_minor // n
    remainder = amount_minor - base_share * n
    for i, member_id in enumerate(split_ids):
        share = base_share + (remainder if i == n - 1 else 0)
        db.add(models.ExpenseSplit(expense_id=expense_id, member_id=member_id, share_amount=share))


@app.patch("/groups/{group_id}/expenses/{expense_id}", response_model=schemas.ExpenseOut)
def update_expense(group_id: str, expense_id: str, payload: schemas.ExpenseUpdate, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    expense = db.get(models.Expense, expense_id)
    if not expense or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")

    member_ids = {m.id for m in group.members}

    if payload.description is not None:
        expense.description = payload.description
    if payload.category is not None:
        expense.category = payload.category
    if payload.notes is not None:
        expense.notes = payload.notes
    if payload.paid_by_member_id is not None:
        if payload.paid_by_member_id not in member_ids:
            raise HTTPException(status_code=400, detail="paid_by_member_id not in group")
        expense.paid_by_member_id = payload.paid_by_member_id

    amount_minor = to_minor(payload.amount_rupees) if payload.amount_rupees is not None else expense.amount
    split_ids = payload.split_among_member_ids
    if split_ids is not None:
        invalid = set(split_ids) - member_ids
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unknown member ids: {invalid}")

    if payload.amount_rupees is not None or split_ids is not None:
        expense.amount = amount_minor
        existing_ids = split_ids or [s.member_id for s in expense.splits]
        for s in list(expense.splits):
            db.delete(s)
        db.flush()
        _write_splits(db, expense.id, amount_minor, existing_ids)

    db.commit()
    db.refresh(expense)
    return schemas.ExpenseOut(
        id=expense.id, description=expense.description, amount_rupees=to_rupees(expense.amount),
        paid_by_member_id=expense.paid_by_member_id, category=expense.category,
        category_emoji=insights.emoji_for(expense.category), notes=expense.notes,
    )


@app.delete("/groups/{group_id}/expenses/{expense_id}")
def delete_expense(group_id: str, expense_id: str, db: Session = Depends(get_db)):
    expense = db.get(models.Expense, expense_id)
    if not expense or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    return {"status": "deleted", "id": expense_id}


@app.get("/groups/{group_id}/expenses", response_model=list[schemas.ExpenseListItem])
def list_expenses(
    group_id: str,
    db: Session = Depends(get_db),
    category: str | None = None,
    member_id: str | None = None,
    q: str | None = None,
):
    group = get_group_or_404(db, group_id)
    members_by_id = {m.id: m for m in group.members}
    ordered = sorted(group.expenses, key=lambda e: e.created_at, reverse=True)

    if category:
        ordered = [e for e in ordered if e.category == category]
    if member_id:
        ordered = [e for e in ordered if e.paid_by_member_id == member_id or any(s.member_id == member_id for s in e.splits)]
    if q:
        ql = q.lower()
        ordered = [e for e in ordered if ql in e.description.lower()]

    return [
        schemas.ExpenseListItem(
            id=e.id, description=e.description, amount_rupees=to_rupees(e.amount),
            category=e.category, category_emoji=insights.emoji_for(e.category),
            paid_by_member_id=e.paid_by_member_id, paid_by_name=members_by_id[e.paid_by_member_id].name,
            notes=e.notes, created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in ordered
    ]


# ------------------------------------------------------------ settlement -

@app.get("/groups/{group_id}/settlement", response_model=schemas.SettlementResponse)
def get_settlement(group_id: str, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    members_by_id = {m.id: m for m in group.members}

    paid, owed = compute_paid_owed(group)

    naive_pair_amounts: dict[tuple[str, str], int] = {}
    for expense in group.expenses:
        for split in expense.splits:
            if split.member_id != expense.paid_by_member_id:
                key = (split.member_id, expense.paid_by_member_id)
                naive_pair_amounts[key] = naive_pair_amounts.get(key, 0) + split.share_amount
    naive_count = sum(1 for e in group.expenses for s in e.splits if s.member_id != e.paid_by_member_id)

    apply_payments(group, paid, owed)
    transactions = settle_group(paid, owed)

    txn_out = [
        schemas.TransactionOut(
            payer_id=t.payer, payer_name=members_by_id[t.payer].name,
            payee_id=t.payee, payee_name=members_by_id[t.payee].name,
            amount_rupees=to_rupees(t.amount),
        )
        for t in transactions
    ]
    naive_edges_out = [
        schemas.GraphEdge(
            from_id=d, from_name=members_by_id[d].name, to_id=c, to_name=members_by_id[c].name,
            amount_rupees=to_rupees(amount),
        )
        for (d, c), amount in naive_pair_amounts.items()
    ]

    return schemas.SettlementResponse(
        group_id=group_id, transactions=txn_out, transaction_count=len(txn_out),
        naive_transaction_count=naive_count, naive_edges=naive_edges_out,
        members=[schemas.MemberOut(id=m.id, name=m.name, avatar_color=m.avatar_color) for m in group.members],
    )


# --------------------------------------------------------------- payments -

@app.post("/groups/{group_id}/payments", response_model=schemas.PaymentOut)
def record_payment(group_id: str, payload: schemas.PaymentCreate, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    member_ids = {m.id for m in group.members}
    if payload.from_member_id not in member_ids or payload.to_member_id not in member_ids:
        raise HTTPException(status_code=400, detail="Unknown member id")

    payment = models.Payment(
        group_id=group_id, from_member_id=payload.from_member_id, to_member_id=payload.to_member_id,
        amount=to_minor(payload.amount_rupees), note=payload.note,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    members_by_id = {m.id: m for m in group.members}
    return schemas.PaymentOut(
        id=payment.id, from_member_id=payment.from_member_id, from_name=members_by_id[payment.from_member_id].name,
        to_member_id=payment.to_member_id, to_name=members_by_id[payment.to_member_id].name,
        amount_rupees=to_rupees(payment.amount), note=payment.note,
        created_at=payment.created_at.isoformat() if payment.created_at else "",
    )


@app.get("/groups/{group_id}/payments", response_model=list[schemas.PaymentOut])
def list_payments(group_id: str, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    members_by_id = {m.id: m for m in group.members}
    ordered = sorted(group.payments, key=lambda p: p.created_at, reverse=True)
    return [
        schemas.PaymentOut(
            id=p.id, from_member_id=p.from_member_id, from_name=members_by_id[p.from_member_id].name,
            to_member_id=p.to_member_id, to_name=members_by_id[p.to_member_id].name,
            amount_rupees=to_rupees(p.amount), note=p.note,
            created_at=p.created_at.isoformat() if p.created_at else "",
        )
        for p in ordered
    ]


# ----------------------------------------------------------------- budget -

@app.post("/groups/{group_id}/budget", response_model=schemas.BudgetStatus)
def set_budget(group_id: str, payload: schemas.BudgetSet, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    if group.budget:
        group.budget.monthly_limit = to_minor(payload.monthly_limit_rupees)
    else:
        db.add(models.Budget(group_id=group_id, monthly_limit=to_minor(payload.monthly_limit_rupees)))
    db.commit()
    return get_budget(group_id, db)


@app.get("/groups/{group_id}/budget", response_model=schemas.BudgetStatus)
def get_budget(group_id: str, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    now = datetime.now(timezone.utc)
    spent_minor = sum(
        e.amount for e in group.expenses
        if e.created_at and e.created_at.year == now.year and e.created_at.month == now.month
    )

    if not group.budget:
        return schemas.BudgetStatus(
            monthly_limit_rupees=None, spent_this_month_rupees=to_rupees(spent_minor),
            pct_used=0, alert=None, ai_powered=False,
        )

    limit_minor = group.budget.monthly_limit
    pct = round(spent_minor / limit_minor * 100) if limit_minor else 0
    alert, ai_powered = ai.budget_alert({"pct_used": pct, "spent_rupees": to_rupees(spent_minor), "limit_rupees": to_rupees(limit_minor)})

    return schemas.BudgetStatus(
        monthly_limit_rupees=to_rupees(limit_minor), spent_this_month_rupees=to_rupees(spent_minor),
        pct_used=pct, alert=alert, ai_powered=ai_powered,
    )


# --------------------------------------------------------------- insights -

@app.get("/groups/{group_id}/insights", response_model=schemas.InsightsResponse)
def get_insights(group_id: str, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    paid, owed = compute_paid_owed(group)
    paid_adj, owed_adj = dict(paid), dict(owed)
    apply_payments(group, paid_adj, owed_adj)
    transactions = settle_group(paid_adj, owed_adj)

    breakdown = insights.category_breakdown(group.expenses)
    trend_rows = insights.weekly_trend(group.expenses)

    facts = build_facts(group, paid_adj, owed_adj, transactions, {m.id: m for m in group.members})
    tips, tips_ai = ai.spending_tips(facts)
    recap, recap_ai = ai.group_recap(facts)

    person_bars = [
        schemas.PersonBar(
            member_id=m.id, name=m.name, paid_rupees=to_rupees(paid[m.id]),
            fair_share_rupees=to_rupees(owed[m.id]), net_rupees=to_rupees(paid[m.id] - owed[m.id]),
        )
        for m in group.members
    ]
    category_breakdown = [
        schemas.CategoryBreakdownItem(category=r["category"], emoji=r["emoji"], amount_rupees=to_rupees(r["amount_minor"]), pct=r["pct"])
        for r in breakdown
    ]
    trend = [schemas.TrendPoint(label=r["label"], amount_rupees=to_rupees(r["amount_minor"])) for r in trend_rows]

    return schemas.InsightsResponse(
        group_id=group_id, person_bars=person_bars, category_breakdown=category_breakdown,
        tips=tips, ai_powered=tips_ai, total_spent_rupees=to_rupees(sum(e.amount for e in group.expenses)),
        trend=trend, recap=recap, recap_ai_powered=recap_ai,
    )


# ------------------------------------------------------------ AI features -

@app.post("/groups/{group_id}/ai/smart-parse", response_model=schemas.SmartParseResult)
def smart_parse(group_id: str, payload: schemas.SmartParseRequest, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    name_to_member = {m.name: m for m in group.members}
    draft, ai_powered = ai.smart_parse_expense(payload.text, list(name_to_member.keys()))

    paid_by_name = draft.get("paid_by")
    paid_by_member = name_to_member.get(paid_by_name) if paid_by_name else None

    split_names = draft.get("split_among") or []
    split_ids = [name_to_member[n].id for n in split_names if n in name_to_member] or None

    category = draft.get("category") or insights.categorize(draft.get("description", ""))

    return schemas.SmartParseResult(
        description=draft.get("description") or "Expense",
        amount_rupees=float(draft.get("amount_rupees") or 0),
        paid_by_member_id=paid_by_member.id if paid_by_member else None,
        paid_by_name=paid_by_member.name if paid_by_member else None,
        split_among_member_ids=split_ids,
        category=category, category_emoji=insights.emoji_for(category),
        ai_powered=ai_powered,
    )


@app.post("/groups/{group_id}/ai/chat", response_model=schemas.ChatResponse)
def chat(group_id: str, payload: schemas.ChatRequest, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    paid, owed = compute_paid_owed(group)
    apply_payments(group, paid, owed)
    transactions = settle_group(dict(paid), dict(owed))
    facts = build_facts(group, paid, owed, transactions, {m.id: m for m in group.members})
    answer, ai_powered = ai.chat_answer(payload.question, facts)
    return schemas.ChatResponse(answer=answer, ai_powered=ai_powered)


@app.get("/groups/{group_id}/achievements", response_model=schemas.AchievementsResponse)
def achievements(group_id: str, db: Session = Depends(get_db)):
    group = get_group_or_404(db, group_id)
    paid, owed = compute_paid_owed(group)
    badges: list[schemas.Achievement] = []

    if group.expenses:
        top_payer_id = max(paid, key=paid.get)
        members_by_id = {m.id: m for m in group.members}
        if paid[top_payer_id] > 0:
            badges.append(schemas.Achievement(emoji="👑", title="Big Spender", description=f"{members_by_id[top_payer_id].name} has fronted the most cash."))

        payer_counts: dict[str, int] = {}
        for e in group.expenses:
            payer_counts[e.paid_by_member_id] = payer_counts.get(e.paid_by_member_id, 0) + 1
        most_active = max(payer_counts, key=payer_counts.get)
        if payer_counts[most_active] >= 2:
            badges.append(schemas.Achievement(emoji="⚡", title="Generous Soul", description=f"{members_by_id[most_active].name} has covered {payer_counts[most_active]} expenses."))

        breakdown = insights.category_breakdown(group.expenses)
        if breakdown and breakdown[0]["category"] == "food":
            badges.append(schemas.Achievement(emoji="🍔", title="Foodie Crew", description="Food is this group's #1 spending category."))
        if breakdown and breakdown[0]["category"] == "travel":
            badges.append(schemas.Achievement(emoji="✈️", title="Jetsetters", description="Travel leads the group's spending."))

        if all(abs(paid[m.id] - owed[m.id]) < 1 for m in group.members):
            badges.append(schemas.Achievement(emoji="🕊️", title="Debt Free", description="Every balance is squared right now."))

        naive_count = sum(1 for e in group.expenses for s in e.splits if s.member_id != e.paid_by_member_id)
        transactions = settle_group(dict(paid), dict(owed))
        if naive_count - len(transactions) >= 2:
            badges.append(schemas.Achievement(emoji="🧮", title="Settlement Savior", description=f"SplitSmart cut {naive_count - len(transactions)} payments out of the settle-up."))

        if group.payments:
            badges.append(schemas.Achievement(emoji="🤝", title="Squared Up", description=f"{len(group.payments)} real payment{'s' if len(group.payments) != 1 else ''} recorded."))

        if len(group.expenses) >= 10:
            badges.append(schemas.Achievement(emoji="🔥", title="On a Roll", description=f"{len(group.expenses)} expenses logged and counting."))

    if not badges:
        badges.append(schemas.Achievement(emoji="🌱", title="Just Getting Started", description="Add your first expense to start earning badges."))

    return schemas.AchievementsResponse(achievements=badges)


@app.get("/api")
def api_root():
    return {"status": "ok", "service": "SplitSmart"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
