"""Phase 5C SAWTE tests (S3-Tests scope, tests only).

Ownership: this file + sawte_* fixtures in conftest.py ONLY. No app code,
docs, or migrations touched. Isolated in-memory SQLite; never touches
smartqueue.db. No AI/ML anywhere: pure arithmetic assertions only.

Contract under test (S1 + S2 landed and verified):
  S1: appointments.actual_duration_minutes (model + migration
    c9d1e2f3a4b5_add_actual_duration_minutes) + app/services/sawte.py pure
    estimator (historical_average, expected_duration, serving_remaining,
    estimate_wait, compute_actual_minutes; ceil policy; LOW 0-2 /
    MEDIUM 3-5 / HIGH 6+; latest-first by appointment_id DESC, window 5).
  S2-Integrate: queue_service wires SAWTE in (recompute_estimates_for_scope
    per-requester via estimate_for_entry; get_my_position returns
    {estimated_wait_minutes, confidence verbatim}; complete records the
    measured actual in the same transaction via compute_actual_minutes;
    WS events forward confidence). Retry-until-landed lazy imports with
    static-math fallbacks remain in app code for pre-S1 runs.

Canonical formula pinned here (from services/sawte.py):
  estimate(requester) = serving_remaining + SUM(ceil(expected(ahead)))
  expected(pair) = historical avg when any history else Service.duration
  serving_remaining = max(0, ceil(expected - elapsed)); no start stamp ->
    ceil(expected); never Queue.joined_at.
  compute_actual = max(1, ceil(completed - serving_start minutes)).

Seeding approach (documented): direct DB rows with
actual_duration_minutes + backdated status-history changed_at stamps
(sawte_seed_history fixture) for unit-level history, AND driving REST
serve/complete (which records measured actuals in-transaction; sub-minute
test services -> 1 min) for integration history. Seeded history lives on
past dates and never collides with same-day queue scopes.

Endpoint assertions cover both layers: history-free scenarios pin the
SAWTE fallback through my-position (incl. confidence LOW), and
history/REST-seeded scenarios pin SAWTE averages + confidence bands
end to end (LOW/MEDIUM/HIGH, ceil, serving remainder with elapsed).

32 tests: fallback(1) one-record(2) LOW(3) MEDIUM(4) five(5) HIGH-6(6)
latest-five-only(7) cancelled(8)/no-show(9)/future(10)/incomplete(11)
excluded cross-barber(12)/cross-service(13) serving-remaining(14)
none-serving(15) mostly-completed(16) non-negative(17) behind(18)
completed(19)/cancelled(20)/no-show(21) excluded positions(22)
ceil(23) confidence-counts(24) join(25)/serve(26)/complete(27)/skip(28)/
cancel(29) recalc WS(30) RBAC(31) regression(32).

No known blockers: S1, S2 estimator and S2 wiring all verified landed.
"""

from datetime import datetime as _datetime
from datetime import time as _time
from datetime import timedelta as _timedelta

import pytest

try:
    from app.services import sawte as _sawte

    _HAS_SAWTE = True
except Exception:
    _sawte = None  # type: ignore[assignment]
    _HAS_SAWTE = False

needs_sawte = pytest.mark.skipif(
    not _HAS_SAWTE,
    reason="BLOCKED: S1/S2 sawte module not landed (retry when S1/S2 land)",
)

APPT_BASE = "/api/v1/appointments"
QUEUE_BASE = "/api/v1/queue"


def _envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}, body
    assert isinstance(body["success"], bool), body
    assert isinstance(body["message"], str), body


