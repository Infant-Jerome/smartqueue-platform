"""Phase 3 appointment booking tests (B4-Tests scope, tests only).

Contract (implemented by API agent):
  POST /api/v1/appointments {barber_id, service_id, appointment_date,
    start_time, salon_id?, booking_type?} -> 201. Server derives end_time
    from the service duration; client end_time/customer_id are rejected
    (422 extra=forbid). ?customer_id=<other> as customer -> 403.
  PUT /api/v1/appointments/{id} {appointment_date?, start_time?, status?}
    -> 200. Terminal (completed/cancelled) rows are immutable (400);
    cancelled -> completed is an invalid transition (400).
  History rows (None->booked on create, *->cancelled on cancel) live in
  appointment_status_history.
Envelope {success, message, data} + exact codes everywhere.
Isolated in-memory SQLite only.
"""
from datetime import date as _date
from datetime import time as _time
from datetime import timedelta as _timedelta

APPT_BASE = "/api/v1/appointments"


def _envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}, body
    assert isinstance(body["success"], bool), body
    assert isinstance(body["message"], str), body


def _payload(barber_id, service_id, date_str, start, salon_id=None, extra=None):
    body = {
        "barber_id": barber_id,
        "service_id": service_id,
        "appointment_date": date_str,
        "start_time": start,
    }
    if salon_id is not None:
        body["salon_id"] = salon_id
    if extra:
        body.update(extra)
    return body


def _slot(slot_date, salon_barber, salon_service, salon, start="10:00"):
    return _payload(
        salon_barber.barber_id,
        salon_service.service_id,
        slot_date.isoformat(),
        start,
        salon_id=salon.salon_id,
    )


# ---------------------------------------------------------------------------
# BOOKING (26)
# ---------------------------------------------------------------------------

def test_booking_success(client, customer_headers, customer_user,
                         salon_barber, salon_service, salon,
                         slot_date, slot_availability):
    """B1: valid booking -> 201, envelope, booked, queue #1, self-owned."""
    res = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                      headers=customer_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "booked"
    assert data["customer_id"] == customer_user.user_id
    assert data.get("queue_position", data.get("queue_number")) == 1
    assert data["appointment_id"] is not None


def test_booking_unauthenticated(client, salon_barber, salon_service, salon, slot_date):
    """B2: no token -> 401, envelope."""
    res = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon))
    assert res.status_code == 401, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


def test_booking_self_ownership(client, customer_headers, customer_user,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """B3: booking is owned by the caller."""
    res = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                      headers=customer_headers)
    assert res.status_code == 201, res.text
    assert res.json()["data"]["customer_id"] == customer_user.user_id


def test_booking_no_customer_id_inject(client, customer_headers, customer_user,
                                       customer2_user, salon_barber, salon_service,
                                       salon, slot_date, slot_availability):
    """B4: customer_id injection rejected: body field -> 422, query alias -> 403."""
    smuggled = _slot(slot_date, salon_barber, salon_service, salon)
    smuggled["customer_id"] = customer2_user.user_id
    res = client.post(APPT_BASE, json=smuggled, headers=customer_headers)
    assert res.status_code == 422, res.text
    assert res.json()["success"] is False

    res = client.post(
        APPT_BASE,
        params={"customer_id": customer2_user.user_id},
        json=_slot(slot_date, salon_barber, salon_service, salon),
        headers=customer_headers,
    )
    assert res.status_code == 403, res.text
    assert res.json()["success"] is False


