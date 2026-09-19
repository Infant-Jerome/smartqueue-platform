"""SmartQueue Phase 4 queue engine (Q1-Engine).

DECISIONS (canonical, documented here per Phase 4 brief):
1. Numbering: keep per-day GLOBAL numbering (existing design: queue_position
   is 1-based, ``max(position)+1`` for the same ``appointment_date``).
   Operational queries additionally scope by ``barber_id`` when provided
   (and by ``salon_id`` when provided). Rationale: avoids a data migration
   and keeps existing positions stable; per-barber ordering is achieved by
   filtering, not by renumbering.
2. No renumbering of history: positions are never reused. New joins use
   ``max(queue_position)+1`` over the same date (and same barber when
   ``barber_id`` is known), else 1. ``count()`` is never used, so
   cancelled/no_show/completed rows keep their numbers and gaps persist.
3. Status model: Queue stores ``waiting | serving | completed | cancelled |
   no_show`` (``serving`` is the queue-side alias of appointment
   ``in_progress``; ``in_progress`` is accepted on input and normalized to
   ``serving`` for storage to preserve route/test compatibility).
   Appointment stores ``booked|confirmed|waiting|in_progress|completed|
   cancelled|no_show``. Every queue transition mirrors onto the appointment
   (serving<->in_progress) so both rows stay consistent.
4. Allowed transitions (queue view):
     waiting -> serving/in_progress (serve)
     serving/in_progress -> completed (complete)
     waiting -> no_show (skip)
     waiting/serving -> cancelled (cancel sync)
   Rejected: waiting->completed directly (400), serving->no_show (400),
   unknown statuses (400), and any transition OUT of a terminal state
   (completed/cancelled/no_show -> anything, incl. completed->no_show)
   with 409. Terminal-source violations are 409 (conflict: already final);
   other illegal edges are 400 (bad request).
5. Atomicity: every transition updates Queue + Appointment, inserts one
   ``AppointmentStatusHistory(old_status, new_status)`` (appointment-level
   statuses), stamps ``updated_at`` on both rows, recomputes estimates for
   the affected (date, barber) scope, then commits once. Any failure rolls
   back fully (no partials).
6. serve_next: next ``waiting`` ordered by ``queue_position ASC`` for that
   ``barber_id`` + date (default ``date.today()``; optional explicit date
   and salon filter). Enforces single active ``serving`` per (date, barber):
   409 if one already exists. No waiting row => 404 (documented choice).
7. Wait estimate: for each ``waiting`` entry E on (date D, barber B):
     estimate(E) = sum(Service.duration_minutes of waiting entries on
     (D,B) with position < E.position) + remaining(serving on (D,B)).
   ``remaining`` approximation = full ``Service.duration_minutes`` of the
   in-progress entry (no elapsed-time tracking, no ML, no WebSocket --
   documented approximation). Durations come from the DB ``services`` table
   only; missing service/duration falls back to 0 (never a hardcoded
   average). ``serving`` rows store their own service duration as their
   estimate. Recomputed for all active rows in the affected (D,B) scope on
   every join/serve/complete/skip/cancel.
8. Concurrency: each mutating path runs in a single transaction with
   deterministic ``ORDER BY queue_position ASC`` and attempts a row-level
   lock via ``SELECT ... FOR UPDATE`` (``with_for_update()``). SQLite
   ignores/does not support ``FOR UPDATE``, so the lock is attempted only
   when the dialect supports it with a try/except fallback to a plain
   ordered SELECT. Safety on SQLite comes from the single-writer lock +
   transactional rollback; on Postgres/MySQL the ``FOR UPDATE`` path gives
   real row-level exclusion. The ``Queue.appointment_id`` UNIQUE 1:1
   constraint is the final guard against double-joins.

No ML, no WebSocket, no frontend. Python/FastAPI + SQLAlchemy only.
"""

from datetime import date, datetime
import math

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatusHistory, Queue, Service, User

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

QUEUE_ACTIVE = ("waiting", "serving")
QUEUE_TERMINAL = ("completed", "cancelled", "no_show")
# Appointment-side mirror of QUEUE_ACTIVE ("serving" <-> "in_progress").
APPT_ACTIVE_FOR_QUEUE = ("waiting", "serving", "in_progress")

