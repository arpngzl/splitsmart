from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app import models, schemas, insights, receipt_scan
from app.settlement import settle_group

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SplitSmart", description="Minimum-transaction group expense settlement")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RUPEES_TO_MINOR = 100  # paise per rupee


def to_minor(rupees: float) -> int:
    return round(rupees * RUPEES_TO_MINOR)


def to_rupees(minor: int) -> float:
    return round(minor / RUPEES_TO_MINOR, 2)


@app.post("/groups", response_model=schemas.GroupOut)
def create_group(payload: schemas.GroupCreate, db: Session = Depends(get_db)):
    group = models.Group(name=payload.name)
    db.add(group)
    db.flush()  # get group.id before adding members

    for name in payload.member_names:
        db.add(models.Member(group_id=group.id, name=name))

    db.commit()
    db.refresh(group)
    return group


@app.get("/groups/{group_id}", response_model=schemas.GroupOut)
def get_group(group_id: str, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@app.post("/groups/by-invite/{invite_code}/members", response_model=schemas.MemberOut)
def join_group(invite_code: str, payload: schemas.MemberAdd, db: Session = Depends(get_db)):
    group = db.query(models.Group).filter(models.Group.invite_code == invite_code).first()
    if not group:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    member = models.Member(group_id=group.id, name=payload.name)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@app.post("/groups/{group_id}/expenses", response_model=schemas.ExpenseOut)
def add_expense(group_id: str, payload: schemas.ExpenseCreate, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

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
    )
    db.add(expense)
    db.flush()

    # Equal split among the chosen members; last person absorbs rounding remainder
    n = len(split_ids)
    base_share = amount_minor // n
    remainder = amount_minor - base_share * n

    for i, member_id in enumerate(split_ids):
        share = base_share + (remainder if i == n - 1 else 0)
        db.add(models.ExpenseSplit(expense_id=expense.id, member_id=member_id, share_amount=share))

    db.commit()
    db.refresh(expense)

    return schemas.ExpenseOut(
        id=expense.id,
        description=expense.description,
        amount_rupees=to_rupees(expense.amount),
        paid_by_member_id=expense.paid_by_member_id,
        category=expense.category,
        category_emoji=insights.emoji_for(expense.category),
    )


@app.get("/groups/{group_id}/expenses", response_model=list[schemas.ExpenseListItem])
def list_expenses(group_id: str, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members_by_id = {m.id: m for m in group.members}
    ordered = sorted(group.expenses, key=lambda e: e.created_at, reverse=True)

    return [
        schemas.ExpenseListItem(
            id=e.id,
            description=e.description,
            amount_rupees=to_rupees(e.amount),
            category=e.category,
            category_emoji=insights.emoji_for(e.category),
            paid_by_member_id=e.paid_by_member_id,
            paid_by_name=members_by_id[e.paid_by_member_id].name,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in ordered
    ]


@app.get("/groups/{group_id}/settlement", response_model=schemas.SettlementResponse)
def get_settlement(group_id: str, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members_by_id = {m.id: m for m in group.members}

    paid: dict[str, int] = {m.id: 0 for m in group.members}
    owed: dict[str, int] = {m.id: 0 for m in group.members}

    # naive_pair_amounts aggregates every individual expense-split debt by
    # (debtor, creditor) pair, so the "before" graph is readable instead of
    # showing one edge per expense. This is still the naive representation —
    # it's exactly what you'd get without netting balances at all.
    naive_pair_amounts: dict[tuple[str, str], int] = {}

    for expense in group.expenses:
        paid[expense.paid_by_member_id] += expense.amount
        for split in expense.splits:
            owed[split.member_id] += split.share_amount
            if split.member_id != expense.paid_by_member_id:
                key = (split.member_id, expense.paid_by_member_id)
                naive_pair_amounts[key] = naive_pair_amounts.get(key, 0) + split.share_amount

    naive_count = sum(
        1
        for expense in group.expenses
        for s in expense.splits
        if s.member_id != expense.paid_by_member_id
    )

    transactions = settle_group(paid, owed)

    txn_out = [
        schemas.TransactionOut(
            payer_id=t.payer,
            payer_name=members_by_id[t.payer].name,
            payee_id=t.payee,
            payee_name=members_by_id[t.payee].name,
            amount_rupees=to_rupees(t.amount),
        )
        for t in transactions
    ]

    naive_edges_out = [
        schemas.GraphEdge(
            from_id=debtor_id,
            from_name=members_by_id[debtor_id].name,
            to_id=creditor_id,
            to_name=members_by_id[creditor_id].name,
            amount_rupees=to_rupees(amount),
        )
        for (debtor_id, creditor_id), amount in naive_pair_amounts.items()
    ]

    return schemas.SettlementResponse(
        group_id=group_id,
        transactions=txn_out,
        transaction_count=len(txn_out),
        naive_transaction_count=naive_count,
        naive_edges=naive_edges_out,
        members=[schemas.MemberOut(id=m.id, name=m.name) for m in group.members],
    )


@app.get("/groups/{group_id}/insights", response_model=schemas.InsightsResponse)
def get_insights(group_id: str, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members_by_id = {m.id: m for m in group.members}
    paid: dict[str, int] = {m.id: 0 for m in group.members}
    owed: dict[str, int] = {m.id: 0 for m in group.members}

    for expense in group.expenses:
        paid[expense.paid_by_member_id] += expense.amount
        for split in expense.splits:
            owed[split.member_id] += split.share_amount

    transactions = settle_group(paid, owed)

    result = insights.build_insights(
        group_name=group.name,
        members_by_id=members_by_id,
        paid=paid,
        owed=owed,
        transactions=transactions,
        expenses=group.expenses,
    )

    person_bars = [
        schemas.PersonBar(
            member_id=m.id,
            name=m.name,
            paid_rupees=to_rupees(paid[m.id]),
            fair_share_rupees=to_rupees(owed[m.id]),
            net_rupees=to_rupees(paid[m.id] - owed[m.id]),
        )
        for m in group.members
    ]

    category_breakdown = [
        schemas.CategoryBreakdownItem(
            category=row["category"],
            emoji=row["emoji"],
            amount_rupees=to_rupees(row["amount_minor"]),
            pct=row["pct"],
        )
        for row in result["category_breakdown"]
    ]

    return schemas.InsightsResponse(
        group_id=group_id,
        person_bars=person_bars,
        category_breakdown=category_breakdown,
        tips=result["tips"],
        ai_powered=result["ai_powered"],
    )


@app.post("/groups/{group_id}/scan-receipt", response_model=schemas.ReceiptScanResponse)
def scan_group_receipt(group_id: str, payload: schemas.ReceiptScanRequest, db: Session = Depends(get_db)):
    group = db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    result = receipt_scan.scan_receipt(payload.image_base64, payload.media_type)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Couldn't read that receipt. Make sure ANTHROPIC_API_KEY is set on the "
                "server, and try a clearer, well-lit photo with the total visible."
            ),
        )

    return schemas.ReceiptScanResponse(
        description=result["description"],
        amount_rupees=result["amount_rupees"],
        category=result["category"],
        category_emoji=insights.emoji_for(result["category"]),
        merchant=result.get("merchant"),
    )


@app.get("/api")
def api_root():
    return {"status": "ok", "service": "SplitSmart"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
