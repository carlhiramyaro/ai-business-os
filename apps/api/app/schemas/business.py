import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.models.business import DEFAULT_CURRENCY
from app.schemas.base import CamelModel


class BusinessCreate(CamelModel):
    business_name: str = Field(min_length=1)
    industry: str | None = None
    # Defaulted here, not just on the column: app/routers/business.py builds
    # the row with `Business(**payload.model_dump())`, so an omitted
    # `currency` would arrive as an explicit None and override the column's
    # own default. See the Business.currency comment.
    currency: str = DEFAULT_CURRENCY
    country: str | None = None
    timezone: str | None = None


class BusinessUpdate(CamelModel):
    business_name: str | None = Field(default=None, min_length=1)
    industry: str | None = None
    currency: str | None = None
    country: str | None = None
    timezone: str | None = None

    # On this model `None` is the "field omitted" sentinel -- the route
    # applies it with `model_dump(exclude_unset=True)`, so an omitted field
    # is never written. An EXPLICIT null in the request body is a different
    # thing: it IS "set", so it would be written, and both of these back
    # NOT NULL columns -- a 500 from the database rather than a 422 from
    # validation. Rejecting it here keeps the error where it belongs.
    # (`industry`/`country`/`timezone` are genuinely nullable, so an
    # explicit null clearing them is legitimate and stays allowed.)
    #
    # Has to be a model-level validator: only `model_fields_set`
    # distinguishes "explicitly sent as null" from "defaulted to None",
    # and a field validator cannot see it.
    _NON_NULLABLE = ("business_name", "currency")

    @model_validator(mode="after")
    def _reject_explicit_nulls(self):
        for field in self._NON_NULLABLE:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class BusinessResponse(CamelModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    business_name: str
    industry: str | None
    # Not optional since [2026-08-27] -- the column is NOT NULL with a
    # server default (see app/models/business.py).
    currency: str
    country: str | None
    timezone: str | None
    created_at: datetime
    updated_at: datetime