# Queue-level allowed edges (after normalizing in_progress -> serving).
_QUEUE_EDGES: dict[str, tuple[str, ...]] = {
    "waiting": ("serving", "no_show", "cancelled"),
    "serving": ("completed", "cancelled"),
    "completed": (),
    "cancelled": (),
    "no_show": (),
}

# Queue status -> appointment status mirror.
_QUEUE_TO_APPT = {
    "waiting": "waiting",
    "serving": "in_progress",
    "completed": "completed",
    "cancelled": "cancelled",
    "no_show": "no_show",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_queue_status(value: str) -> str:
    """Normalize caller-supplied queue status; ``in_progress`` is an accepted
    alias for the stored ``serving`` value."""
    v = (value or "").strip().lower()
    if v == "in_progress":
        return "serving"
    return v


def _get_entry(db: Session, entry_id: int) -> Queue:
    entry = db.query(Queue).filter(Queue.queue_id == entry_id).first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found",
        )
    return entry


def _get_appointment_for_entry(db: Session, entry: Queue) -> Appointment:
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == entry.appointment_id)
        .first()
    )
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment for queue entry not found",
        )
    return appt


def _try_for_update(query):
    """Attempt SELECT ... FOR UPDATE; fall back to plain query on SQLite or
    any dialect that does not support it. Never raises for locking alone."""
    try:
        dialect = None
        try:
            bind = query.session.bind if hasattr(query, "session") else None
            if bind is not None:
                dialect = getattr(bind, "dialect", None)
                dialect = getattr(dialect, "name", None)
        except Exception:
            dialect = None
        if dialect == "sqlite":
            return query
        return query.with_for_update()
    except Exception:
        return query


def _active_serving_for_barber_date(
    db: Session, barber_id: int, appt_date: date, exclude_queue_id: int | None = None
):
    """Return the single active serving row for (date, barber), if any."""
    q = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
            Queue.status == "serving",
        )
        .order_by(Queue.queue_position.asc())
    )
    if exclude_queue_id is not None:
        q = q.filter(Queue.queue_id != exclude_queue_id)
    try:
        rows = _try_for_update(q).all()
    except Exception:
        rows = q.all()
    return rows[0] if rows else None


def _validate_queue_edge(current: str, target: str) -> None:
    cur = _normalize_queue_status(current)
    tgt = _normalize_queue_status(target)
    if tgt not in ("waiting", "serving", "completed", "cancelled", "no_show"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid queue status '{target}'",
        )
    if tgt == cur:
        if cur in QUEUE_TERMINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Queue entry is already '{cur}'",
            )
        return
    if cur in QUEUE_TERMINAL:
        # Terminal -> anything (incl. completed->no_show) is a conflict.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Queue entry is already '{cur}' and cannot transition to '{tgt}'",
        )
    allowed = _QUEUE_EDGES.get(cur, ())
    if tgt not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition queue entry from '{cur}' to '{tgt}'",
        )


def _service_durations(db: Session) -> dict[int, int]:
    """Service_id -> duration_minutes from the DB only (missing => 0)."""
    rows = db.query(Service.service_id, Service.duration_minutes).all()
    out: dict[int, int] = {}
    for sid, dur in rows:
        try:
            out[int(sid)] = int(dur) if dur else 0
        except (TypeError, ValueError):
            out[int(sid)] = 0
    return out


# ---------------------------------------------------------------------------
# SAWTE integration (Phase 5C, S2-Integrate)
# ---------------------------------------------------------------------------
# Contract from S1: ``app.services.sawte`` exposes ``estimate_wait``,
# ``expected_duration`` and ``compute_actual_minutes``; ``Appointment`` gains
# a nullable ``actual_duration_minutes`` column (model definition owned by
# another stream -- never defined here, only written defensively).
#
# The sawte module may not have landed yet, so EVERY use below lazy-imports
# ("retry import until landed") and falls back to the Phase 4 static math
# with confidence "low". Fallback wait values are identical to the old math,
# so existing engine tests pass with or without S1. Call conventions are
# signature-adaptive (only matching kwargs are passed; **kwargs functions
# get the full context) and return values are normalized, so S2 works with
# whatever reasonable S1 signature lands. Nothing here changes lifecycle,
# RBAC, position or recalc-trigger rules.

_FALLBACK_CONFIDENCE = "low"


