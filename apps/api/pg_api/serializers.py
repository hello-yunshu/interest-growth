from __future__ import annotations

from sqlalchemy.inspection import inspect


def model_dict(obj):
    return {attr.key: getattr(obj, attr.key) for attr in inspect(obj).mapper.column_attrs}
