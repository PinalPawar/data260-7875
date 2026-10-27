"""HW8 Part 1: the worker's business logic, with no Kafka in it (so it can be tested offline).

Notices live in a plain Python dict inside the worker, as the assignment asks. Field validation
reuses the existing `NoticeCreate` schema from schemas.py (HW5), so a notice sent over Kafka has
to meet the same rules as one sent to the REST API:

    product         non-empty string (max 255)
    notice_code     RCL-YYYY-NNNNN, e.g. RCL-2026-00001
    units_affected  integer >= 0
    manufacturer_id integer > 0
    email           valid e-mail address
    description     non-empty string
    category        supplyShortage | bacterialContamination | foreignMaterial | mislabelling
"""

import uuid

from pydantic import ValidationError

from schemas import NoticeCreate

from .config import ID_FIELD, OP_CREATE, OP_GET

REQUIRED_FIELDS = list(NoticeCreate.model_fields)  # all seven, units_affected included


def validate_notice(data) -> tuple[dict | None, str | None]:
    """Return (clean_fields, None) or (None, error message)."""
    if not isinstance(data, dict):
        return None, "data must be a JSON object"
    missing = [f for f in REQUIRED_FIELDS if f not in data or data[f] is None]
    if missing:
        return None, f"Missing required field(s): {', '.join(missing)}"
    empty = [f for f in REQUIRED_FIELDS if isinstance(data[f], str) and not data[f].strip()]
    if empty:
        return None, f"Empty value for field(s): {', '.join(empty)}"
    unknown = sorted(set(data) - set(REQUIRED_FIELDS))
    if unknown:
        return None, f"Unknown field(s): {', '.join(unknown)}"
    try:
        # strict: "5" is not accepted as a number and true is not accepted as 1
        notice = NoticeCreate.model_validate(data, strict=True)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]) or "data"
            problems.append(f"{field}: {err['msg']}")
        return None, "Invalid value(s): " + "; ".join(problems)
    return notice.model_dump(), None


class NoticeService:
    """In-memory notice store plus the CREATE/GET request handler."""

    def __init__(self, idempotent: bool = True):
        self.notices: dict[str, dict] = {}
        self.idempotent = idempotent
        self.seen: dict[str, dict] = {}  # correlation_id -> response already sent

    def handle(self, request: dict) -> tuple[dict, bool]:
        """Process one request envelope. Returns (response, was_duplicate).

        The response always echoes the request's correlation_id unchanged, success or not.
        """
        corr = request.get("correlation_id") if isinstance(request, dict) else None
        if self.idempotent and corr and corr in self.seen:
            return self.seen[corr], True

        result = self._process(request)
        response = {"correlation_id": corr, "operation": _op(request), **result}
        if self.idempotent and corr and response["success"]:
            self.seen[corr] = response
        return response, False

    def _process(self, request) -> dict:
        if not isinstance(request, dict):
            return {"success": False, "error": "Request must be a JSON object"}
        envelope = ("correlation_id", "reply_to", "operation", "data")
        missing = [k for k in envelope if k not in request]
        if missing:
            return {"success": False, "error": f"Malformed request, missing: {', '.join(missing)}"}
        op = request["operation"]
        data = request["data"]
        if op == OP_CREATE:
            clean, error = validate_notice(data)
            if error:
                return {"success": False, "error": error}
            notice_id = str(uuid.uuid4())
            self.notices[notice_id] = {ID_FIELD: notice_id, **clean}
            return {"success": True, ID_FIELD: notice_id, "message": "Notice created"}
        if op == OP_GET:
            notice_id = data.get(ID_FIELD) if isinstance(data, dict) else None
            if not isinstance(notice_id, str) or not notice_id.strip():
                return {"success": False, "error": f"{ID_FIELD} is required"}
            if notice_id not in self.notices:
                return {"success": False, "error": "Notice not found"}
            return {"success": True, "notice": self.notices[notice_id]}
        return {"success": False, "error": "Unknown operation"}


def _op(request):
    return request.get("operation") if isinstance(request, dict) else None
