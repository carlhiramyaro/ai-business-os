from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for API-facing schemas: snake_case attributes in Python,
    camelCase in JSON (matches erd.md/endpoints.md's documented API shape,
    while ORM models stay snake_case — see decisions.md [2026-07-17])."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
