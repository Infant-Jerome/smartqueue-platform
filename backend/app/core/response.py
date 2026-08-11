from typing import Any


def ok(data: Any = None, message: str = "OK") -> dict:
    return {"success": True, "message": message, "data": data}


def err(message: str) -> dict:
    return {"success": False, "message": message, "data": None}