from sqlalchemy.orm import Session
from datetime import datetime
from models import BudgetControl


def enforce_budget(db: Session, estimated_cost: float):
    today = datetime.utcnow().date().isoformat()

    budget = (
        db.query(BudgetControl)
        .filter(BudgetControl.date == today)
        .with_for_update()
        .first()
    )

    if not budget:
        raise Exception("No budget configured for today.")

    if budget.is_locked:
        raise Exception("Daily budget locked.")

    projected = budget.current_spend_usd + estimated_cost

    if projected > budget.daily_limit_usd:
        budget.is_locked = True
        db.commit()
        raise Exception("Daily budget exceeded.")

    budget.current_spend_usd = projected
    db.commit()

    return projected
