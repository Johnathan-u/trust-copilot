"""Shared Pydantic request schemas used by multiple route modules."""

from pydantic import BaseModel


class MetadataUpdateBody(BaseModel):
    frameworks: list[str] = []
    subject_areas: list[str] = []


class BulkDeleteBody(BaseModel):
    ids: list[int] = []