def _load_sawte():
    """Import the S1 SAWTE module on every call (retry-until-landed).

    Returns the module, or None when it has not landed yet / is broken.
    Never raises."""
    try:
        from app.services import sawte as _mod
        return _mod
    except Exception:
        return None


def _adaptive_call(fn, ctx: dict):
    """Call ``fn`` with the subset of ``ctx`` its signature accepts.

    Functions taking ``**kwargs`` receive the full context. Returns None on
    any failure (caller applies its static fallback). Never raises."""
    try:
        import inspect as _inspect

        try:
            sig = _inspect.signature(fn)
        except (TypeError, ValueError):
            return None
        params = sig.parameters
        if any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return fn(**ctx)
        kwargs = {k: v for k, v in ctx.items() if k in params}
        return fn(**kwargs)
    except Exception:
        return None


def _normalize_estimate(result, fallback_wait: int):
    """Normalize SAWTE ``estimate_wait`` output to ``(wait:int, confidence)``.

    Accepts an int/float, a ``(wait, confidence)`` tuple/list, or a dict.
    Confidence is forwarded verbatim (whatever type S1 uses). Never raises.
    """
    try:
        if result is None:
            return int(fallback_wait or 0), _FALLBACK_CONFIDENCE
        if isinstance(result, dict):
            wait = fallback_wait
            for key in (
                "estimated_wait_minutes",
                "wait_minutes",
                "estimate_minutes",
                "estimate",
                "minutes",
                "wait",
            ):
                if result.get(key) is not None:
                    try:
                        wait = int(result[key])
                        break
                    except (TypeError, ValueError):
                        continue
            conf = result.get(
                "confidence",
                result.get("confidence_level", _FALLBACK_CONFIDENCE),
            )
            return max(0, int(wait or 0)), conf
        if isinstance(result, (tuple, list)):
            if len(result) == 0:
                return int(fallback_wait or 0), _FALLBACK_CONFIDENCE
            if len(result) == 1:
                try:
                    return max(0, int(result[0] or 0)), _FALLBACK_CONFIDENCE
                except (TypeError, ValueError):
                    return int(fallback_wait or 0), _FALLBACK_CONFIDENCE
            try:
                return max(0, int(result[0] or 0)), result[1]
            except (TypeError, ValueError):
                return int(fallback_wait or 0), result[1]
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            return max(0, int(result)), _FALLBACK_CONFIDENCE
    except Exception:
        pass
    try:
        return int(fallback_wait or 0), _FALLBACK_CONFIDENCE
    except Exception:
        return 0, _FALLBACK_CONFIDENCE


def _expected_minutes(
    db: Session,
    service_id: int,
    durations: dict | None = None,
    barber_id: int | None = None,
) -> int:
    """SAWTE-aware per-service duration: ``expected_duration`` when landed,
    else the DB services-table value (missing => 0). Matches the S1 ceil
    convention for fractional averages. Never raises."""
    try:
        if durations is not None:
            fallback = int(durations.get(service_id, 0) or 0)
        else:
            fallback = int(_service_durations(db).get(service_id, 0) or 0)
    except Exception:
        fallback = 0
    mod = _load_sawte()
    if mod is None:
        return fallback
    fn = getattr(mod, "expected_duration", None)
    if not callable(fn):
        return fallback
    ctx = {
        # S1 canonical names first (db, barber_id, service_id); extras are
        # only passed when the landed signature accepts them.
        "db": db,
        "session": db,
        "barber_id": barber_id,
        "service_id": service_id,
        "durations": durations,
        "fallback_minutes": fallback,
        "static_minutes": fallback,
    }
    try:
        result = _adaptive_call(fn, ctx)
        if isinstance(result, dict):
            for key in (
                "expected_minutes",
                "expected_duration",
                "minutes",
                "duration_minutes",
                "duration",
            ):
                if result.get(key) is not None:
                    try:
                        return max(0, int(math.ceil(float(result[key]))))
                    except (TypeError, ValueError):
                        continue
            return fallback
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            return max(0, int(math.ceil(float(result))))
    except Exception:
        pass
    return fallback


