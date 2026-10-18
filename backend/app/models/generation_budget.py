from enum import Enum


class GenerationStatus(str, Enum):
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PARTIAL_COMPLETED = "PARTIAL_COMPLETED"


class BudgetDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
