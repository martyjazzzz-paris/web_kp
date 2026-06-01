from __future__ import annotations

import json


def parsed_to_json(parsed: dict) -> str:
    return json.dumps(parsed, ensure_ascii=False)