def _compute_actual_minutes(start, end) -> int:
    """SAWTE ``compute_actual_minutes`` when landed, else the S1-convention
    fallback ``max(1, ceil(minutes))`` (0 only when a stamp is missing).
    Never raises."""
    mod = _load_sawte()
    if mod is not None:
        fn = getattr(mod, "compute_actual_minutes", None)
        if callable(fn):
            ctx = {
                # S1 canonical names first; extras only on **kwargs signatures.
                "serving_start_changed_at": start,
                "completed_at": end,
                "start": start,
                "end": end,
                "start_time": start,
                "end_time": end,
                "serving_start": start,
                "now": end,
            }
            try:
                result = _adaptive_call(fn, ctx)
                if isinstance(result, dict):
                    for key in (
                        "actual_minutes",
                        "actual_duration_minutes",
                        "minutes",
                        "duration_minutes",
                    ):
                        if result.get(key) is not None:
                            try:
                                return max(0, int(result[key]))
                            except (TypeError, ValueError):
                                continue
                elif isinstance(result, (int, float)) and not isinstance(
                    result, bool
                ):
                    return max(0, int(result))
            except Exception:
                pass
    try:
        if start is None or end is None:
            return 0
        try:
            return max(1, int(math.ceil((end - start).total_seconds() / 60.0)))
        except Exception:
            return 0
    except Exception:
        return 0


def _serving_start_for(db: Session, appointment_id: int, fallback):
    """Latest history ``changed_at`` with ``new_status == 'in_progress'`` for
    the appointment (i.e. when serving began); ``fallback`` (Queue.joined_at)
    when no such row exists. Never raises."""
    try:
        hist = (
            db.query(AppointmentStatusHistory)
            .filter(
                AppointmentStatusHistory.appointment_id == appointment_id,
                AppointmentStatusHistory.new_status == "in_progress",
            )
            .order_by(
                AppointmentStatusHistory.changed_at.desc(),
                AppointmentStatusHistory.history_id.desc(),
            )
            .first()
        )
        if hist is not None and getattr(hist, "changed_at", None) is not None:
            return hist.changed_at
    except Exception:
        pass
    return fallback


def _active_rows_for_scope(db: Session, appt_date: date, barber_id: int):
    return (
        db.query(Queue, Appointment)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
            Queue.status.in_(["waiting", "serving"]),
        )
        .order_by(Queue.queue_position.asc())
        .all()
    )


def recompute_estimates_for_scope(db: Session, appt_date: date, barber_id: int) -> None:
    """Recompute ``estimated_wait_minutes`` for active rows in (date, barber).

    Phase 5C: each waiting entry uses per-requester SAWTE ``estimate_wait``
    (same scoping as Phase 4: waiting rows with lower position + serving
    remainder); serving rows store their own SAWTE-aware duration. The
    stored column stays an int as before; confidence is transient (see
    ``estimate_for_entry``) and never persisted. Flushes (no commit);
    caller owns the transaction.
    """
    rows = _active_rows_for_scope(db, appt_date, barber_id)
    if not rows:
        return
    try:
        durations = _service_durations(db)
    except Exception:
        durations = {}
    for queue_row, appt in rows:
        try:
            if queue_row.status == "serving":
                queue_row.estimated_wait_minutes = _expected_minutes(
                    db, appt.service_id, durations, barber_id
                )
            else:
                wait, _conf = estimate_for_entry(db, queue_row, appt, durations)
                queue_row.estimated_wait_minutes = int(wait)
        except Exception:
            continue
    db.flush()


