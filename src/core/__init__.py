"""Validated Query Plan workflow."""

from .schema import Filter, QueryPlan

def parse_query_plan(*args, **kwargs):
    from .query_plan import parse_query_plan as _parse_query_plan

    return _parse_query_plan(*args, **kwargs)

def process_question(*args, **kwargs):
    from .fallback import process_question as _process_question

    return _process_question(*args, **kwargs)

__all__ = ["Filter", "QueryPlan", "parse_query_plan", "process_question"]
