from dataclasses import dataclass


@dataclass
class BudgetCheckResult:
    allowed: bool
    status: str
    estimated_cost: float
    remaining_budget: float


class BudgetService:
    """
    Cost guard before expensive AI generation.

    Budget exhaustion is treated as a workflow state,
    not as a technical exception.
    """

    def check(self, estimated_cost: float, remaining_budget: float):
        if estimated_cost > remaining_budget:
            return BudgetCheckResult(
                allowed=False,
                status="BUDGET_EXCEEDED",
                estimated_cost=estimated_cost,
                remaining_budget=remaining_budget,
            )

        return BudgetCheckResult(
            allowed=True,
            status="ALLOW",
            estimated_cost=estimated_cost,
            remaining_budget=remaining_budget,
        )
