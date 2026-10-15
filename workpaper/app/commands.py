"""Typed commands: every write to the workpaper is validated here before it reaches the log.

A command that fails validation never becomes an event, so the log only ever
holds well-formed facts. The HTTP layer turns validation errors into 422s with
a readable message instead of a server error.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError, field_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Opt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class Cmd(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- adjustments and findings
class Adjust(Cmd):
    type: Literal["adjust"]
    line: Ref
    delta: float | None = None
    new_value: float | None = None
    reason: Text
    authority: Opt = ""
    category: str | None = None
    basis_fed: float | None = None
    basis_ca: float | None = None

    @field_validator("new_value")
    @classmethod
    def one_of(cls, v, info):
        if v is None and info.data.get("delta") is None:
            raise ValueError("give either delta or new_value")
        return v


class RevertAdjustment(Cmd):
    type: Literal["revert_adjustment"]
    adjustment: Ref
    reason: Text


class ApproveAdjustment(Cmd):
    type: Literal["approve_adjustment"]
    adjustment: Ref


class AcceptFinding(Cmd):
    type: Literal["accept_finding"]
    finding: Ref
    reason: Opt = ""
    authority: Opt = ""
    batch: str | None = None


class DismissFinding(Cmd):
    type: Literal["dismiss_finding"]
    finding: Ref
    reason: Text
    authority: Opt = ""
    disposition: Literal["dismissed", "deferred"] = "dismissed"
    batch: str | None = None


class FindingToClient(Cmd):
    type: Literal["finding_to_client"]
    finding: Ref
    text: Text
    to: Literal["client"] = "client"


# ---------------------------------------------------------------- evidence
class Verify(Cmd):
    type: Literal["verify"]
    target: Ref | None = None
    targets: list[Ref] | None = Field(default=None, max_length=1000)
    method: Ref
    note: Opt = ""
    evidence: list[Ref] = []
    batch: str | None = None

    @field_validator("targets")
    @classmethod
    def need_target(cls, v, info):
        if not v and not info.data.get("target"):
            raise ValueError("give target or targets")
        return v


class DisposeDocument(Cmd):
    type: Literal["dispose_document"]
    document: Ref
    status: Literal["reviewed_not_input", "used_by_workpaper", "superseded", "duplicate", "out_of_scope"]
    reason: Text
    batch: str | None = None


class FixHousehold(Cmd):
    type: Literal["fix_household"]
    person: Ref
    field: Literal["ssn", "name", "dob"]
    value: Text
    reason: Text
    evidence: list[Ref] = []


class ExplainVariance(Cmd):
    type: Literal["explain_variance"]
    key: Ref
    text: Text
    evidence: list[Ref] = []
    batch: str | None = None


# ---------------------------------------------------------------- people
class Note(Cmd):
    type: Literal["note"]
    target: Ref
    text: Text
    blocking: bool = False
    assignee: Ref | None = None
    kind: Literal["review", "question"] = "review"


class Reply(Cmd):
    type: Literal["reply"]
    note: Ref
    text: Text
    attachments: list[Any] = []


class ResolveNote(Cmd):
    type: Literal["resolve_note"]
    note: Ref
    text: Opt | None = None


class ReopenNote(Cmd):
    type: Literal["reopen_note"]
    note: Ref


class AskClient(Cmd):
    type: Literal["ask_client"]
    text: Text
    target: Ref | None = None
    to: Literal["client"] = "client"


class Answer(Cmd):
    type: Literal["answer"]
    question: Ref
    text: Text
    attachments: list[Any] = []


class ReviewAnswer(Cmd):
    type: Literal["review_answer"]
    question: Ref
    text: Opt = "Answer reviewed."


class Signoff(Cmd):
    type: Literal["signoff"]
    area: Ref
    level: Literal["preparer", "reviewer", "partner"]
    note: Opt = ""


class WithdrawSignoff(Cmd):
    type: Literal["withdraw_signoff"]
    area: Ref
    level: Literal["preparer", "reviewer", "partner"]


class CompleteStep(Cmd):
    type: Literal["complete_step"]
    step: Literal["identity", "prior_year"]
    note: Opt = ""
    evidence: list[Ref] = []


class Decide(Cmd):
    type: Literal["decide"]
    topic: Ref
    choice: Text
    rationale: Opt = ""
    authority: Opt = ""
    answers: list[dict] | None = None
    what_if: Ref | None = None
    finding: Ref | None = None


class LogTime(Cmd):
    type: Literal["log_time"]
    area: Ref
    hours: float = Field(gt=0, le=24)
    note: Opt = ""


class Assign(Cmd):
    type: Literal["assign"]
    role: Literal["preparer", "reviewer", "partner"]
    staff: Ref


class Standard(Cmd):
    type: Literal["standard"]
    path: Literal["variance_review.flag_if_change_over_percent", "variance_review.and_over_amount", "partner_signoff_over", "retention_years"]
    value: float = Field(ge=0)
    reason: Opt = ""


class Seen(Cmd):
    type: Literal["seen"]
    seq: int | None = None


class Reveal(Cmd):
    type: Literal["reveal"]
    target: Ref
    field: Opt = ""
    reason: Opt = ""


# ---------------------------------------------------------------- filing
class SendToClient(Cmd):
    type: Literal["send_to_client"]
    force: bool = False


class ClientApprove(Cmd):
    type: Literal["client_approve"]


class Transmit(Cmd):
    type: Literal["transmit"]
    force: bool = False


class Deliver(Cmd):
    type: Literal["deliver"]


class StartAmendment(Cmd):
    type: Literal["start_amendment"]
    reason: Text


class RespondNotice(Cmd):
    type: Literal["respond_notice"]
    notice: Ref
    text: Opt = ""
    packet_hash: str | None = None


class AdvanceClock(Cmd):
    type: Literal["advance_clock"]
    to: str

    @field_validator("to")
    @classmethod
    def iso(cls, v):
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class Undo(Cmd):
    type: Literal["undo"]
    batch: str | None = None
    event: str | None = None


BulkItem = Annotated[Verify | AcceptFinding | DismissFinding | DisposeDocument | ExplainVariance, Field(discriminator="type")]


class Bulk(Cmd):
    type: Literal["bulk"]
    items: list[BulkItem] = Field(min_length=1, max_length=1000)


class Attach(Cmd):
    """Internal: created by the upload endpoint, never accepted from the browser."""
    type: Literal["attach"]
    target: Ref
    file: dict
    name: Ref | None = None
    note: Opt = ""


Command = Annotated[Adjust | RevertAdjustment | ApproveAdjustment | AcceptFinding | DismissFinding | FindingToClient | Verify | DisposeDocument | FixHousehold | ExplainVariance | Note | Reply | ResolveNote | ReopenNote | AskClient | Answer | ReviewAnswer | Signoff | WithdrawSignoff | CompleteStep | Decide | LogTime | Assign | Standard | Seen | Reveal | SendToClient | ClientApprove | Transmit | Deliver | StartAmendment | RespondNotice | AdvanceClock | Undo | Bulk | Attach, Field(discriminator="type")]

_adapter = TypeAdapter(Command)
INTERNAL = {"attach"}


class CommandError(ValueError):
    pass


def parse(raw: dict, *, external: bool = False) -> dict:
    """Validate a command; returns a plain dict for the workpaper. Raises CommandError with a readable message."""
    if external and isinstance(raw, dict) and raw.get("type") in INTERNAL:
        raise CommandError(f"'{raw['type']}' cannot be sent directly")
    try:
        cmd = _adapter.validate_python(raw)
    except ValidationError as e:
        msgs = []
        for err in e.errors()[:5]:
            loc = ".".join(str(x) for x in err["loc"] if not str(x).startswith(("function-", "tagged-union")))
            msgs.append(f"{loc or 'command'}: {err['msg']}")
        raise CommandError("; ".join(msgs)) from None
    return cmd.model_dump(exclude_none=True)
