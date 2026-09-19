"""SmartQueue Phase 5C SAWTE (Service-Aware Wait Time Estimator).

Deterministic, no ML: pure arithmetic over measured durations
(``appointments.actual_duration_minutes``) with a mandatory fallback to
``services.duration_minutes``. No sklearn/numpy/learned weights, no hidden
clock except an injectable ``now`` parameter (for tests).

FORMULA (canonical):
    estimate(requester) = serving_remaining + SUM(expected(ahead waiting))
    serving_remaining   = max(0, ceil(expected(serving) - elapsed_minutes))
    expected(a)         = historical_avg(barber, service) if any history
                          else Service.duration_minutes (mandatory fallback)
    historical_avg      = sum(latest <=5 completed durations) / len(window)
    elapsed_minutes     = now - latest history.changed_at(new_status=in_progress)
                          for the serving appointment; if no start stamp,
                          remaining = expected (never Queue.joined_at).
    compute_actual      = max(1, ceil((completed_at - serving_start).minutes))

DECISIONS (documented per brief):
1. Storage: ONE nullable ``appointments.actual_duration_minutes`` column
   (see model comment). History deltas are transient/fragile and
   ``Queue.updated_at`` is overwritten, so neither can hold the measurement.
2. ``historical_average`` filters ``status == "completed"`` AND
   ``actual_duration_minutes IS NOT NULL``. That single predicate excludes
   cancelled / no_show / incomplete rows. "Future" rows are excluded in
   effect: a future appointment has no measured duration yet, so it can
   never satisfy the NOT-NULL completed predicate; no separate wall-clock
   date predicate is used so the function stays pure of
   (db, barber, service, limit) and test-seedable.
3. "Latest" = highest ``appointment_id`` first (monotonic insertion order;
   deterministic even when dates tie). ``total_count`` counts ALL matching
   rows (beyond the window); ``avg`` covers only the window.
4. No-start-stamp fallback: ``serving_remaining`` returns ``ceil(expected)``
   when no ``in_progress`` history row exists. ``Queue.joined_at`` is
   deliberately NOT used (join time != service-start time).
5. Confidence rule: each component (the serving row + every ahead waiting
   row) maps its pair's TOTAL count to LOW (0-2) / MEDIUM (3-5) / HIGH (6+);
   request confidence = min (weakest) over components. Zero components
   (empty queue ahead + no serving) -> LOW, because zero historical records
   are involved. Documented here as canonical.
6. No N+1: ``estimate_wait`` collects DISTINCT service_ids across
   serving + ahead rows, calls ``historical_average`` once per distinct
   (barber, service) pair (window LIMIT 5 + COUNT each), and fetches all
   fallback service durations in ONE ``IN`` query. Cost is bounded by
   distinct pairs, never by row count.
7. S2 owns the write path: this module only PROVIDES
   ``compute_actual_minutes`` + the column; it never writes
   ``actual_duration_minutes`` on complete.

All rounding is ``math.ceil`` to whole minutes (never underestimate wait).
"""

import math
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.queue import Queue
from app.models.service import Service
from app.models.status_history import AppointmentStatusHistory

HISTORY_WINDOW = 5


def _utcnow() -> datetime:
    return datetime.utcnow()


def historical_average(
    db: Session, barber_id: int, service_id: int, limit: int = HISTORY_WINDOW
) -> tuple[float | None, int]:
    """Return ``(avg_or_None, total_count)`` for a (barber, service) pair.

    Window: latest ``<= limit`` completed appointments with
    ``actual_duration_minutes NOT NULL``, newest first by
    ``appointment_id DESC``. ``avg = sum(window) / len(window)`` or None
    when the window is empty. ``total_count`` counts every matching row,
    including rows beyond the window.
    """
    base = (
        db.query(Appointment).filter(
            Appointment.barber_id == barber_id,
            Appointment.service_id == service_id,
            Appointment.status == "completed",
            Appointment.actual_duration_minutes.isnot(None),
        )
    )
    total_count = base.with_entities(func.count()).scalar() or 0
    window_rows = (
        base.with_entities(Appointment.actual_duration_minutes)
        .order_by(Appointment.appointment_id.desc())
        .limit(limit)
        .all()
    )
    durations = [int(r[0]) for r in window_rows if r[0] is not None]
    if not durations:
        return None, int(total_count)
    return float(sum(durations)) / float(len(durations)), int(total_count)


def expected_duration(
    db: Session, barber_id: int, service_id: int, limit: int = HISTORY_WINDOW
) -> float:
    """Expected minutes for a (barber, service) pair.

    Historical window average when available, else the mandatory fallback
    ``Service.duration_minutes``. Raises ``ValueError`` if the service row
    (fallback source) is missing.
    """
    avg, _ = historical_average(db, barber_id, service_id, limit=limit)
    if avg is not None:
        return float(avg)
    service = (
        db.query(Service).filter(Service.service_id == service_id).first()
    )
    if service is None or service.duration_minutes is None:
        raise ValueError(f"Service {service_id} not found for fallback duration")
    return float(service.duration_minutes)


