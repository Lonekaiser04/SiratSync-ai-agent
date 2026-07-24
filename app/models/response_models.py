"""
Pydantic response models. Nested action/reminder/habit/dua structures are
typed explicitly so the API contract is self-documenting and validated on
the way out, rather than relying on a loosely-typed `Dict`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SourceItem(BaseModel):
    type: str
    label: str
    reference: str | None = None
    detail: str | None = None
    icon: str | None = None


class ReminderAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str | None = None
    title: str | None = None
    time: str | None = None
    priority: str | None = None
    description: str | None = None


class HabitAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str | None = None
    description: str | None = None
    difficulty: str | None = None
    estimated_minutes: int | None = None
    target: str | None = None


class DuaAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    situation: str | None = None
    dua: str | None = None
    meaning: str | None = None
    transliteration: str | None = None


class QuickAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str | None = None
    label: str | None = None
    surah: str | None = None


class ResourceItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str | None = None
    fixes: list[str] | None = None
    available: list[str] | None = None


class ActionsPayload(BaseModel):
    """Typed replacement for the previous untyped `Dict` actions field."""

    reminders: list[ReminderAction] = []
    habits: list[HabitAction] = []
    duas: list[DuaAction] = []
    resources: list[ResourceItem] = []
    encouragement: str = ""
    quick_actions: list[QuickAction] = []


class ChatResponse(BaseModel):
    reply: str
    intent: str
    sub_intent: str | None = None
    sentiment: str = "neutral"
    actions: ActionsPayload = ActionsPayload()
    suggestions: list[str] = []
    motivational_quote: str | None = None
    timestamp: str
    sources: list[SourceItem] = []


class SummarizeResponse(BaseModel):
    summary: str
    original_length: int
    summary_length: int