def test_booking_nonexistent_salon(client, customer_headers, salon_barber,
                                   salon_service, slot_date, slot_availability):
    """B5: unknown salon_id -> 404."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=999999),
        headers=customer_headers,
    )
    assert res.status_code == 404, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_nonexistent_service(client, customer_headers, salon_barber,
                                     salon, slot_date, slot_availability):
    """B6: unknown service_id -> 404."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, 999999,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 404, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_nonexistent_barber(client, customer_headers, salon_service,
                                    salon, slot_date):
    """B7: unknown barber_id -> 404."""
    res = client.post(
        APPT_BASE,
        json=_payload(999999, salon_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 404, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_cross_salon_service(client, customer_headers, salon_barber,
                                     salon2_service, salon, slot_date, slot_availability):
    """B8: barber (salon A) + service (salon B) -> 400."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon2_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_cross_salon_barber(client, customer_headers, salon2_barber,
                                    salon_service, salon, slot_date, slot_availability):
    """B9: barber (salon B) booked under salon A -> 400."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon2_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_inactive_service(client, customer_headers, salon_barber,
                                  inactive_service, salon, slot_date, slot_availability):
    """B10: inactive service -> 400."""
    res = client.post(
        APPT_BASE, json=_slot(slot_date, salon_barber, inactive_service, salon),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_inactive_salon(client, customer_headers, salon_barber,
                                salon_service, inactive_salon,
                                slot_date, slot_availability):
    """B11: inactive salon -> 400."""
    res = client.post(
        APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, inactive_salon),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_invalid_date(client, customer_headers, salon_barber,
                              salon_service, salon, slot_availability):
    """B12: malformed appointment_date -> 422."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      "not-a-date", "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 422, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_past_date(client, customer_headers, salon_barber,
                           salon_service, salon, slot_availability):
    """B13: yesterday -> 400 mentioning past."""
    yesterday = (_date.today() - _timedelta(days=1)).isoformat()
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      yesterday, "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    assert "past" in res.json()["message"].lower()


def test_booking_today_past_time(client, customer_headers, salon_barber,
                                 salon_service, salon):
    """B14: today with a start_time already past -> 400."""
    from datetime import datetime as _dt

    now = _dt.now()
    if now.hour >= 2:
        start = _time(now.hour - 2, now.minute).strftime("%H:%M")
    else:  # just after midnight: 00:00 slot is already past
        start = "00:00"
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      _date.today().isoformat(), start, salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_outside_hours(client, customer_headers, salon_barber,
                               salon_service, salon, slot_date, slot_availability):
    """B15: 07:00 slot outside 09:00-18:00 salon hours -> 400."""
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "07:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_barber_not_available(client, customer_headers, db_session,
                                      second_barber, second_service, salon,
                                      slot_date, slot_availability):
    """B16: barber flagged unavailable for the slot -> 400."""
    from app.models.availability import BarberAvailability as _Avail

    db_session.add(_Avail(barber_id=second_barber.barber_id, date=slot_date,
                          start_time=_time(9, 0), end_time=_time(18, 0),
                          status="unavailable"))
    db_session.commit()
    res = client.post(
        APPT_BASE,
        json=_payload(second_barber.barber_id, second_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_duration_from_service(client, customer_headers, salon_barber,
                                       salon_service, salon,
                                       slot_date, slot_availability):
    """B17: server derives end_time (10:00 + 30 min = 10:30) -> 201."""
    res = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                      headers=customer_headers)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["start_time"][:5] == "10:00"
    assert data["end_time"][:5] == "10:30"
    assert salon_service.duration_minutes == 30


def test_booking_duration_manipulation_rejected(client, customer_headers,
                                                salon_barber, salon_service, salon,
                                                slot_date, slot_availability):
    """B18: client-supplied end_time is never trusted -> 422."""
    smuggled = _slot(slot_date, salon_barber, salon_service, salon)
    smuggled["end_time"] = "11:00"
    res = client.post(APPT_BASE, json=smuggled, headers=customer_headers)
    assert res.status_code == 422, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_adjacent_allowed(client, customer_headers, salon_barber,
                                  salon_service, salon,
                                  slot_date, slot_availability):
    """B19: back-to-back slots (touching boundary) -> both 201."""
    first = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                        headers=customer_headers)
    assert first.status_code == 201, first.text
    second = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "10:30", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert second.status_code == 201, second.text


def test_booking_partial_overlap_rejected(client, customer_headers, salon_barber,
                                          salon_service, salon,
                                          slot_date, slot_availability):
    """B20: partial overlap (10:15 over 10:00-10:30) -> 409."""
    assert client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                       headers=customer_headers).status_code == 201
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "10:15", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 409, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_booking_inner_overlap_rejected(client, customer_headers, db_session,
                                        salon, salon_barber, salon_service,
                                        slot_date, slot_availability):
    """B21: inner overlap (30-min inside a 60-min booking) -> 409."""
    from app.models.service import Service as _Service

    long_svc = _Service(service_name="Long Cut", description="60 min",
                        duration_minutes=60, price=500.00,
                        status="active", salon_id=salon.salon_id)
    db_session.add(long_svc)
    db_session.commit()
    db_session.refresh(long_svc)
    base = _payload(salon_barber.barber_id, long_svc.service_id,
                    slot_date.isoformat(), "10:00", salon_id=salon.salon_id)
    assert client.post(APPT_BASE, json=base, headers=customer_headers).status_code == 201
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, salon_service.service_id,
                      slot_date.isoformat(), "10:05", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 409, res.text
    assert res.json()["success"] is False


def test_booking_outer_overlap_rejected(client, customer_headers, db_session,
                                        salon, salon_barber, salon_service,
                                        slot_date, slot_availability):
    """B22: outer overlap (60-min enclosing a 30-min booking) -> 409."""
    from app.models.service import Service as _Service

    long_svc = _Service(service_name="Long Cut 2", description="60 min",
                        duration_minutes=60, price=500.00,
                        status="active", salon_id=salon.salon_id)
    db_session.add(long_svc)
    db_session.commit()
    db_session.refresh(long_svc)
    assert client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                       headers=customer_headers).status_code == 201
    res = client.post(
        APPT_BASE,
        json=_payload(salon_barber.barber_id, long_svc.service_id,
                      slot_date.isoformat(), "09:45", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert res.status_code == 409, res.text
    assert res.json()["success"] is False


def test_booking_different_barber_same_time_allowed(
    client, customer_headers, customer2_headers,
    salon_barber, second_barber, salon_service, second_service,
    salon, slot_date, slot_availability,
):
    """B23: different customer + different barber, same slot -> 201."""
    first = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                        headers=customer_headers)
    assert first.status_code == 201, first.text
    second = client.post(
        APPT_BASE,
        json=_payload(second_barber.barber_id, second_service.service_id,
                      slot_date.isoformat(), "10:00", salon_id=salon.salon_id),
        headers=customer2_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["success"] is True


def test_booking_conflict_exact(client, customer_headers, salon_barber,
                                salon_service, salon,
                                slot_date, slot_availability):
    """B24: exact double-book -> 409, envelope."""
    payload = _slot(slot_date, salon_barber, salon_service, salon)
    assert client.post(APPT_BASE, json=payload, headers=customer_headers).status_code == 201
    res = client.post(APPT_BASE, json=payload, headers=customer_headers)
    assert res.status_code == 409, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


def test_booking_own_view(client, customer_headers, salon_barber,
                          salon_service, salon, slot_date, slot_availability):
    """B25: customer reads own appointment -> 200 + envelope."""
    created = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                          headers=customer_headers)
    assert created.status_code == 201, created.text
    appt_id = created.json()["data"]["appointment_id"]
    res = client.get(f"{APPT_BASE}/{appt_id}", headers=customer_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["appointment_id"] == appt_id


def test_booking_other_customer_view_forbidden(
    client, customer_headers, customer2_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """B26: customer cannot read another customer's appointment -> 403."""
    created = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                          headers=customer_headers)
    assert created.status_code == 201, created.text
    appt_id = created.json()["data"]["appointment_id"]
    res = client.get(f"{APPT_BASE}/{appt_id}", headers=customer2_headers)
    assert res.status_code == 403, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


# ---------------------------------------------------------------------------
# RESCHEDULE (7): PUT {appointment_date?, start_time?} (end derived)
# ---------------------------------------------------------------------------

def _book_id(client, headers, payload):
    res = client.post(APPT_BASE, json=payload, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["data"]["appointment_id"]


def _move(date_str, start):
    return {"appointment_date": date_str, "start_time": start}


def test_reschedule_valid(client, customer_headers, salon_barber,
                          salon_service, salon, slot_date, slot_availability):
    """R1: move to a free slot -> 200, derived end_time updated."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "11:00"),
                     headers=customer_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["start_time"][:5] == "11:00"
    assert body["data"]["end_time"][:5] == "11:30"


def test_reschedule_unavailable(client, customer_headers, db_session,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """R2: move into a window flagged unavailable -> 400."""
    from app.models.availability import BarberAvailability as _Avail

    bare_date = slot_date + _timedelta(days=1)
    db_session.add(_Avail(barber_id=salon_barber.barber_id, date=bare_date,
                          start_time=_time(9, 0), end_time=_time(18, 0),
                          status="unavailable"))
    db_session.commit()
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(bare_date.isoformat(), "10:00"),
                     headers=customer_headers)
    assert res.status_code == 400, res.text
    assert res.json()["success"] is False


def test_reschedule_conflict(client, customer_headers, customer2_headers,
                             salon_barber, salon_service, second_service,
                             salon, slot_date, slot_availability):
    """R3: move onto another booking's slot -> 409."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    other = _payload(salon_barber.barber_id, second_service.service_id,
                     slot_date.isoformat(), "11:00", salon_id=salon.salon_id)
    assert client.post(APPT_BASE, json=other, headers=customer2_headers).status_code == 201
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "11:00"),
                     headers=customer_headers)
    assert res.status_code == 409, res.text
    assert res.json()["success"] is False


