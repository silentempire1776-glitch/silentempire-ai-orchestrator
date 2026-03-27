from sqlalchemy.orm import Session
from models import ProviderPricing


def calculate_cost(
    db: Session,
    provider: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
) -> float:
    pricing = (
        db.query(ProviderPricing)
        .filter(
            ProviderPricing.provider == provider,
            ProviderPricing.model == model,
        )
        .first()
    )

    if not pricing:
        raise Exception(f"No pricing configured for {provider}:{model}")

    input_cost = (tokens_input / 1000) * pricing.input_cost_per_1k_tokens
    output_cost = (tokens_output / 1000) * pricing.output_cost_per_1k_tokens

    return round(input_cost + output_cost, 8)
