"""
HW4 Part 2: create one demo login user so the React app / Postman has an
account to log in with. Run once:

    python3 scripts/seed_demo_user.py

Prints the credentials it created (or confirms the account already exists).
Safe to re-run.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, engine, SessionLocal
from models import User
from routers.session_auth import hash_password

DEMO_NAME = "Pinal Pawar"
DEMO_EMAIL = "pinal@example.com"
DEMO_PASSWORD = "hw4-demo-pass"

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    db_session_basede26 = SessionLocal()
    try:
        existing = db_session_basede26.query(User).filter(User.email == DEMO_EMAIL).first()
        if existing:
            print(f"Demo user already exists: {DEMO_EMAIL}")
        else:
            user = User(
                name=DEMO_NAME,
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
            )
            db_session_basede26.add(user)
            db_session_basede26.commit()
            print(f"Created demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    finally:
        db_session_basede26.close()