def test_reschedule_outside_hours(client, customer_headers, salon_barber,
                                  salon_service, salon, slot_date, slot_availability):
    """R4: move outside salon hours -> 400."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "07:00"),
                     headers=customer_headers)
    assert res.status_code == 400, res.text
    assert res.json()["success"] is False


def test_reschedule_other_customer_forbidden(client, customer_headers,
                                             customer2_headers, salon_barber,
                                             salon_service, salon,
                                             slot_date, slot_availability):
    """R5: rescheduling someone else's appointment -> 403."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "11:00"),
                     headers=customer2_headers)
    assert res.status_code == 403, res.text
    assert res.json()["success"] is False


def test_reschedule_completed_immutable(client, customer_headers, admin_headers,
                                        salon_barber, salon_service, salon,
                                        slot_date, slot_availability):
    """R6: completed appointment cannot be rescheduled -> 400."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    done = client.put(f"{APPT_BASE}/{appt_id}", json={"status": "completed"},
                      headers=admin_headers)
    assert done.status_code == 200, done.text
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "11:00"),
                     headers=admin_headers)
    assert res.status_code == 400, res.text
    assert res.json()["success"] is False


def test_reschedule_cancelled_immutable(client, customer_headers, salon_barber,
                                        salon_service, salon,
                                        slot_date, slot_availability):
    """R7: cancelled appointment cannot be rescheduled -> 400."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    cancelled = client.put(f"{APPT_BASE}/{appt_id}", json={"status": "cancelled"},
                           headers=customer_headers)
    assert cancelled.status_code == 200, cancelled.text
    res = client.put(f"{APPT_BASE}/{appt_id}", json=_move(slot_date.isoformat(), "11:00"),
                     headers=customer_headers)
    assert res.status_code == 400, res.text
    assert res.json()["success"] is False


