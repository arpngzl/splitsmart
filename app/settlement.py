"""
Debt settlement algorithm.

Given a group's net balances, computes the minimum number of transactions
needed to settle everyone up.

Approach: greedy max-creditor / max-debtor matching using heaps.
Each transaction fully zeroes out at least one person's balance, so for
`k` people with non-zero balances, this produces at most k-1 transactions
— which is the theoretical minimum (you cannot fully settle k independent
non-zero balances in fewer than k-1 transfers).

Complexity: O(n log n) — each of the up to n-1 settlement steps does a
constant number of heap push/pop operations, each O(log n).
"""

import heapq
from dataclasses import dataclass

# Amounts are handled in integer paise/cents internally to avoid floating
# point drift; the API layer converts to/from rupees.
EPSILON = 0  # working in integer minor units, so exact comparison is safe


@dataclass
class Transaction:
    payer: str
    payee: str
    amount: int  # minor units (e.g. paise)


def compute_net_balances(paid: dict[str, int], owed: dict[str, int]) -> dict[str, int]:
    """
    paid: how much each person actually paid, in minor units
    owed: how much each person's fair share was, in minor units
    Returns net balance per person = paid - owed.
    Positive => creditor (is owed money). Negative => debtor (owes money).
    """
    people = set(paid) | set(owed)
    return {p: paid.get(p, 0) - owed.get(p, 0) for p in people}


def settle_balances(net_balances: dict[str, int]) -> list[Transaction]:
    """
    Greedy minimum-transaction settlement.

    Uses two max-heaps (creditors, debtors) keyed by absolute balance.
    Python's heapq is a min-heap, so we push negated values for creditors
    and the raw (negative) values for debtors to get max-heap behavior.
    """
    creditors: list[tuple[int, str]] = []  # (-balance, name), balance > 0
    debtors: list[tuple[int, str]] = []    # (balance, name), balance < 0  (already "most negative first")

    for person, balance in net_balances.items():
        if balance > EPSILON:
            heapq.heappush(creditors, (-balance, person))
        elif balance < -EPSILON:
            heapq.heappush(debtors, (balance, person))
        # balance == 0 -> already settled, nothing to do

    transactions: list[Transaction] = []

    while creditors and debtors:
        neg_credit, creditor = heapq.heappop(creditors)
        debit, debtor = heapq.heappop(debtors)

        credit = -neg_credit          # positive amount creditor is owed
        debt = -debit                 # positive amount debtor owes

        settle_amount = min(credit, debt)
        transactions.append(Transaction(payer=debtor, payee=creditor, amount=settle_amount))

        remaining_credit = credit - settle_amount
        remaining_debt = debt - settle_amount

        if remaining_credit > EPSILON:
            heapq.heappush(creditors, (-remaining_credit, creditor))
        if remaining_debt > EPSILON:
            heapq.heappush(debtors, (-remaining_debt, debtor))

    return transactions


def settle_group(paid: dict[str, int], owed: dict[str, int]) -> list[Transaction]:
    """Convenience wrapper: paid/owed dicts -> minimal transaction list."""
    balances = compute_net_balances(paid, owed)
    return settle_balances(balances)
