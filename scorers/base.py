"""
Base scorer module for the Institutional Momentum Trading System.

Provides the abstract base class and data class that all scoring
modules must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoreResult:
    """Result container for a scoring module's calculation.

    Attributes:
        score: The calculated score (can be negative due to penalties).
        max_score: The maximum possible score for this module.
        details: A dictionary of diagnostic info about the calculation.
        auto_skip: If True, this stock should be automatically skipped.
        skip_reason: Human-readable reason for the auto-skip.
    """
    score: float
    max_score: float
    details: dict = field(default_factory=dict)
    auto_skip: bool = False
    skip_reason: Optional[str] = None


class BaseScorer(ABC):
    """Abstract base class for all scoring modules.

    Each scorer implements a specific dimension of the institutional
    momentum scoring system. The calculate() method must return a
    ScoreResult with the score, diagnostic details, and auto-skip flag.
    """

    @abstractmethod
    def calculate(self, symbol: str, data: dict, bias: str = "LONG") -> ScoreResult:
        """Calculate the score based on the provided data.

        Args:
            symbol: The stock symbol being scored (e.g., 'RELIANCE').
            data: Dictionary containing the required input data for
                  this scorer. Each scorer defines its own expected keys.

        Returns:
            ScoreResult with the computed score, max possible score,
            diagnostic details, auto-skip flag, and skip reason.
        """
        pass
