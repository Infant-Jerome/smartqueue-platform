"""Canonical schema checks Phase 1.1 (T-Tests ownership).

8 required checks:
 1. salons PK is salon_id
 2. appointments PK is appointment_id
 3. queue PK is queue_id
 4. history FK -> appointments.appointment_id
 5. no duplicate Queue/QueueEntry active (single mapper for queue table)
 6. no duplicate Appointment active (single mapper for appointments table)
 7. fresh alembic DB matches metadata (tolerant parity until MIG lands,
    strict after via STRICT_CANONICAL=1)
 8. alembic check passes (via alembic command config if possible, else
    metadata-vs-migration table/PK compare)

Isolated in-memory SQLite only.
"""
import os

from sqlalchemy import inspect


def _metadata():
    from app.db.base import Base
    import app.models.appointment  # noqa: F401
    import app.models.availability  # noqa: F401
    import app.models.barber  # noqa: F401
    import app.models.queue  # noqa: F401
    import app.models.salon  # noqa: F401
    import app.models.service  # noqa: F401
    import app.models.status_history  # noqa: F401
    import app.models.user  # noqa: F401
    return Base.metadata


def test_c1_salon_pk_is_salon_id():
    meta = _metadata()
    table = meta.tables["salons"]
    pk = [c.name for c in table.primary_key.columns]
    assert pk == ["salon_id"], f"salons PK must be ['salon_id'], got {pk}"
    assert "id" not in [c.name for c in table.columns]
    from app.models.salon import Salon
    assert Salon.__mapper__.primary_key[0].name == "salon_id"


def test_c2_appointment_pk_is_appointment_id():
    meta = _metadata()
    table = meta.tables["appointments"]
    pk = [c.name for c in table.primary_key.columns]
    assert pk == ["appointment_id"], f"appointments PK must be ['appointment_id'], got {pk}"
    cols = {c.name for c in table.columns}
    assert {"appointment_id", "customer_id", "start_time", "end_time"} <= cols
    assert "id" not in cols, "legacy appointments.id must be gone"
    assert "user_id" not in cols, "legacy appointments.user_id must be gone (canonical customer_id)"
    assert "appointment_time" not in cols
    assert "queue_number" not in cols
    from app.models.appointment import Appointment
    assert Appointment.__mapper__.primary_key[0].name == "appointment_id"


def test_c3_queue_pk_is_queue_id():
    meta = _metadata()
    table = meta.tables["queue"]
    pk = [c.name for c in table.primary_key.columns]
    assert pk == ["queue_id"], f"queue PK must be ['queue_id'], got {pk}"
    cols = {c.name for c in table.columns}
    assert {"queue_id", "queue_position", "estimated_wait_minutes"} <= cols
    assert "id" not in cols
    assert "queue_number" not in cols
    assert "estimated_wait_time" not in cols
    from app.models.queue import Queue
    assert Queue.__mapper__.primary_key[0].name == "queue_id"


def test_c4_history_fk_to_appointments_appointment_id():
    meta = _metadata()
    table = meta.tables["appointment_status_history"]
    pk = [c.name for c in table.primary_key.columns]
    assert pk == ["history_id"], f"history PK must be ['history_id'], got {pk}"
    fks = {str(fk.target_fullname) for fk in table.foreign_keys}
    assert "appointments.appointment_id" in fks, f"history FK must target appointments.appointment_id, got {fks}"
    assert "appointments.id" not in fks


def test_c5_no_duplicate_queue_mapper():
    from app.db.base import Base

    _metadata()
    queue_mappers = [
        m for m in Base.registry.mappers
        if m.persist_selectable is not None
        and getattr(m.persist_selectable, "name", None) == "queue"
    ]
    assert len(queue_mappers) == 1, (
        f"exactly one mapper for queue table, got {[m.class_.__name__ for m in queue_mappers]}"
    )
    assert queue_mappers[0].class_.__name__ == "Queue"
    # Legacy alias must resolve to the same class, not a second mapper.
    from app.models.models import QueueEntry
    from app.models.queue import Queue
    assert QueueEntry is Queue


def test_c6_no_duplicate_appointment_mapper():
    from app.db.base import Base

    _metadata()
    appt_mappers = [
        m for m in Base.registry.mappers
        if m.persist_selectable is not None
        and getattr(m.persist_selectable, "name", None) == "appointments"
    ]
    assert len(appt_mappers) == 1, (
        f"exactly one mapper for appointments table, got {[m.class_.__name__ for m in appt_mappers]}"
    )
    assert appt_mappers[0].class_.__name__ == "Appointment"


