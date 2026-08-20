import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.settlement import compute_net_balances, settle_balances, settle_group


def total_settled(transactions):
    return sum(t.amount for t in transactions)


def test_already_settled_group():
    balances = {"alice": 0, "bob": 0, "charlie": 0}
    assert settle_balances(balances) == []


def test_single_debtor_creditor_pair():
    balances = {"alice": 150, "charlie": -150}
    txns = settle_balances(balances)
    assert len(txns) == 1
    assert txns[0].payer == "charlie"
    assert txns[0].payee == "alice"
    assert txns[0].amount == 150


def test_three_person_dinner_and_cab():
    # Alice paid 300 for dinner, Bob paid 150 for cab, Charlie paid 0.
    # Fair share is 150 each.
    paid = {"alice": 300, "bob": 150, "charlie": 0}
    owed = {"alice": 150, "bob": 150, "charlie": 150}
    txns = settle_group(paid, owed)
    assert len(txns) == 1
    assert txns[0].payer == "charlie"
    assert txns[0].payee == "alice"
    assert txns[0].amount == 150


def test_four_person_worked_example():
    balances = {"alice": 200, "bob": 100, "charlie": -150, "dave": -150}
    txns = settle_balances(balances)
    # n-1 bound: 4 non-zero balances -> at most 3 transactions
    assert len(txns) <= 3
    assert total_settled(txns) == 300
    # Net effect must reconcile: sum paid by each person to what they owed
    net = {"alice": 0, "bob": 0, "charlie": 0, "dave": 0}
    for t in txns:
        net[t.payer] -= t.amount
        net[t.payee] += t.amount
    assert net["alice"] == 200
    assert net["bob"] == 100
    assert net["charlie"] == -150
    assert net["dave"] == -150


def test_circular_debt_collapses():
    # A owes B 100, B owes C 100, C owes A 100 -> net balances all zero
    # This models three pairwise debts that should fully cancel out.
    paid = {"a": 100, "b": 100, "c": 100}
    owed = {"a": 100, "b": 100, "c": 100}
    txns = settle_group(paid, owed)
    assert txns == []


def test_minimum_transaction_bound():
    # k people with non-zero balances -> at most k-1 transactions, always.
    balances = {"p1": 50, "p2": 30, "p3": 20, "p4": -40, "p5": -60}
    txns = settle_balances(balances)
    non_zero_people = sum(1 for v in balances.values() if v != 0)
    assert len(txns) <= non_zero_people - 1


def test_uneven_split_no_precision_loss():
    # Ensure integer minor-unit math doesn't lose money.
    paid = {"alice": 1000, "bob": 0, "charlie": 0}
    owed = {"alice": 334, "bob": 333, "charlie": 333}
    txns = settle_group(paid, owed)
    assert total_settled(txns) == 666  # bob + charlie owe alice 333 each


def test_compute_net_balances_missing_keys():
    # Someone who paid but has no explicit "owed" entry (e.g. owes 0)
    paid = {"alice": 100}
    owed = {"alice": 50, "bob": 50}
    net = compute_net_balances(paid, owed)
    assert net["alice"] == 50
    assert net["bob"] == -50
