# Root shim so imports like "from database import engine, SessionLocal" work
from services.api.database import engine, SessionLocal