def estimate_for_entry(
    db: Session,
    entry: Queue,
    appointment: Appointment | None = None,
    durations: dict | None = None,
) -> tuple:
    """SAWTE per-requester estimate for one queue entry.

    Returns ``(estimated_wait_minutes:int, confidence)`` with the same
    scoping as Phase 4 (same date + same barber, waiting rows with a lower
    position, plus the serving remainder). ``estimate_wait`` is used when the
    S1 module has landed; otherwise the Phase 4 static math is returned with
    confidence ``"low"`` (bit-identical waits). Confidence is forwarded
    verbatim from SAWTE and never persisted. Never raises.
    """
    try:
        if appointment is None:
            try:
                appointment = (
                    db.query(Appointment)
                    .filter(Appointment.appointment_id == entry.appointment_id)
                    .first()
                )
            except Exception:
                appointment = None
        if appointment is None:
            try:
                return int(entry.estimated_wait_minutes or 0), _FALLBACK_CONFIDENCE
            except Exception:
                return 0, _FALLBACK_CONFIDENCE
        appt_date = appointment.appointment_date
        barber_id = entry.barber_id
        if durations is None:
            try:
                durations = _service_durations(db)
            except Exception:
                durations = {}
        ahead_rows = (
            db.query(Queue, Appointment)
            .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
            .filter(
                Queue.status == "waiting",
                Queue.queue_position < entry.queue_position,
                Appointment.appointment_date == appt_date,
                Queue.barber_id == barber_id,
            )
            .order_by(Queue.queue_position.asc())
            .all()
        )
        wait_ahead = 0
        for _, ahead_appt in ahead_rows:
            try:
                wait_ahead += _expected_minutes(
                    db, ahead_appt.service_id, durations, barber_id
                )
            except Exception:
                continue
        serving_remainder = 0
        try:
            serving = (
                db.query(Queue)
                .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
                .filter(
                    Queue.status == "serving",
                    Appointment.appointment_date == appt_date,
                    Queue.barber_id == barber_id,
                )
                .order_by(Queue.queue_position.asc())
                .first()
            )
            if serving is not None:
                serving_appt = (
                    db.query(Appointment)
                    .filter(Appointment.appointment_id == serving.appointment_id)
                    .first()
                )
                if serving_appt is not None:
                    serving_remainder = _expected_minutes(
                        db, serving_appt.service_id, durations, barber_id
                    )
        except Exception:
            serving_remainder = serving_remainder or 0
        if _normalize_queue_status(entry.status) == "serving":
            static_wait = int(serving_remainder or 0)
        else:
            static_wait = int((wait_ahead or 0) + (serving_remainder or 0))
        mod = _load_sawte()
        if mod is None:
            return static_wait, _FALLBACK_CONFIDENCE
        fn = getattr(mod, "estimate_wait", None)
        if not callable(fn):
            return static_wait, _FALLBACK_CONFIDENCE
        ctx = {
            # S1 canonical names first (db, barber_id, appt_date,
            # requester_position); extras only on **kwargs signatures.
            "db": db,
            "session": db,
            "barber_id": barber_id,
            "appointment_date": appt_date,
            "appt_date": appt_date,
            "date": appt_date,
            "requester_position": entry.queue_position,
            "queue_position": entry.queue_position,
            "position": entry.queue_position,
            "service_id": appointment.service_id,
            "appointment": appointment,
            "entry": entry,
            "queue_entry": entry,
            "waiting_ahead_minutes": wait_ahead,
            "wait_ahead": wait_ahead,
            "ahead_minutes": wait_ahead,
            "ahead_count": len(ahead_rows),
            "people_ahead": len(ahead_rows),
            "serving_remainder": serving_remainder,
            "serving_minutes": serving_remainder,
            "static_estimate": static_wait,
            "fallback_minutes": static_wait,
            "durations": durations,
        }
        return _normalize_estimate(_adaptive_call(fn, ctx), static_wait)
    except Exception:
        try:
            return int(entry.estimated_wait_minutes or 0), _FALLBACK_CONFIDENCE
        except Exception:
            return 0, _FALLBACK_CONFIDENCE


def get_confidence_for_entry(
    db: Session, entry: Queue, appointment: Appointment | None = None
):
    """Transient SAWTE confidence for one queue entry (verbatim, never
    persisted). ``"low"`` fallback when SAWTE has not landed. Never raises."""
    try:
        _, conf = estimate_for_entry(db, entry, appointment)
        return conf
    except Exception:
        return _FALLBACK_CONFIDENCE


def _post_commit_emit(
    entry: Queue,
    appointment: Appointment,
    target_q: str,
    db: Session | None = None,
) -> None:
    """WS2-Events hook: publish AFTER db.commit succeeded (never before).

    Maps the stored queue status to its event; wait values are forwarded
    verbatim from the committed row (no independent calc), and the transient
    SAWTE confidence is attached verbatim when computable. Never raises:
    publish errors are logged only so REST is never broken.
    """
    try:
        from app.services import queue_events as _qe

        confidence = None
        if db is not None:
            try:
                _, confidence = estimate_for_entry(db, entry, appointment)
            except Exception:
                confidence = None
        _qe.publish_for_queue_status(
            target_q, entry, appointment, confidence=confidence
        )
    except Exception:
        pass  # queue_events logs internally; never break REST


