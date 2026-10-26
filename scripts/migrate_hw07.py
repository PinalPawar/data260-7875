"""HW7 Part 1: add username + role to the MySQL users table and seed three users.

Safe to run more than once: columns are only added if missing, and the three
demo users are created or updated (passwords re-hashed with bcrypt).
Passwords come from .env (HW7_*_PASSWORD) -- never hardcoded here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from database import SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from routers.session_auth import hash_password  # noqa: E402

load_dotenv()

DEMO_USERS = [
    ("reader1", "reader", "HW7_READER_PASSWORD"),
    ("writer1", "writer", "HW7_WRITER_PASSWORD"),
    ("mod1", "moderator", "HW7_MODERATOR_PASSWORD"),
]


def add_columns() -> None:
    """Add users.username (unique) and users.role if they are not there yet."""
    existing = {col["name"] for col in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "username" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(64) NULL UNIQUE"))
            print("added column users.username")
        if "role" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'reader' "
                "CHECK (role IN ('reader', 'writer', 'moderator'))"
            ))
            print("added column users.role")
        # Older HW4 users get a username so every row can log in by username.
        conn.execute(text("UPDATE users SET username = CONCAT('user', id) WHERE username IS NULL"))


def seed_users() -> None:
    """Create or update reader1 / writer1 / mod1 with bcrypt-hashed passwords."""
    db_session_basede26 = SessionLocal()
    try:
        for username, role, env_var in DEMO_USERS:
            password = os.getenv(env_var)
            if not password:
                sys.exit(f"Set {env_var} in .env first")
            user = db_session_basede26.query(User).filter(User.username == username).first()
            if user is None:
                user = User(name=username, email=f"{username}@s7875.local", username=username)
                db_session_basede26.add(user)
            user.role = role
            user.password_hash = hash_password(password)
            print(f"{username}: role={role} (password stored as bcrypt hash)")
        db_session_basede26.commit()
    finally:
        db_session_basede26.close()


if __name__ == "__main__":
    add_columns()
    seed_users()
    print("migration complete")
