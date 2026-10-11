"""
Balance computation: derive account balances from postings.

A balance is not stored. It is DERIVED from postings. This is what
makes temporal queries possible: to get the balance at time T, we sum
only the postings that existed at time T.

Definition:
    total_debit(account, T)  = sum of debit_kobo  for postings
                               where account_code = account
                               and created_at <= T
    total_credit(account, T) = sum of credit_kobo for postings
                               where account_code = account
                               and created_at <= T
    net(account, T) = total_debit - total_credit

Sign convention:
    For asset accounts (Cash, Receivables), a positive net means the
    account holds value.
    For income accounts (Revenue), a negative net means income was
    earned (because revenue is credited, not debited).

Callers interpret the sign based on the account type. The balance
endpoint returns total_debit, total_credit, and net so the caller
has full context.
"""
from datetime import datetime
from sqlalchemy import func
from models import Posting


def get_balance(db, account_code: str, as_of: datetime) -> dict:
    """
    Return the balance of `account_code` as of `as_of`.

    Returns:
        {
            "account_code": str,
            "as_of": iso8601 str,
            "total_debit": int,
            "total_credit": int,
            "net": int,
        }
    """
    row = (
        db.query(
            func.coalesce(func.sum(Posting.debit_kobo), 0).label("total_debit"),
            func.coalesce(func.sum(Posting.credit_kobo), 0).label("total_credit"),
        )
        .filter(Posting.account_code == account_code)
        .filter(Posting.created_at <= as_of)
        .one()
    )

    total_debit = int(row.total_debit)
    total_credit = int(row.total_credit)

    return {
        "account_code": account_code,
        "as_of": as_of.isoformat(),
        "total_debit": total_debit,
        "total_credit": total_credit,
        "net": total_debit - total_credit,
    }