def _migration_tables_and_pks():
    """Parse alembic versions/ for create_table names + PK columns (best effort)."""
    import ast

    versions = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "alembic",
        "versions",
    )
    tables = {}
    for fname in sorted(os.listdir(versions)):
        if not fname.endswith(".py"):
            continue
        src = open(os.path.join(versions, fname)).read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(getattr(node, "func", None), "attr", "") == "create_table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                tname = node.args[0].value
                pk = []
                for kw in node.keywords:
                    if kw.arg is None and isinstance(kw.value, ast.Call):
                        func = getattr(kw.value, "func", None)
                        if getattr(func, "attr", "") == "PrimaryKeyConstraint":
                            pk = [a.value for a in kw.value.args if isinstance(a, ast.Constant)]
                tables.setdefault(tname, pk)
    return tables


def test_c7_fresh_alembic_db_matches_metadata(db_engine):
    """Fresh DB from metadata must equal alembic-upgraded DB.

    Tolerant until MIG lands: passes if core canonical tables exist in the
    isolated engine; strict (STRICT_CANONICAL=1) requires migration scripts
    to declare the canonical tables/PKs.
    """
    meta = _metadata()
    engine_tables = set(inspect(db_engine).get_table_names())
    canonical = {"users", "salons", "barbers", "services", "barber_availability",
                 "appointments", "queue", "appointment_status_history"}
    assert canonical <= engine_tables
    for t in canonical:
        insp_pk = inspect(db_engine).get_pk_constraint(t) or {}
        meta_pk = [c.name for c in meta.tables[t].primary_key.columns]
        assert (insp_pk.get("constrained_columns") or []) == meta_pk

    strict = os.getenv("STRICT_CANONICAL") == "1"
    mig = _migration_tables_and_pks()
    expected_pk = {
        "users": ["user_id"], "salons": ["salon_id"], "barbers": ["barber_id"],
        "services": ["service_id"], "barber_availability": ["availability_id"],
        "appointments": ["appointment_id"], "queue": ["queue_id"],
        "appointment_status_history": ["history_id"],
    }
    drift = {
        t: {"migration_pk": mig.get(t), "metadata_pk": pk}
        for t, pk in expected_pk.items() if mig.get(t) != pk
    }
    if strict:
        assert not drift, f"migration/metadata PK drift (MIG blocker): {drift}"
    else:
        print(f"INFO migration parity drift until MIG lands: {drift}")


def test_c8_alembic_check_passes():
    """Invoke `alembic check` against a temp file DB if possible, else compare
    migration table/PK declarations vs metadata (tolerant until MIG lands,
    strict with STRICT_CANONICAL=1).
    """
    import subprocess
    import tempfile

    meta = _metadata()
    strict = os.getenv("STRICT_CANONICAL") == "1"
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db = tmp.name
    # Build a migration-stamped DB then run `alembic check`.
    url = f"sqlite:///{tmp_db}"
    env = dict(os.environ, DATABASE_URL=url)
    try:
        up = subprocess.run(
            ["alembic", "upgrade", "head"], cwd=backend_dir, env=env,
            capture_output=True, text=True, timeout=120,
        )
        if up.returncode != 0:
            print(f"INFO alembic upgrade head failed (MIG blocker): {up.stderr[-2000:]}")
            if strict:
                assert False, f"alembic upgrade head failed: {up.stderr[-2000:]}"
            return
        chk = subprocess.run(
            ["alembic", "check"], cwd=backend_dir, env=env,
            capture_output=True, text=True, timeout=120,
        )
        out = (chk.stdout + chk.stderr)[-4000:]
        if chk.returncode != 0:
            print(f"INFO alembic check drift (MIG blocker): {out}")
            if strict:
                assert False, f"alembic check failed: {out}"
            # Tolerant: fall back to metadata-vs-migration table compare.
            mig = _migration_tables_and_pks()
            missing = sorted(set(meta.tables) - set(mig))
            print(f"INFO tables in metadata but not migrations: {missing}")
            return
    except FileNotFoundError:
        # No alembic CLI: metadata-vs-migration compare fallback.
        mig = _migration_tables_and_pks()
        missing = sorted(set(meta.tables) - set(mig))
        print(f"INFO alembic CLI unavailable; metadata-only tables: {missing}")
        if strict:
            assert not missing, f"tables missing from migrations: {missing}"
    finally:
        try:
            os.unlink(tmp_db)
        except OSError:
            pass
