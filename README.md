# SplitSmart

Group expense splitting that settles debts using the **minimum possible number
of transactions**, instead of logging a separate debt for every expense.

Live demo: _add your deployed link here_

## The problem

Most expense-splitting tools log a debt record per expense. For a group of
`n` people splitting `m` expenses, that can produce up to `O(n·m)` individual
"who owes whom" records — most of which are redundant once you look at the
group's actual net balances.

**Example:** Alice paid for hotel, Bob paid for the cab, Charlie paid for
dinner. A naive tracker creates a debt entry per person per expense. But once
you net everything out, it's very likely the whole group can settle up in
just 1–2 transfers.

## The algorithm

1. **Collapse to net balances.** For each person, `net = amount_paid - fair_share`.
   Positive → they're owed money (creditor). Negative → they owe money (debtor).
   This step alone eliminates most redundancy — expense history doesn't matter
   once balances are netted.

2. **Greedy max-creditor / max-debtor matching.** Repeatedly match the
   person owed the most against the person who owes the most, settle the
   smaller of the two amounts, and remove whoever hits zero. Implemented
   with two max-heaps for `O(n log n)` performance.

3. **Why it's optimal.** Each transaction can fully zero out at most one
   person's balance without affecting anyone else's. So settling `k` people
   with non-zero balances requires at least `k-1` transactions — and the
   greedy approach achieves exactly that bound. This isn't just "an"
   algorithm, it provably produces the minimum transaction count.

See [`app/settlement.py`](app/settlement.py) for the implementation and
[`tests/test_settlement.py`](tests/test_settlement.py) for edge cases:
already-settled groups, circular debt that cancels out completely, integer
precision handling for money (no floating-point drift), and a property test
verifying the `n-1` transaction bound.

## Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** Vanilla HTML/JS (no build step, served directly by FastAPI)
- **Deployment:** Docker

## Running locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

Run the algorithm test suite:

```bash
pytest tests/ -v
```

## Running with Docker

```bash
docker build -t splitsmart .
docker run -p 8000:8000 splitsmart
```

## API

| Method | Endpoint                                  | Description                          |
|--------|--------------------------------------------|---------------------------------------|
| POST   | `/groups`                                  | Create a group with member names      |
| GET    | `/groups/{id}`                             | Get group details                     |
| POST   | `/groups/by-invite/{code}/members`         | Join a group via invite code          |
| POST   | `/groups/{id}/expenses`                    | Log an expense (equal split default)  |
| GET    | `/groups/{id}/settlement`                  | Get the minimal settlement plan       |

## What's next

- Unequal/percentage-based splits (the `expense_splits` table already
  supports this — no schema change needed)
- Auth beyond invite codes
- Push notifications for new expenses