def _confidence_level(total_count: int) -> str:
    if total_count >= 6:
        return "HIGH"
    if total_count >= 3:
        return "MEDIUM"
    return "LOW"


def serving_remaining(
    db: Session, serving_appointment: Appointment, now: datetime | None = None
) -> int:
    """Ceiled whole minutes left for the in-progress appointment.

    ``remaining = expected(serving) - elapsed`` where ``elapsed`` is minutes
    from the latest history ``changed_at`` with ``new_status='in_progress'``
    to ``now``. No start stamp -> remaining = ``ceil(expected)`` (never
    ``Queue.joined_at``). Clamped ``>= 0``, ``ceil`` to int.
    """
    expected = expected_duration(
        db, serving_appointment.barber_id, serving_appointment.service_id
    )
    moment = now if now is not None else _utcnow()
    start_row = (
        db.query(AppointmentStatusHistory)
        .filter(
            AppointmentStatusHistory.appointment_id
            == serving_appointment.appointment_id,
            AppointmentStatusHistory.new_status == "in_progress",
        )
        .order_by(
            AppointmentStatusHistory.changed_at.desc(),
            AppointmentStatusHistory.history_id.desc(),
        )
        .first()
    )
    if start_row is None or start_row.changed_at is None:
        return int(math.ceil(expected))
    elapsed = (moment - start_row.changed_at).total_seconds() / 60.0
    if elapsed < 0:
        elapsed = 0.0
    remaining = expected - elapsed
    if remaining <= 0:
        return 0
    return int(math.ceil(remaining))


def estimate_wait(
    db: Session,
    barber_id: int,
    appt_date: date,
    requester_position: int,
    now: datetime | None = None,
) -> tuple[int, str]:
    """Estimate wait for a requester at ``requester_position``.

    ``total = serving_remaining(same barber+date)``
    ``+ SUM(ceil(expected(ahead waiting row)))`` for waiting rows with
    ``queue_position < requester_position`` on the same barber+date.
    Returns ``(minutes_int, confidence)`` with the confidence rule from the
    module docstring (min over components; LOW when zero components).
    Batched per distinct (barber, service) pair: one window+count lookup
    each, plus one bulk service-duration fetch. No per-row N+1.
    """
    serving_row = (
        db.query(Queue, Appointment)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
            Queue.status == "serving",
        )
        .order_by(Queue.queue_position.asc())
        .first()
    )
    ahead_rows = (
        db.query(Queue, Appointment)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.appointment_date == appt_date,
            Queue.barber_id == barber_id,
            Queue.status == "waiting",
            Queue.queue_position < requester_position,
        )
        .order_by(Queue.queue_position.asc())
        .all()
    )

    # Batch: distinct service_ids -> one historical_average per pair.
    service_ids: list[int] = []
    if serving_row is not None:
        service_ids.append(int(serving_row[1].service_id))
    for _, appt in ahead_rows:
        service_ids.append(int(appt.service_id))
    distinct_ids = sorted(set(service_ids))

    stats: dict[int, tuple[float | None, int]] = {}
    for sid in distinct_ids:
        stats[sid] = historical_average(db, barber_id, sid)

    fallbacks: dict[int, float] = {}
    if distinct_ids:
        missing = [
            sid for sid, (avg, _) in stats.items() if avg is None
        ]
        if missing:
            rows = (
                db.query(Service.service_id, Service.duration_minutes)
                .filter(Service.service_id.in_(missing))
                .all()
            )
            for sid, dur in rows:
                fallbacks[int(sid)] = float(dur) if dur else 0.0

    def _expected_for(sid: int) -> float:
        avg, _ = stats[sid]
        if avg is not None:
            return float(avg)
        if sid in fallbacks:
            return float(fallbacks[sid])
        raise ValueError(f"Service {sid} not found for fallback duration")

    total = 0
    levels: list[str] = []
    if serving_row is not None:
        _, serving_appt = serving_row
        total += serving_remaining(db, serving_appt, now=now)
        _, count = stats[int(serving_appt.service_id)]
        levels.append(_confidence_level(count))
    for _, appt in ahead_rows:
        total += int(math.ceil(_expected_for(int(appt.service_id))))
        _, count = stats[int(appt.service_id)]
        levels.append(_confidence_level(count))

    if not levels:
        confidence = "LOW"
    else:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        confidence = min(levels, key=lambda lv: order[lv])
    return int(total), confidence


def compute_actual_minutes(
    serving_start_changed_at: datetime, completed_at: datetime
) -> int:
    """Ceiled measured minutes between service start and completion.

    Pure helper for S2 to call on complete (start = history ``in_progress``
    row's ``changed_at``, end = completion time). ``max(1, ceil(delta))``:
    sub-minute services still record 1 minute; clock skew (end < start)
    clamps to 1 rather than 0/negative.
    """
    delta = (completed_at - serving_start_changed_at).total_seconds() / 60.0
    return max(1, int(math.ceil(delta)))
