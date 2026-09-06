from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "sleep", "activity", "workouts", "recovery", "cardiovascular", "body"
]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    period: str | None = None
    focus: list[Category] = Field(
        default_factory=lambda: ["sleep", "activity", "recovery", "workouts"],
        min_length=1,
        max_length=6,
    )


class AskRequest(AnalysisRequest):
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class Scores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sleep: float | None = Field(default=None, ge=0, le=100)
    activity: float | None = Field(default=None, ge=0, le=100)
    recovery: float | None = Field(default=None, ge=0, le=100)


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Category
    title: str
    observation: str
    reasoning: str
    priority: Literal["low", "medium", "high"]
    based_on: list[str] = Field(min_length=1)


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Category
    title: str
    recommendation: str
    based_on: list[str] = Field(min_length=1)


class AIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=8000)
    score: Scores = Field(default_factory=Scores)
    insights: list[Insight] = Field(max_length=15)
    suggestions: list[Suggestion] = Field(max_length=15)
    warnings: list[str]
    data_gaps: list[str]
