"""HW7 Part 1 one-off patch: move every domain route from the HW4 session to JWT roles.

Files changed: main.py (/api/notices), routers/manufacturers.py, routers/n1_demo.py.
Rules: read -> any authenticated role; create/update -> writer or moderator;
delete -> moderator. Run once from the repo root; it refuses to run twice.
"""
import re
from pathlib import Path

READ = "get_current_user"
WRITE = 'require_roles("writer", "moderator")'
DELETE = 'require_roles("moderator")'
OLD_IMPORT = "from routers.session_auth import require_session\n"
NEW_IMPORT = {
    "routers/manufacturers.py": "from routers.jwt_auth import get_current_user, require_roles\n",
    "routers/n1_demo.py": "from routers.jwt_auth import get_current_user\n",
}

RULES = {
    "main.py": {"get_notices": READ, "get_notice_by_id": READ, "create_notice": WRITE,
                "update_notice": WRITE, "delete_notice": DELETE},
    "routers/manufacturers.py": {"create_manufacturer": WRITE, "list_manufacturers": READ,
                                 "get_manufacturer": READ, "update_manufacturer": WRITE,
                                 "delete_manufacturer": DELETE, "notices_for_manufacturer": READ},
    "routers/n1_demo.py": {"list_naive": READ, "list_fixed": READ},
}


def swap_dependencies(text: str, rules: dict, path: str) -> str:
    """Replace Depends(require_session) inside each named function with its JWT rule."""
    for func, dep in rules.items():
        pattern = rf"(def {func}\((?:.|\n)*?)_user: User = Depends\(require_session\),"
        text, count = re.subn(pattern, rf"\g<1>_user: User = Depends({dep}),", text, count=1)
        if count != 1:
            raise SystemExit(f"{path}: could not patch {func} -- nothing written")
    return text


def patch_main(text: str) -> str:
    """main.py: new imports, mount the JWT router, refresh the comment."""
    text = text.replace(
        "from routers.session_auth import router as session_auth_router, require_session\n",
        "from routers.session_auth import router as session_auth_router\n"
        "from routers.jwt_auth import router as jwt_router, get_current_user, require_roles\n", 1)
    text = text.replace(
        "app.include_router(session_auth_router)\n",
        "app.include_router(session_auth_router)\n\n"
        "# HW7 Part 1: JWT bearer auth (/auth/login, /auth/me). All domain routes now use\n"
        "# JWT roles instead of the HW4 session (the session version is kept at the hw4 tag).\n"
        "app.include_router(jwt_router)\n", 1)
    return text.replace(
        "# All endpoints depend on require_session: an anonymous request gets a 401\n"
        "# \"Login required\" before any DB query runs. HW5 adds",
        "# HW7: every endpoint needs a JWT bearer token (401 without a valid one).\n"
        "# Read: any role. Create/update: writer or moderator. Delete: moderator (else 403).\n"
        "# HW5 adds", 1)


def main() -> None:
    """Patch all three files, or none if any check fails."""
    new_texts = {}
    for path, rules in RULES.items():
        text = Path(path).read_text()
        if "require_session" not in text:
            raise SystemExit(f"{path} looks already patched -- nothing written")
        if path == "main.py":
            text = patch_main(text)
        else:
            text = text.replace(OLD_IMPORT, NEW_IMPORT[path], 1)
        text = swap_dependencies(text, rules, path)
        text = text.replace("protected by require_session", "protected by JWT (any role)")
        if "require_session" in text:
            raise SystemExit(f"{path}: require_session still referenced -- nothing written")
        new_texts[path] = text
    for path, text in new_texts.items():
        Path(path).write_text(text)
        print(f"patched {path}")


if __name__ == "__main__":
    main()