def _commit_transition(
    db: Session,
    entry: Queue,
    appointment: Appointment,
    new_queue_status: str,
) -> Queue:
    """Apply Queue+Appointment+history+estimates atomically; commit once.

    ``new_queue_status`` may be the ``in_progress`` alias (normalized).
    History records appointment-level statuses (serving -> in_progress).
    Rolls back fully on any failure (no partials).
    """
    target_q = _normalize_queue_status(new_queue_status)
    _validate_queue_edge(entry.status, target_q)

    # Single-active guard when entering serving.
    if target_q == "serving":
        clash = _active_serving_for_barber_date(
            db, entry.barber_id, appointment.appointment_date,
            exclude_queue_id=entry.queue_id,
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another customer is already being served for this barber",
            )

    old_appt_status = appointment.status
    new_appt_status = _QUEUE_TO_APPT[target_q]
    now = _utcnow()
    try:
        entry.status = target_q
        entry.updated_at = now
        appointment.status = new_appt_status
        appointment.updated_at = now
        db.add(
            AppointmentStatusHistory(
                appointment_id=appointment.appointment_id,
                old_status=old_appt_status,
                new_status=new_appt_status,
            )
        )
        if target_q == "completed":
            # Phase 5C (S2-Integrate): serving -> completed records the
            # actual service duration in the SAME transaction (part of this
            # commit, never a separate one). Serving start = latest history
            # changed_at with new_status == 'in_progress', falling back to
            # Queue.joined_at. The column is model-owned by another stream;
            # the guarded setattr is a no-op until it lands and never breaks
            # the commit.
            try:
                _start = _serving_start_for(
                    db, appointment.appointment_id, entry.joined_at
                )
                appointment.actual_duration_minutes = _compute_actual_minutes(
                    _start, now
                )
            except Exception:
                pass
        db.flush()
        recompute_estimates_for_scope(db, appointment.appointment_date, entry.barber_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Queue transition conflicts with an existing row",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Queue transition failed",
        ) from exc
    db.refresh(entry)
    _post_commit_emit(entry, appointment, target_q, db=db)  # WS2: post-commit only
    return entry


# ---------------------------------------------------------------------------
# Read API (route-compatible)
# ---------------------------------------------------------------------------

def list_active_entries(
    db: Session,
    barber_id: int | None = None,
    salon_id: int | None = None,
    appointment_date: "date | str | None" = None,
):
    """List active queue rows (waiting + serving), ordered by position.

    Optional scope filters ``(appointment_date, barber_id, salon_id)`` keep
    the per-day global numbering while scoping operational views. Called
    with no filters by the current route (backwards compatible).
    """
    q = (
        db.query(Queue)
        .filter(Queue.status.in_(list(QUEUE_ACTIVE)))
        .order_by(Queue.queue_position.asc())
    )
    if barber_id is not None:
        q = q.filter(Queue.barber_id == barber_id)
    if salon_id is not None:
        q = q.filter(Queue.salon_id == salon_id)
    if appointment_date is not None:
        q = (
            q.join(Appointment, Queue.appointment_id == Appointment.appointment_id)
            .filter(Appointment.appointment_date == appointment_date)
            .order_by(Queue.queue_position.asc())
        )
    return q.all()


