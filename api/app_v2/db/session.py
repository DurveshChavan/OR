"""Engine and per-request session handling.

One environment variable selects the database (spec C.1)::

    DATABASE_URL=postgresql+psycopg://user:password@host:5432/sla_desk
    DATABASE_URL=sqlite:///./data/demo/sla_desk.sqlite3

PostgreSQL is normal operation; SQLite is the offline demo and the test
default. Sessions are synchronous on purpose: this is a single-machine
deployment where an async stack would add failure modes a viva cannot inspect.

A request gets exactly one session. It commits once, after the current-state
change and its events are both written, rolls back on any error, and closes in
a ``finally`` block, so a half-written ticket with no event can never survive.
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./data/demo/sla_desk.sqlite3"

_engine = None
_session_factory = None


def database_url() -> str:
    """The configured database URL, defaulting to the offline demo SQLite file."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _apply_sqlite_pragmas(dbapi_connection, connection_record):
    """Turn on the SQLite behaviour the schema assumes.

    SQLite ignores foreign keys unless asked, which would silently weaken every
    ``ForeignKey`` in the model layer and make the fallback mode a weaker
    database than the one the tests claim to cover.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_sqlite_directory(url: str) -> None:
    """Create the folder a SQLite file lives in.

    The offline demo ships as a path under ``data/``, which is not tracked, so a
    fresh clone would otherwise fail on "unable to open database file" before
    the first migration runs.
    """
    path = url.split("sqlite:///", 1)[-1]
    if not path or path == ":memory:":
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def make_engine(url: str = None) -> Engine:
    """Build an engine for `url` with the dialect quirks already handled."""
    url = url or database_url()
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        _ensure_sqlite_directory(url)
        # check_same_thread is a SQLite-only guard that TestClient trips over;
        # the session is still used from one thread at a time.
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


def get_engine() -> Engine:
    """The process-wide engine, created on first use."""
    global _engine, _session_factory
    if _engine is None:
        _engine = make_engine()
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def set_engine(engine: Engine) -> None:
    """Point this process at `engine`. Used by tests and the CLI commands."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def session_scope() -> Session:
    """A new session bound to the current engine. The caller owns its lifecycle."""
    get_engine()
    return _session_factory()


def get_db():
    """FastAPI dependency: one session per request, committed once or rolled back."""
    db = session_scope()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