def _book(client, headers, barber_id, service_id, date_str, start, salon_id):
    res = client.post(
        APPT_BASE,
        json={
            "barber_id": barber_id,
            "service_id": service_id,
            "appointment_date": date_str,
            "start_time": start,
            "salon_id": salon_id,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    return body["data"]


def _mypos(client, headers):
    res = client.get(QUEUE_BASE + "/my-position", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    return body["data"]


def _queues(db_session):
    from app.models.queue import Queue as _Q

    return db_session.query(_Q).order_by(_Q.queue_position.asc()).all()


def _stored(db_session, appointment_id):
    from app.models.queue import Queue as _Q

    return (
        db_session.query(_Q)
        .filter(_Q.appointment_id == appointment_id)
        .one()
    )


def _history(db_session, appointment_id):
    from app.models.status_history import AppointmentStatusHistory as _H

    return (
        db_session.query(_H)
        .filter(_H.appointment_id == appointment_id)
        .order_by(_H.history_id.asc())
        .all()
    )


def _find_queue_id(client, admin_headers, appointment_id):
    res = client.get(QUEUE_BASE, headers=admin_headers)
    assert res.status_code == 200, res.text
    for entry in res.json()["data"]:
        if entry.get("appointment_id") == appointment_id:
            return entry["queue_id"]
    raise AssertionError(f"no queue entry for appointment {appointment_id}")


def _pair(db_session, salon_barber, salon_service):
    return salon_barber.barber_id, salon_service.service_id


# ---------------------------------------------------------------------------
# 1-7: fallback / record counts / window / confidence bands (sawte surface).
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte01_fallback_no_history(
    client, customer_headers, customer2_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """1: no history -> (None, 0), fallback to Service.duration, conf LOW."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg is None
    assert count == 0
    assert _sawte.expected_duration(db_session, barber_id, service_id) == 30.0
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (30, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["has_queue"] is True
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"
    assert a["appointment_id"] != b["appointment_id"]


@needs_sawte
def test_sawte02_single_record_average(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """2: one completed actual=40 (duration 30) -> avg 40.0, count 1."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg == 40.0
    assert count == 1
    assert _sawte.expected_duration(db_session, barber_id, service_id) == 40.0
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (40, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 40
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte03_confidence_low(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """3: counts 1-2 -> LOW (0 covered by fallback test 1)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40, 42],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg == 41.0
    assert count == 2
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    total, conf = _sawte.estimate_wait(db_session, barber_id, slot_date, bpos)
    assert conf == "LOW"
    assert total == 41
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 41
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte04_confidence_medium(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, second_barber, salon_service, salon,
    slot_date, slot_availability, sawte_seed_history,
):
    """4: counts 3-4 -> MEDIUM (5 covered by test 5)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[38, 40, 42, 44],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg == 41.0
    assert count == 4
    sawte_seed_history(
        barber_id=second_barber.barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[10, 11, 12],
        salon_id=salon.salon_id,
    )
    _, count3 = _sawte.historical_average(
        db_session, second_barber.barber_id, service_id)
    assert count3 == 3
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    total, conf = _sawte.estimate_wait(db_session, barber_id, slot_date, bpos)
    assert conf == "MEDIUM"
    assert total == 41
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 41
    assert pos["confidence"] == "MEDIUM"


@needs_sawte
def test_sawte05_five_records_full_window(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """5: exactly five records -> avg over all five, count 5 (MEDIUM)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[36, 38, 40, 42, 44],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg == 40.0
    assert count == 5
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (40, "MEDIUM")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 40
    assert pos["confidence"] == "MEDIUM"


@needs_sawte
def test_sawte06_high_six_records(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """6: six records -> HIGH; avg over latest five (oldest outlier cut)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[20, 36, 38, 40, 42, 44],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert count == 6
    assert avg == 40.0  # latest five exclude the oldest 20
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (40, "HIGH")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 40
    assert pos["confidence"] == "HIGH"


@needs_sawte
def test_sawte07_latest_five_only(
    db_session, customer_user, salon_barber, salon_service, salon,
    sawte_seed_history,
):
    """7: seven records -> window holds only the latest five (count 7)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id,
        durations=[99, 98, 21, 22, 23, 24, 25],
        salon_id=salon.salon_id,
    )
    avg, count = _sawte.historical_average(db_session, barber_id, service_id)
    assert count == 7
    assert avg == 23.0  # (21+22+23+24+25)/5; 99/98 excluded


# ---------------------------------------------------------------------------
# 8-11: history exclusions (status / future / NULL actual).
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte08_cancelled_excluded(db_session, customer_user, salon_barber,
                                    salon_service, salon, sawte_seed_history):
    """8: cancelled rows (even with an actual) never enter the average."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40, 40, 200],
        statuses=["completed", "completed", "cancelled"],
        salon_id=salon.salon_id,
    )
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 2)


@needs_sawte
def test_sawte09_noshow_excluded(db_session, customer_user, salon_barber,
                                 salon_service, salon, sawte_seed_history):
    """9: no_show rows (even with an actual) never enter the average."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40, 40, 200],
        statuses=["completed", "completed", "no_show"],
        salon_id=salon.salon_id,
    )
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 2)


@needs_sawte
def test_sawte10_future_excluded(db_session, customer_user, salon_barber,
                                 salon_service, salon, slot_date,
                                 sawte_seed_history):
    """10: future appointments have no measured duration -> excluded.

    Per S2 decision 2 this holds in effect: only completed NOT-NULL rows
    count, and a future appointment can never satisfy that predicate.
    """
    from app.models.appointment import Appointment as _Appointment

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    future = slot_date + _timedelta(days=30)
    for st, actual, start in (("booked", None, _time(10, 0)),
                              ("in_progress", 55, _time(11, 0))):
        db_session.add(_Appointment(
            customer_id=customer_user.user_id,
            salon_id=salon.salon_id,
            barber_id=barber_id,
            service_id=service_id,
            appointment_date=future,
            start_time=start,
            end_time=_time(11, 30) if start == _time(11, 0) else _time(10, 30),
            status=st,
            booking_type="online",
            actual_duration_minutes=actual,
        ))
    db_session.commit()
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 1)


@needs_sawte
def test_sawte11_incomplete_excluded(db_session, customer_user, salon_barber,
                                     salon_service, salon, sawte_seed_history):
    """11: non-completed statuses (even with actuals) and NULL actuals out."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id,
        durations=[40, 50, 55, 60, None],
        statuses=["completed", "booked", "waiting", "in_progress", "completed"],
        salon_id=salon.salon_id,
    )
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 1)


# ---------------------------------------------------------------------------
# 12-13: cross-pair isolation.
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte12_cross_barber_isolation(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, second_barber, salon_service, salon,
    slot_date, slot_availability, sawte_seed_history,
):
    """12: another barber's history never leaks into this pair's average."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=second_barber.barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[200, 200, 200],
        salon_id=salon.salon_id,
    )
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 1)
    assert _sawte.historical_average(
        db_session, second_barber.barber_id, service_id) == (200.0, 3)
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (40, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 40
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte13_cross_service_isolation(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, second_service, salon,
    slot_date, slot_availability, sawte_seed_history,
):
    """13: another service's history never leaks into this pair's average."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=second_service.service_id,
        customer_id=customer_user.user_id, durations=[200, 200],
        salon_id=salon.salon_id,
    )
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    assert _sawte.historical_average(db_session, barber_id, service_id) == (40.0, 1)
    assert _sawte.historical_average(
        db_session, barber_id, second_service.service_id) == (200.0, 2)
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (40, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 40
    assert pos["confidence"] == "LOW"


# ---------------------------------------------------------------------------
# 14-18: serving remainder, scope, sign, behind.
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte14_serving_remaining_included(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    customer_user, salon_barber, salon_service, salon,
    slot_date, slot_availability, sawte_seed_history,
):
    """14: serving row contributes remaining = ceil(expected - elapsed)."""
    from app.models.appointment import Appointment as _Appointment
    from app.models.status_history import AppointmentStatusHistory as _History

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    db_session.expire_all()
    serving_appt = (
        db_session.query(_Appointment)
        .filter(_Appointment.appointment_id == a["appointment_id"]).one()
    )
    stamp = (
        db_session.query(_History)
        .filter(_History.appointment_id == a["appointment_id"],
                _History.new_status == "in_progress").one()
    )
    t0 = _datetime.utcnow() - _timedelta(minutes=5)
    stamp.changed_at = t0
    db_session.commit()
    now = t0 + _timedelta(minutes=5)
    assert _sawte.serving_remaining(db_session, serving_appt, now=now) == 35
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos, now=now) == (35, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 0
    assert pos["currently_serving"] == 1
    assert pos["estimated_wait_minutes"] == 35  # 5 min elapsed of 40
    assert pos["confidence"] == "LOW"
    # No start stamp -> full ceil(expected), never Queue.joined_at.
    db_session.delete(stamp)
    db_session.commit()
    assert _sawte.serving_remaining(db_session, serving_appt, now=now) == 40
    # Future stamp (clock skew) -> elapsed clamps to 0 -> full expected.
    db_session.add(_History(
        appointment_id=a["appointment_id"], old_status="booked",
        new_status="in_progress", changed_at=now + _timedelta(minutes=10)))
    db_session.commit()
    assert _sawte.serving_remaining(db_session, serving_appt, now=now) == 40


@needs_sawte
def test_sawte15_no_serving_remainder_zero(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """15: with nobody serving, total == ahead-only (serving adds 0)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    total, conf = _sawte.estimate_wait(db_session, barber_id, slot_date, bpos)
    assert total == 40  # ahead ceil(40) + serving 0
    assert conf == "LOW"


@needs_sawte
def test_sawte16_mostly_completed(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """16: history-free queue where most ahead rows completed -> only live
    waiting ahead counts. REST completions record measured actuals (fast
    tests -> 1 min each), so D waits ceil(avg(1,1)) = 1 for C."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    _, c4h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    d = _book(client, c4h, barber_id, service_id, day, "11:30", salon.salon_id)
    for appt in (a, b):
        qid = _find_queue_id(client, admin_headers, appt["appointment_id"])
        assert client.post(f"{QUEUE_BASE}/{qid}/serve", headers=admin_headers).status_code == 200
        assert client.post(f"{QUEUE_BASE}/{qid}/complete", headers=admin_headers).status_code == 200
    db_session.expire_all()
    from app.models.appointment import Appointment as _Appointment

    actuals = [
        r.actual_duration_minutes for r in db_session.query(_Appointment)
        .filter(_Appointment.appointment_id.in_(
            [a["appointment_id"], b["appointment_id"]])).all()
    ]
    assert actuals == [1, 1]  # REST-seeded history: sub-minute service -> 1
    dpos = _stored(db_session, d["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, dpos) == (1, "LOW")
    pos = _mypos(client, c4h)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 1
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte17_wait_non_negative(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    customer_user, salon_barber, salon_service, salon,
    slot_date, slot_availability, sawte_seed_history,
):
    """17: over-elapsed serving clamps to 0; totals never go negative."""
    from app.models.appointment import Appointment as _Appointment
    from app.models.status_history import AppointmentStatusHistory as _History

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[30],
        salon_id=salon.salon_id,
    )
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    db_session.expire_all()
    serving_appt = (
        db_session.query(_Appointment)
        .filter(_Appointment.appointment_id == a["appointment_id"]).one()
    )
    stamp = (
        db_session.query(_History)
        .filter(_History.appointment_id == a["appointment_id"],
                _History.new_status == "in_progress").one()
    )
    now = _datetime.utcnow()
    stamp.changed_at = now - _timedelta(minutes=60)  # elapsed >> expected
    db_session.commit()
    assert _sawte.serving_remaining(db_session, serving_appt, now=now) == 0
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    total, _ = _sawte.estimate_wait(db_session, barber_id, slot_date, bpos, now=now)
    assert total >= 0


@needs_sawte
def test_sawte18_behind_excluded(
    client, customer_headers, customer2_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """18: waiting rows behind the requester never count (B waits only A)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, bpos) == (30, "LOW")
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"


# ---------------------------------------------------------------------------
# 19-22: terminal-row exclusion from live scope; positions stable.
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte19_completed_excluded(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """19: completed rows leave people-ahead and the wait. The REST
    completion records a measured actual (fast test -> 1 min), so C waits
    ceil(1.0) = 1 for B."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    c = _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    assert client.post(f"{QUEUE_BASE}/{qid_a}/complete", headers=admin_headers).status_code == 200
    db_session.expire_all()
    from app.models.appointment import Appointment as _Appointment

    assert db_session.query(_Appointment).filter(
        _Appointment.appointment_id == a["appointment_id"]).one() \
        .actual_duration_minutes == 1
    cpos = _stored(db_session, c["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, cpos) == (1, "LOW")
    pos = _mypos(client, c3h)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 1
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte20_cancelled_excluded(
    client, customer_headers, customer2_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """20: cancelled rows leave people-ahead and the wait (C waits only B)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    c = _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    assert client.delete(
        f"{APPT_BASE}/{a['appointment_id']}", headers=customer_headers).status_code == 200
    db_session.expire_all()
    assert _stored(db_session, a["appointment_id"]).status == "cancelled"
    cpos = _stored(db_session, c["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, cpos) == (30, "LOW")
    pos = _mypos(client, c3h)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte21_noshow_excluded(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """21: no_show rows leave people-ahead and the wait (C waits only B)."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    c = _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/skip", headers=admin_headers).status_code == 200
    db_session.expire_all()
    cpos = _stored(db_session, c["appointment_id"]).queue_position
    assert _sawte.estimate_wait(db_session, barber_id, slot_date, cpos) == (30, "LOW")
    pos = _mypos(client, c3h)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"


@needs_sawte
def test_sawte22_positions_unchanged(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """22: estimating + transitions never renumber; freed numbers unreused."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    _, c4h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    c = _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    assert [q.queue_position for q in _queues(db_session)] == [1, 2, 3]
    cpos = _stored(db_session, c["appointment_id"]).queue_position
    _sawte.estimate_wait(db_session, barber_id, slot_date, cpos)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    assert client.post(f"{QUEUE_BASE}/{qid_a}/complete", headers=admin_headers).status_code == 200
    d = _book(client, c4h, barber_id, service_id, day, "11:30", salon.salon_id)
    db_session.expire_all()
    live = {q.appointment_id: q.queue_position
            for q in _queues(db_session) if q.status in ("waiting", "serving")}
    assert live[_stored(db_session, b["appointment_id"]).appointment_id] == 2
    assert live[_stored(db_session, c["appointment_id"]).appointment_id] == 3
    assert live[d["appointment_id"]] == 4  # max+1, gap at 1 persists


# ---------------------------------------------------------------------------
# 23-24: ceil policy + confidence aggregation.
# ---------------------------------------------------------------------------


@needs_sawte
def test_sawte23_ceil_rounding(
    client, customer_headers, customer2_headers, db_session, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_seed_history,
):
    """23: fractional averages ceil per ahead row; actuals ceil, min 1."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    sawte_seed_history(
        barber_id=barber_id, service_id=service_id,
        customer_id=customer_user.user_id, durations=[10, 11],
        salon_id=salon.salon_id,
    )
    avg, _ = _sawte.historical_average(db_session, barber_id, service_id)
    assert avg == 10.5
    day = slot_date.isoformat()
    _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    bpos = _stored(db_session, b["appointment_id"]).queue_position
    total, _ = _sawte.estimate_wait(db_session, barber_id, slot_date, bpos)
    assert total == 11  # ceil(10.5), never underestimate
    t = _datetime(2026, 5, 1, 10, 0, 0)
    assert _sawte.compute_actual_minutes(t, t + _timedelta(seconds=61)) == 2
    assert _sawte.compute_actual_minutes(t, t + _timedelta(seconds=30)) == 1
    assert _sawte.compute_actual_minutes(t, t + _timedelta(minutes=5)) == 5
    assert _sawte.compute_actual_minutes(t + _timedelta(minutes=1), t) == 1


@needs_sawte
def test_sawte24_confidence_counts(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    customer_user, salon_barber, salon_service, second_service, salon,
    second_barber, slot_date, slot_availability, sawte_extra_customer_factory,
    sawte_seed_history,
):
    """24: request confidence = min over components; empty scope -> LOW."""
    barber_id, svc1 = _pair(db_session, salon_barber, salon_service)
    svc2 = second_service.service_id
    sawte_seed_history(
        barber_id=barber_id, service_id=svc1,
        customer_id=customer_user.user_id, durations=[40],
        salon_id=salon.salon_id,
    )
    sawte_seed_history(
        barber_id=barber_id, service_id=svc2,
        customer_id=customer_user.user_id, durations=[20] * 6,
        salon_id=salon.salon_id,
    )
    _, c3h = sawte_extra_customer_factory()
    _, c4h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, svc2, day, "10:00", salon.salon_id)
    c = _book(client, customer2_headers, barber_id, svc1, day, "10:30", salon.salon_id)
    d = _book(client, c3h, barber_id, svc2, day, "11:00", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    db_session.expire_all()
    dpos = _stored(db_session, d["appointment_id"]).queue_position
    total, conf = _sawte.estimate_wait(db_session, barber_id, slot_date, dpos)
    assert conf == "LOW"  # serving HIGH + ahead LOW -> weakest wins
    assert total == 20 + 40
    cpos = _stored(db_session, c["appointment_id"]).queue_position
    total_c, conf_c = _sawte.estimate_wait(db_session, barber_id, slot_date, cpos)
    assert (total_c, conf_c) == (20, "HIGH")  # serving-only component
    x = _book(client, c4h, second_barber.barber_id, svc1, day, "10:00", salon.salon_id)
    xpos = _stored(db_session, x["appointment_id"]).queue_position
    assert _sawte.estimate_wait(
        db_session, second_barber.barber_id, slot_date, xpos) == (0, "LOW")


# ---------------------------------------------------------------------------
# 25-29: estimate recalc on every queue mutation (live engine).
# ---------------------------------------------------------------------------


def test_sawte25_join_recalc(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """25: join appends max+1, newcomer waits the head, created emits wait."""
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _qe.clear_outbox()
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    db_session.expire_all()
    assert _stored(db_session, b["appointment_id"]).queue_position == 2
    assert _stored(db_session, b["appointment_id"]).estimated_wait_minutes == 30
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"
    created = [e for e in _qe.peek_outbox() if e.get("type") == "queue.created"]
    assert created, "join must emit queue.created"
    mine = [e for e in created
            if e.get("data", {}).get("appointment_id") == b["appointment_id"]]
    assert mine
    assert mine[0]["data"]["estimated_wait_minutes"] == 30
    assert mine[0]["data"]["queue_position"] == 2
    assert a["appointment_id"] != b["appointment_id"]


def test_sawte26_serve_recalc(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """26: serve recomputes the scope (serving keeps own duration; next
    waits the serving remainder) and emits serving."""
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    _qe.clear_outbox()
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    res = client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    db_session.expire_all()
    assert _stored(db_session, a["appointment_id"]).estimated_wait_minutes == 30
    assert _stored(db_session, b["appointment_id"]).estimated_wait_minutes == 30
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 0
    assert pos["estimated_wait_minutes"] == 30
    assert pos["currently_serving"] == 1
    assert pos["confidence"] == "LOW"
    assert any(e.get("type") == "queue.serving" for e in _qe.peek_outbox())


def test_sawte27_complete_recalc(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """27: complete recomputes the scope (next waits 0), records the
    measured actual in-transaction, and emits completed."""
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid_a}/serve", headers=admin_headers).status_code == 200
    _qe.clear_outbox()
    res = client.post(f"{QUEUE_BASE}/{qid_a}/complete", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert res.json()["data"]["status"] == "completed"
    db_session.expire_all()
    from app.models.appointment import Appointment as _Appointment

    assert db_session.query(_Appointment).filter(
        _Appointment.appointment_id == a["appointment_id"]).one() \
        .actual_duration_minutes == 1  # measured in-transaction
    assert _stored(db_session, b["appointment_id"]).estimated_wait_minutes == 0
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 0
    assert pos["estimated_wait_minutes"] == 0
    assert pos["confidence"] == "LOW"
    assert any(e.get("type") == "queue.completed" for e in _qe.peek_outbox())


def test_sawte28_skip_recalc(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """28: skip recomputes the scope (next waits 0) and emits skipped."""
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    qid_a = _find_queue_id(client, admin_headers, a["appointment_id"])
    _qe.clear_outbox()
    res = client.post(f"{QUEUE_BASE}/{qid_a}/skip", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert res.json()["data"]["status"] == "no_show"
    db_session.expire_all()
    assert _stored(db_session, b["appointment_id"]).estimated_wait_minutes == 0
    pos = _mypos(client, customer2_headers)
    assert pos["people_ahead"] == 0
    assert pos["estimated_wait_minutes"] == 0
    assert pos["confidence"] == "LOW"
    assert any(e.get("type") == "queue.skipped" for e in _qe.peek_outbox())


def test_sawte29_cancel_recalc(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    sawte_extra_customer_factory,
):
    """29: cancel syncs queue->cancelled; live scope drops the row
    (C waits only B) and cancel emits. Positions are never reused."""
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    _, c3h = sawte_extra_customer_factory()
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    _book(client, c3h, barber_id, service_id, day, "11:00", salon.salon_id)
    _qe.clear_outbox()
    res = client.delete(f"{APPT_BASE}/{a['appointment_id']}", headers=customer_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    db_session.expire_all()
    assert _stored(db_session, a["appointment_id"]).status == "cancelled"
    assert [q.queue_position for q in _queues(db_session)] == [1, 2, 3]
    pos = _mypos(client, c3h)
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert pos["confidence"] == "LOW"
    assert any(e.get("type") == "queue.cancelled" for e in _qe.peek_outbox())


# ---------------------------------------------------------------------------
# 30-32: WS events, RBAC, end-to-end regression.
# ---------------------------------------------------------------------------


def _try_receive(ws, timeout=5.0):
    import queue as _queue
    import threading

    box: _queue.Queue = _queue.Queue(maxsize=1)

    def _run():
        try:
            box.put(("ok", ws.receive_json()))
        except Exception as exc:
            try:
                box.put(("err", exc))
            except Exception:
                pass

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    try:
        kind, val = box.get(timeout=timeout)
    except _queue.Empty:
        return None
    return val if kind == "ok" else None


def _payload_text(msg):
    import json

    try:
        return json.dumps(msg, default=str).lower()
    except Exception:
        return str(msg).lower()


def test_sawte30_ws_events_work(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """30: join/serve-next broadcast with positions + waits; payloads safe."""
    from app.services import queue_events as _qe
    from tests.conftest import ws_queue_url, ws_raw_token_from_headers

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    _qe.clear_outbox()
    full = ws_queue_url(
        salon.salon_id, token=ws_raw_token_from_headers(admin_headers),
        date_str=day)
    with client.websocket_connect(full) as ws:
        snap = _try_receive(ws, timeout=5.0)
        assert snap is not None, "expected initial WS snapshot, got none"
        text = _payload_text(snap)
        assert "queue.updated" in text
        assert "queue_position" in text
        assert "estimated_wait" in text
        assert "confidence" in text
        b = _book(client, customer2_headers, barber_id, service_id, day, "10:30",
                  salon.salon_id)
        created = _try_receive(ws, timeout=5.0)
        assert created is not None, "expected create broadcast, got none"
        ctext = _payload_text(created)
        assert any(m in ctext for m in ("queue.created", "created", "waiting"))
        assert str(b["appointment_id"]) in ctext
        res = client.post(
            QUEUE_BASE + "/serve-next",
            json={"barber_id": barber_id, "salon_id": salon.salon_id},
            headers=admin_headers)
        assert res.status_code == 200, res.text
        serving = _try_receive(ws, timeout=5.0)
        assert serving is not None, "expected serve-next broadcast, got none"
        assert any(m in _payload_text(serving)
                   for m in ("serving", "queue.serving"))
        for msg in (snap, created, serving):
            t = _payload_text(msg)
            for banned in ("password_hash", "$2b$", "jwt_secret", "secret_key",
                           "access_token", "customer@test.com", "1234567890"):
                assert banned not in t, f"WS payload leaks {banned!r}: {msg}"
    types = [e.get("type", "") for e in _qe.peek_outbox()]
    assert "queue.created" in types
    assert "queue.serving" in types
    assert a["appointment_id"] != b["appointment_id"]


def test_sawte31_rbac_pass(
    client, customer_headers, customer2_headers, admin_headers, db_session,
    customer_user, customer2_user, salon_barber, salon_service, salon,
    slot_date, slot_availability,
):
    """31: my-position/queue RBAC: anon 401, own 200 isolated, staff 200,
    customer ops 403."""
    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    a = _book(client, customer_headers, barber_id, service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, barber_id, service_id, day, "10:30", salon.salon_id)
    anon = client.get(QUEUE_BASE + "/my-position")
    assert anon.status_code == 401, anon.text
    _envelope(anon.json())
    assert anon.json()["success"] is False
    mine = _mypos(client, customer_headers)
    assert mine["has_queue"] is True
    assert mine["queue_position"] == 1
    assert mine["confidence"] == "LOW"
    other = _mypos(client, customer2_headers)
    assert other["queue_position"] == 2
    assert other["confidence"] == "LOW"
    assert other["appointment_status"] == "booked"
    cross = client.get(f"{APPT_BASE}/{a['appointment_id']}", headers=customer2_headers)
    assert cross.status_code == 403, cross.text
    own = client.get(f"{APPT_BASE}/{a['appointment_id']}", headers=customer_headers)
    assert own.status_code == 200, own.text
    denied = client.get(QUEUE_BASE, headers=customer_headers)
    assert denied.status_code == 403, denied.text
    _envelope(denied.json())
    assert denied.json()["success"] is False
    listed = client.get(QUEUE_BASE, headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]) == 2
    qid_b = _find_queue_id(client, admin_headers, b["appointment_id"])
    serve_denied = client.post(f"{QUEUE_BASE}/{qid_b}/serve", headers=customer_headers)
    assert serve_denied.status_code == 403, serve_denied.text
    _envelope(serve_denied.json())
    assert serve_denied.json()["success"] is False
    assert customer_user.user_id != customer2_user.user_id


def test_sawte32_appointment_queue_regression(
    client, customer_headers, admin_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """32: book -> serve -> complete keeps appointment/queue/history/
    estimates consistent (envelope + exact codes throughout)."""
    from app.models.appointment import Appointment as _Appointment
    from app.services import queue_events as _qe

    barber_id, service_id = _pair(db_session, salon_barber, salon_service)
    day = slot_date.isoformat()
    _qe.clear_outbox()
    data = _book(client, customer_headers, barber_id, service_id, day, "10:00",
                 salon.salon_id)
    assert data["status"] == "booked"
    qid = _find_queue_id(client, admin_headers, data["appointment_id"])
    served = client.post(f"{QUEUE_BASE}/{qid}/serve", headers=admin_headers)
    assert served.status_code == 200, served.text
    _envelope(served.json())
    assert served.json()["data"]["status"] == "serving"
    done = client.post(f"{QUEUE_BASE}/{qid}/complete", headers=admin_headers)
    assert done.status_code == 200, done.text
    _envelope(done.json())
    assert done.json()["data"]["status"] == "completed"
    db_session.expire_all()
    appt = (
        db_session.query(_Appointment)
        .filter(_Appointment.appointment_id == data["appointment_id"]).one()
    )
    assert appt.status == "completed"
    row = _stored(db_session, data["appointment_id"])
    assert row.status == "completed"
    assert isinstance(row.estimated_wait_minutes, int)
    assert row.estimated_wait_minutes >= 0
    assert [(h.old_status, h.new_status)
            for h in _history(db_session, data["appointment_id"])] == [
        (None, "booked"), ("booked", "in_progress"), ("in_progress", "completed")]
    pos = _mypos(client, customer_headers)
    assert pos["has_queue"] is False
    listed = client.get(QUEUE_BASE, headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert [e["appointment_id"] for e in listed.json()["data"]] == []
    types = [e.get("type", "") for e in _qe.peek_outbox()]
    assert types == ["queue.created", "queue.serving", "queue.completed"]
