import unicodedata

from pydantic import BaseModel, Field, field_validator


class ComparisonCreate(BaseModel):
    task_a_id: int
    task_b_id: int
    label_a: str | None = Field(default=None, max_length=100)
    label_b: str | None = Field(default=None, max_length=100)

    @field_validator('label_a', 'label_b')
    @classmethod
    def clean_label(cls, value):
        if value is None:
            return None
        return ''.join(c for c in value if not unicodedata.category(c).startswith('C')).strip() or None