def get_my_position(db: Session, user: User) -> dict:
    """Customer view: position, people ahead (same date + same barber,
    waiting with smaller position), SAWTE wait estimate + confidence, and
    the currently-serving position for that (date, barber) scope."""
    my_appointment = (
        db.query(Appointment)
        .filter(
            Appointment.customer_id == user.user_id,
            Appointment.status.in_(
                ["booked", "confirmed", "waiting", "serving", "in_progress"]
            ),
        )
        .order_by(Appointment.created_at.desc())
        .first()
    )
    if not my_appointment:
        return {"has_queue": False, "message": "No active appointment"}

    queue_entry = (
        db.query(Queue)
        .filter(Queue.appointment_id == my_appointment.appointment_id)
        .first()
    )
    if not queue_entry:
        return {"has_queue": False, "message": "No queue entry found"}

    appt_date = my_appointment.appointment_date
    barber_id = my_appointment.barber_id
    try:
        durations = _service_durations(db)
    except Exception:
        durations = {}

    ahead_rows = (
        db.query(Queue, Appointment)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Queue.status == "waiting",
            Queue.queue_position < queue_entry.queue_position,
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
        )
        .order_by(Queue.queue_position.asc())
        .all()
    )
    people_ahead = len(ahead_rows)

    currently_serving = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Queue.status == "serving",
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
        )
        .order_by(Queue.queue_position.asc())
        .first()
    )

    # Phase 5C: per-requester SAWTE estimate (same scoping as above);
    # confidence returned alongside, verbatim. Stored column untouched here.
    estimated_wait, confidence = estimate_for_entry(
        db, queue_entry, my_appointment, durations
    )

    return {
        "has_queue": True,
        "queue_position": queue_entry.queue_position,
        "status": queue_entry.status,
        "people_ahead": people_ahead,
        "estimated_wait_minutes": int(estimated_wait),
        "currently_serving": currently_serving.queue_position if currently_serving else None,
        "appointment_status": my_appointment.status,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Join (new join = max(position)+1; never reuse; never renumber)
# ---------------------------------------------------------------------------

def _next_position_for_scope(
    db: Session, appt_date: date, barber_id: int | None
) -> int:
    q = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(Appointment.appointment_date == appt_date)
    )
    if barber_id is not None:
        q = q.filter(Queue.barber_id == barber_id)
    last = q.order_by(Queue.queue_position.desc()).first()
    return (last.queue_position + 1) if last else 1


def join_queue_entry(db: Session, appointment_id: int) -> Queue:
    """Append a queue row for an appointment: position = max+1 for the same
    date (and same barber), else 1. History rows are never renumbered and
    freed positions are never reused. Enforces the 1:1 unique guard."""
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    existing = (
        db.query(Queue).filter(Queue.appointment_id == appointment_id).first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment already has a queue entry",
        )
    durations = _service_durations(db)
    try:
        entry = Queue(
            appointment_id=appointment.appointment_id,
            salon_id=appointment.salon_id,
            barber_id=appointment.barber_id,
            queue_position=_next_position_for_scope(
                db, appointment.appointment_date, appointment.barber_id
            ),
            estimated_wait_minutes=durations.get(appointment.service_id, 0),
            status="waiting",
        )
        db.add(entry)
        db.flush()
        recompute_estimates_for_scope(
            db, appointment.appointment_date, appointment.barber_id
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment already has a queue entry",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Queue join failed",
        ) from exc
    db.refresh(entry)
    try:  # WS2: creation emit post-commit only (publish errors never break REST)
        from app.services import queue_events as _qe

        try:
            _, _create_conf = estimate_for_entry(db, entry, appointment)
        except Exception:
            _create_conf = None
        _qe.publish_creation(entry, appointment, confidence=_create_conf)
    except Exception:
        pass
    return entry


# ---------------------------------------------------------------------------
# Transitions (route-compatible names)
# ---------------------------------------------------------------------------

def _sync_appointment_status(db: Session, entry: Queue, entry_status: str) -> None:
    """Legacy helper kept for compatibility; maps queue -> appointment."""
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == entry.appointment_id)
        .first()
    )
    if appointment:
        appointment.status = _QUEUE_TO_APPT.get(
            _normalize_queue_status(entry_status), entry_status
        )


def update_queue_entry(db: Session, entry_id: int, entry_status: str) -> Queue:
    """Generic guarded transition (PUT). Validates edges, mirrors to the
    appointment, writes history, stamps updated_at, recomputes estimates."""
    entry = _get_entry(db, entry_id)
    appointment = _get_appointment_for_entry(db, entry)
    return _commit_transition(db, entry, appointment, entry_status)


def update(entry_id: int, entry_status: str, db: Session) -> Queue:
    """Alias kept for the spec's ``update`` name (routes use
    ``update_queue_entry``)."""
    return update_queue_entry(db, entry_id, entry_status)


def serve_customer(db: Session, entry_id: int) -> Queue:
    """waiting -> serving (appointment -> in_progress). 400 when not waiting;
    409 when another serving row is active for the same (date, barber) or the
    entry is terminal."""
    entry = _get_entry(db, entry_id)
    if _normalize_queue_status(entry.status) != "waiting":
        if entry.status in QUEUE_TERMINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Queue entry is already '{entry.status}'",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Entry is not in waiting status",
        )
    appointment = _get_appointment_for_entry(db, entry)
    return _commit_transition(db, entry, appointment, "serving")


