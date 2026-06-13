"""Small json_fix compatibility module used by TI's gui_parser.py.

TI's visualizer expects importing json_fix to add ``json.fallback_table`` and
make ``json.dumps`` consult that table for otherwise non-serializable values.
"""

import json


if not hasattr(json, "fallback_table"):
    json.fallback_table = {}

_ORIGINAL_DEFAULT = json.JSONEncoder.default


def _json_fix_default(self, obj):
    for value_type, serializer in json.fallback_table.items():
        if isinstance(obj, value_type):
            return serializer(obj)
    return _ORIGINAL_DEFAULT(self, obj)


if getattr(json.JSONEncoder.default, "__name__", "") != "_json_fix_default":
    json.JSONEncoder.default = _json_fix_default
