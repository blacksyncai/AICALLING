"""Typed CRM tools: never arbitrary endpoints, executable code, or unbounded bulk writes."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["active", "won", "lost"] = "active"

class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["list_contacts", "find_contact", "create_contact", "list_pipelines", "create_pipeline", "add_stages", "move_stage", "field_catalog", "contact_fields", "add_note", "mark_dnc", "create_task", "create_pond", "create_stage", "list_sources", "set_contact_source"]
    name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    company: str = Field(default="", max_length=120)
    external_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")
    pipeline_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")
    stage_id: str = Field(default="", max_length=128)
    stages: list[StageInput] = Field(default_factory=list, max_length=20)
    query: str = Field(default="", max_length=120)
    limit: int = Field(default=25, ge=1, le=100)
    text: str = Field(default="", max_length=4000)
    due_date: date | None = None

    @model_validator(mode="after")
    def bounded(self):
        needed = {"create_contact": ["name"], "create_pipeline": ["name"],
                  "add_stages": ["pipeline_id", "stages"], "move_stage": ["external_id", "pipeline_id", "stage_id"],
                  "add_note": ["external_id", "text"], "mark_dnc": ["external_id"],
                  "contact_fields": ["external_id"], "create_task": ["external_id", "name", "due_date"], "create_pond": ["name"], "create_stage": ["name"], "set_contact_source": ["external_id", "name"]}
        for key in needed.get(self.action, []):
            if not getattr(self, key): raise ValueError(f"{self.action} needs {key}")
        if self.action in ("find_contact", "create_contact") and not (self.phone or self.email):
            raise ValueError("Provide an exact phone number or email address")
        if self.phone and not 7 <= sum(c.isdigit() for c in self.phone) <= 15:
            raise ValueError("Provide a phone number with 7 to 15 digits")
        if self.email and ("@" not in self.email or any(c.isspace() for c in self.email)):
            raise ValueError("Provide a valid email address")
        if len({s.label.casefold() for s in self.stages}) != len(self.stages):
            raise ValueError("Stage names must be unique")
        allowed = {"list_contacts": {"query", "limit"}, "find_contact": {"phone", "email"},
                   "create_contact": {"name", "phone", "email", "company"}, "list_pipelines": set(),
                   "create_pipeline": {"name", "stages"}, "add_stages": {"pipeline_id", "stages"},
                   "move_stage": {"external_id", "pipeline_id", "stage_id"}, "field_catalog": set(),
                   "contact_fields": {"external_id"}, "add_note": {"external_id", "text", "name"},
                   "mark_dnc": {"external_id"}, "create_task": {"external_id", "name", "due_date"},
                   "create_pond": {"name"}, "create_stage": {"name"}, "list_sources": set(), "set_contact_source": {"external_id", "name"}}[self.action]
        for key in self.model_fields_set - {"action"} - allowed:
            default = type(self).model_fields[key].get_default(call_default_factory=True)
            if getattr(self, key) != default: raise ValueError(f"{self.action} does not accept {key}")
        return self

READS = {"list_contacts", "find_contact", "list_pipelines", "field_catalog", "contact_fields", "list_sources"}