def serve(db: Session, entry_id: int) -> Queue:
    """Alias kept for the spec's ``serve`` name."""
    return serve_customer(db, entry_id)


def complete_customer(db: Session, entry_id: int) -> Queue:
    """serving -> completed. waiting->completed directly is rejected (400);
    terminal sources are rejected (409)."""
    entry = _get_entry(db, entry_id)
    if _normalize_queue_status(entry.status) == "waiting":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete an entry that has not been served yet",
        )
    appointment = _get_appointment_for_entry(db, entry)
    return _commit_transition(db, entry, appointment, "completed")


def complete(db: Session, entry_id: int) -> Queue:
    """Alias kept for the spec's ``complete`` name."""
    return complete_customer(db, entry_id)


def skip_customer(db: Session, entry_id: int) -> Queue:
    """waiting -> no_show (skip). Only waiting rows may be skipped (400
    otherwise; 409 when terminal)."""
    entry = _get_entry(db, entry_id)
    if _normalize_queue_status(entry.status) != "waiting":
        if entry.status in QUEUE_TERMINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Queue entry is already '{entry.status}'",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only waiting entries can be marked as no-show",
        )
    appointment = _get_appointment_for_entry(db, entry)
    return _commit_transition(db, entry, appointment, "no_show")


def serve_next(
    db: Session,
    barber_id: int,
    salon_id: int | None = None,
    appointment_date: "date | str | None" = None,
) -> Queue:
    """Serve the next waiting entry for (date, barber [+ salon]).

    Next = smallest ``queue_position`` with status waiting. Enforces a single
    active serving row per (date, barber): 409 if one exists. No waiting row
    => 404 (documented choice). Transition is atomic (queue + appointment +
    history + estimates in one transaction with rollback; FOR UPDATE
    attempted with SQLite fallback).
    """
    target_date = appointment_date or date.today()

    clash_scope_q = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == target_date,
            Queue.barber_id == barber_id,
            Queue.status == "serving",
        )
    )
    if salon_id is not None:
        clash_scope_q = clash_scope_q.filter(Queue.salon_id == salon_id)
    try:
        clash = _try_for_update(
            clash_scope_q.order_by(Queue.queue_position.asc())
        ).first()
    except Exception:
        clash = clash_scope_q.order_by(Queue.queue_position.asc()).first()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another customer is already being served for this barber",
        )

    next_q = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == target_date,
            Queue.barber_id == barber_id,
            Queue.status == "waiting",
        )
        .order_by(Queue.queue_position.asc())
    )
    if salon_id is not None:
        next_q = next_q.filter(Queue.salon_id == salon_id)
    try:
        entry = _try_for_update(next_q).first()
    except Exception:
        entry = next_q.first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No waiting customers for this barber",
        )
    appointment = _get_appointment_for_entry(db, entry)
    return _commit_transition(db, entry, appointment, "serving")


def cancel_queue_for_appointment(db: Session, appointment_id: int) -> Queue:
    """Sync helper for appointment cancellation: waiting/serving queue row ->
    cancelled (appointment -> cancelled) with history + estimate recompute.

    Idempotent on already-terminal rows (returns as-is, no duplicate
    history) so booking-cancel retries do not 409; explicit illegal edges
    via ``update_queue_entry`` still raise. 404 when no queue row exists.
    """
    entry = (
        db.query(Queue).filter(Queue.appointment_id == appointment_id).first()
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found for appointment",
        )
    appointment = _get_appointment_for_entry(db, entry)
    if entry.status in QUEUE_TERMINAL and appointment.status in (
        "completed",
        "cancelled",
        "no_show",
    ):
        return entry
    return _commit_transition(db, entry, appointment, "cancelled")


def recompute_estimates(
    db: Session, appt_date: date, barber_id: int, commit: bool = False
) -> None:
    """Public wrapper for estimate recompute (join/serve/complete/skip/
    cancel call this internally). Commits only when ``commit=True``."""
    recompute_estimates_for_scope(db, appt_date, barber_id)
    if commit:
        db.commit()
        try:  # WS2: wait-recompute emit post-commit only (scope-only update)
            from app.services import queue_events as _qe

            _qe.publish_updated(None, None, barber_id=barber_id, date=appt_date)
        except Exception:
            pass
