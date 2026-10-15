"""Bounded, validated rules; the assistant cannot emit executable code or HTTP requests."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.call_log import CALL_OUTCOMES

VERIFICATIONS = ("name_confirmed", "named_voicemail", "wrong_number", "unverified")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    agent_id: UUID | None = None
    campaign_id: UUID | None = None
    pond_id: str = Field(default="", max_length=128)


class Condition(StrictModel):
    kind: Literal["verification", "outcome", "field"] = "verification"
    value: str = Field(default="name_confirmed", max_length=500)
    field: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9_ .-]*$")
    operator: Literal["equals", "contains", "exists"] = "equals"

    @model_validator(mode="after")
    def supported(self):
        if self.kind == "verification" and self.value not in VERIFICATIONS:
            raise ValueError("Choose a supported verification result")
        if self.kind == "outcome" and self.value not in CALL_OUTCOMES:
            raise ValueError("Choose a supported call outcome")
        if self.kind == "field" and (not self.field or self.field.startswith("_")):
            raise ValueError("Choose a public extracted field")
        return self


class Action(StrictModel):
    kind: Literal["blacksync_pond", "crm_pond", "crm_stage", "crm_tag"]
    target_id: str = Field(min_length=1, max_length=200)
    pipeline_id: str = Field(default="", max_length=128)


class RuleSpec(StrictModel):
    source: Source = Field(default_factory=Source)
    condition: Condition = Field(default_factory=Condition)
    actions: list[Action] = Field(min_length=1, max_length=4)

    @field_validator("actions")
    @classmethod
    def unique_actions(cls, actions):
        keys = [(a.kind, a.target_id, a.pipeline_id) for a in actions]
        if len(keys) != len(set(keys)):
            raise ValueError("Remove duplicate actions")
        if sum(a.kind == "crm_pond" for a in actions) > 1:
            raise ValueError("A rule can route to only one CRM pond")
        return actions


class RuleIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    request: str = Field(default="", max_length=4000)
    spec: RuleSpec