# ---------------------------------------------------------------------------
# HISTORY (5)
# ---------------------------------------------------------------------------

def _history(db_session, appt_id):
    from app.models.status_history import AppointmentStatusHistory as _H

    return (db_session.query(_H)
            .filter(_H.appointment_id == appt_id)
            .order_by(_H.history_id.asc()).all())


def test_history_written_on_create(client, customer_headers, db_session,
                                   salon_barber, salon_service, salon,
                                   slot_date, slot_availability):
    """H1: booking writes a (None -> booked) history row."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    rows = _history(db_session, appt_id)
    assert len(rows) >= 1
    assert rows[0].old_status is None
    assert rows[0].new_status == "booked"


def test_history_appended_on_cancel(client, customer_headers, db_session,
                                    salon_barber, salon_service, salon,
                                    slot_date, slot_availability):
    """H2: cancel appends a (booked -> cancelled) history row."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    res = client.put(f"{APPT_BASE}/{appt_id}", json={"status": "cancelled"},
                     headers=customer_headers)
    assert res.status_code == 200, res.text
    rows = _history(db_session, appt_id)
    assert len(rows) >= 2
    assert rows[-1].old_status == "booked"
    assert rows[-1].new_status == "cancelled"


def test_history_invalid_transition_rejected(client, customer_headers,
                                             admin_headers, salon_barber,
                                             salon_service, salon,
                                             slot_date, slot_availability):
    """H3: cancelled -> completed is an invalid transition -> 400."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    assert client.put(f"{APPT_BASE}/{appt_id}", json={"status": "cancelled"},
                      headers=customer_headers).status_code == 200
    res = client.put(f"{APPT_BASE}/{appt_id}", json={"status": "completed"},
                     headers=admin_headers)
    assert res.status_code == 400, res.text
    assert res.json()["success"] is False


def test_history_fk_to_appointment(db_session, customer_user, salon_barber,
                                   salon_service, slot_date):
    """H4: history row FK-targets appointments.appointment_id."""
    from app.models.appointment import Appointment as _A
    from app.models.status_history import AppointmentStatusHistory as _H

    appt = _A(customer_id=customer_user.user_id, barber_id=salon_barber.barber_id,
              service_id=salon_service.service_id, appointment_date=slot_date,
              start_time=_time(10, 0), end_time=_time(10, 30), status="booked")
    db_session.add(appt)
    db_session.flush()
    row = _H(appointment_id=appt.appointment_id, old_status=None, new_status="booked")
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.history_id is not None
    assert row.appointment_id == appt.appointment_id
    fks = [str(fk.target_fullname) for fk in _H.__table__.foreign_keys]
    assert "appointments.appointment_id" in fks


def test_history_no_duplicates(client, customer_headers, db_session,
                               salon_barber, salon_service, salon,
                               slot_date, slot_availability):
    """H5: book + cancel yields exactly 2 rows, no duplicate transitions."""
    appt_id = _book_id(client, customer_headers,
                       _slot(slot_date, salon_barber, salon_service, salon))
    assert client.put(f"{APPT_BASE}/{appt_id}", json={"status": "cancelled"},
                      headers=customer_headers).status_code == 200
    rows = _history(db_session, appt_id)
    assert len(rows) == 2
    assert len({(r.old_status, r.new_status) for r in rows}) == 2


# ---------------------------------------------------------------------------
# TRANSACTION (1)
# ---------------------------------------------------------------------------

def test_failed_booking_leaves_no_partial_rows(client, customer_headers, db_session,
                                               salon_barber, salon_service, salon,
                                               slot_date, slot_availability):
    """T1: 409/404 bookings create no appointment, queue, or history rows."""
    from app.models.appointment import Appointment as _A
    from app.models.queue import Queue as _Q
    from app.models.status_history import AppointmentStatusHistory as _H

    def counts():
        return (db_session.query(_A).count(), db_session.query(_Q).count(),
                db_session.query(_H).count())

    assert client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                       headers=customer_headers).status_code == 201
    before = counts()
    assert before[0] >= 1 and before[1] >= 1

    conflict = client.post(APPT_BASE, json=_slot(slot_date, salon_barber, salon_service, salon),
                           headers=customer_headers)
    assert conflict.status_code == 409, conflict.text

    missing = client.post(
        APPT_BASE,
        json=_payload(999999, salon_service.service_id, slot_date.isoformat(),
                      "11:00", salon_id=salon.salon_id),
        headers=customer_headers,
    )
    assert missing.status_code == 404, missing.text

    assert counts() == before
