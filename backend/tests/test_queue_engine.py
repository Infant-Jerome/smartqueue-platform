"""Phase 4 queue-engine tests (Q3-Tests scope, tests only).

Contract under test (Q1-Engine + Q2-Routes, Phase 4):
  Booking (POST /api/v1/appointments -> 201) derives one Queue row
  (waiting, per-day queue_position, salon/barber links).
  Queue ops (uniform envelope {success, message, data} + exact codes):
    POST /api/v1/queue/serve-next {barber_id, salon_id?} -> 200 (first
      waiting by position; 409 one-active guard; 404 empty/unknown barber;
      403 customer / non-owner barber; 422 missing barber_id)
    POST /api/v1/queue/{id}/serve    waiting -> serving (appt in_progress)
    POST /api/v1/queue/{id}/complete serving -> completed (400 waiting
      direct; 409 terminal/serve-after-complete)
    POST /api/v1/queue/{id}/skip     waiting -> no_show (409 otherwise)
    DELETE /api/v1/appointments/{id} cancel syncs queue -> cancelled
    GET  /api/v1/queue/current       active serving row (200 + null empty)
    GET  /api/v1/queue/my-position   people_ahead (same date + same barber,
      waiting, smaller position) + wait = ahead-durations + serving
      remainder (DB service durations only)

Coverage: CREATION 7, SERVE-NEXT 14, COMPLETE 7, SKIP 7, CANCEL 5, WAIT 6.
Barber_id+date scoped bookings with the availability fixtures.
Isolated in-memory SQLite only (conftest); never touches smartqueue.db.
"""

from app.models.appointment import Appointment as _Appointment
from app.models.queue import Queue as _Queue
from app.models.service import Service as _Service
from app.models.status_history import AppointmentStatusHistory as _History
from app.models.user import User as _User
from app.core.security import hash_password as _hash_password

APPT_BASE = "/api/v1/appointments"
QUEUE_BASE = "/api/v1/queue"

_THIRD_N = {"n": 0}


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


def _queues(db_session):
    return (
        db_session.query(_Queue).order_by(_Queue.queue_position.asc()).all()
    )


def _history(db_session, appt_id):
    return (
        db_session.query(_History)
        .filter(_History.appointment_id == appt_id)
        .order_by(_History.history_id.asc())
        .all()
    )


def _counts(db_session):
    return (
        db_session.query(_Queue).count(),
        db_session.query(_Appointment).count(),
        db_session.query(_History).count(),
    )


def _svc45(db_session, salon, name="Wait45 Cut"):
    row = _Service(
        service_name=name,
        description="45 minute service for wait-math tests",
        duration_minutes=45,
        price=400.00,
        status="active",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _third_headers(client, db_session):
    """A third isolated customer (fresh DB per test, so the email is free)."""
    _THIRD_N["n"] += 1
    user = _User(
        name="Customer3",
        email="customer3@test.com",
        password_hash=_hash_password("customer3pass"),
        phone="1234567890",
        role="customer",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer3@test.com", "password": "customer3pass"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["data"]["access_token"]}


def _trio(client, c1h, c2h, c3h, barber, svc30, svc45, salon, slot_date):
    """A(30) + B(45) ahead of C(30): sequential, non-overlapping slots."""
    day = slot_date.isoformat()
    a = _book(client, c1h, barber.barber_id, svc30.service_id, day, "10:00", salon.salon_id)
    b = _book(client, c2h, barber.barber_id, svc45.service_id, day, "10:30", salon.salon_id)
    c = _book(client, c3h, barber.barber_id, svc30.service_id, day, "11:15", salon.salon_id)
    return a, b, c


def _qid(entry):
    return entry["queue_id"]


# ---------------------------------------------------------------------------
# CREATION (7): booking derives exactly one correct waiting queue row
# ---------------------------------------------------------------------------


def test_creation_one_queue_row(client, customer_headers, db_session,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """C1: one booking creates exactly one queue row."""
    assert db_session.query(_Queue).count() == 0
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    assert db_session.query(_Queue).count() == 1


def test_creation_starts_waiting(client, customer_headers, admin_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """C2: the derived row starts in waiting status (API + DB)."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    assert row.status == "waiting"
    res = client.get(QUEUE_BASE, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"][0]["status"] == "waiting"


def test_creation_valid_position(client, customer_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """C3: first booking of the day gets a valid position (1)."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    assert data.get("queue_position") == 1
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    assert isinstance(row.queue_position, int) and row.queue_position >= 1
    assert row.queue_position == 1


def test_creation_correct_appointment(client, customer_headers, customer_user,
                                      db_session, salon_barber, salon_service, salon,
                                      slot_date, slot_availability):
    """C4: queue row links the correct appointment/customer/service."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    assert row.appointment_id == data["appointment_id"]
    appt = db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one()
    assert appt.customer_id == customer_user.user_id
    assert appt.service_id == salon_service.service_id
    assert appt.queue.queue_id == row.queue_id


def test_creation_correct_salon_barber(client, customer_headers, db_session,
                                       salon_barber, salon_service, salon,
                                       slot_date, slot_availability):
    """C5: queue row carries the correct salon_id/barber_id."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    assert row.barber_id == salon_barber.barber_id
    assert row.salon_id == salon.salon_id


def test_creation_no_dupes(client, customer_headers, customer2_headers, db_session,
                           salon_barber, salon_service, salon,
                           slot_date, slot_availability):
    """C6: two bookings -> two rows (distinct appointments); a 409 overlap
    writes no extra queue row."""
    day = slot_date.isoformat()
    a = _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, day, "10:00", salon.salon_id)
    b = _book(client, customer2_headers, salon_barber.barber_id,
              salon_service.service_id, day, "10:30", salon.salon_id)
    assert a["appointment_id"] != b["appointment_id"]
    assert db_session.query(_Queue).count() == 2
    clash = client.post(APPT_BASE, json={
        "barber_id": salon_barber.barber_id, "service_id": salon_service.service_id,
        "appointment_date": day, "start_time": "10:15", "salon_id": salon.salon_id,
    }, headers=customer_headers)
    assert clash.status_code == 409, clash.text
    _envelope(clash.json())
    assert db_session.query(_Queue).count() == 2


def test_creation_positions_increment(client, customer_headers, customer2_headers,
                                      db_session, salon_barber, salon_service, salon,
                                      slot_date, slot_availability):
    """C7: per-day positions increment 1, 2, 3 for sequential bookings."""
    day = slot_date.isoformat()
    h3 = _third_headers(client, db_session)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    _book(client, h3, salon_barber.barber_id,
          salon_service.service_id, day, "11:00", salon.salon_id)
    assert [q.queue_position for q in _queues(db_session)] == [1, 2, 3]


# ---------------------------------------------------------------------------
# SERVE-NEXT (14)
# ---------------------------------------------------------------------------


def test_servenext_picks_first_waiting(client, customer_headers, customer2_headers,
                                       admin_headers, db_session, salon_barber,
                                       salon_service, salon, slot_date, slot_availability):
    """S1: serve-next serves the smallest waiting position (1)."""
    day = slot_date.isoformat()
    h3 = _third_headers(client, db_session)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    _book(client, h3, salon_barber.barber_id,
          salon_service.service_id, day, "11:00", salon.salon_id)
    res = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["queue_position"] == 1
    assert body["data"]["status"] == "serving"
    assert body["data"]["barber_id"] == salon_barber.barber_id


def test_servenext_ordering_by_position(client, customer_headers, customer2_headers,
                                        admin_headers, db_session, salon_barber,
                                        salon_service, salon, slot_date, slot_availability):
    """S2: serve -> complete -> serve-next follows position order (1, then 2)."""
    day = slot_date.isoformat()
    h3 = _third_headers(client, db_session)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    _book(client, h3, salon_barber.barber_id,
          salon_service.service_id, day, "11:00", salon.salon_id)
    first = client.post(QUEUE_BASE + "/serve-next",
                        json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["queue_position"] == 1
    done = client.post(QUEUE_BASE + "/" + str(_qid(first.json()["data"])) + "/complete",
                       headers=admin_headers)
    assert done.status_code == 200, done.text
    second = client.post(QUEUE_BASE + "/serve-next",
                         json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["queue_position"] == 2


def test_serve_syncs_appointment(client, customer_headers, customer2_headers,
                                 admin_headers, db_session, salon_barber,
                                 salon_service, salon, slot_date, slot_availability):
    """S3: waiting -> serving mirrors the appointment to in_progress."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    appt_id = _queues(db_session)[0].appointment_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["data"]["status"] == "serving"
    db_session.expire_all()
    appt = db_session.query(_Appointment).filter(
        _Appointment.appointment_id == appt_id).one()
    assert appt.status == "in_progress"


def test_serve_writes_history(client, customer_headers, admin_headers, db_session,
                              salon_barber, salon_service, salon,
                              slot_date, slot_availability):
    """S4: serve appends a (booked -> in_progress) history row."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    assert [(h.old_status, h.new_status) for h in _history(db_session, data["appointment_id"])] == [(None, "booked")]
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=admin_headers).status_code == 200
    rows = _history(db_session, data["appointment_id"])
    assert len(rows) == 2
    assert (rows[-1].old_status, rows[-1].new_status) == ("booked", "in_progress")


def test_current_reflects_active(client, customer_headers, customer2_headers,
                                 admin_headers, db_session, salon_barber,
                                 salon_service, salon, slot_date, slot_availability):
    """S5: /current returns the serving entry; empty after complete (200+null)."""
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    served = client.post(QUEUE_BASE + "/serve-next",
                         json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert served.status_code == 200, served.text
    cur = client.get(QUEUE_BASE + "/current",
                     params={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert cur.status_code == 200, cur.text
    _envelope(cur.json())
    assert cur.json()["data"]["queue_id"] == _qid(served.json()["data"])
    assert cur.json()["data"]["status"] == "serving"
    assert client.post(
        QUEUE_BASE + "/" + str(_qid(served.json()["data"])) + "/complete",
        headers=admin_headers).status_code == 200
    empty = client.get(QUEUE_BASE + "/current",
                       params={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] is None


def test_serve_one_active_guard(client, customer_headers, customer2_headers,
                                admin_headers, db_session, salon_barber,
                                salon_service, salon, slot_date, slot_availability):
    """S6: serving a second entry while one is active -> 409."""
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/serve",
                       headers=admin_headers).status_code == 200
    res = client.post(QUEUE_BASE + "/" + str(rows[1].queue_id) + "/serve",
                      headers=admin_headers)
    assert res.status_code == 409, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_servenext_guard_while_active(client, customer_headers, customer2_headers,
                                      admin_headers, db_session, salon_barber,
                                      salon_service, salon, slot_date, slot_availability):
    """S7: serve-next while a serving row is active -> 409."""
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    assert client.post(QUEUE_BASE + "/serve-next",
                       json={"barber_id": salon_barber.barber_id},
                       headers=admin_headers).status_code == 200
    res = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert res.status_code == 409, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_servenext_empty_404(client, admin_headers, db_session,
                             salon_barber, slot_date):
    """S8: serve-next with no waiting rows -> 404; unknown entry -> 404."""
    res = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert res.status_code == 404, res.text
    _envelope(res.json())
    assert res.json()["success"] is False
    missing = client.post(QUEUE_BASE + "/999999/serve", headers=admin_headers)
    assert missing.status_code == 404, missing.text
    _envelope(missing.json())
    assert missing.json()["success"] is False


def test_serve_customer_forbidden(client, customer_headers, db_session,
                                  salon_barber, salon_service, salon,
                                  slot_date, slot_availability):
    """S9: customers cannot serve (403 + envelope)."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=customer_headers)
    assert res.status_code == 403, res.text
    _envelope(res.json())
    assert res.json()["success"] is False
    nxt = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=customer_headers)
    assert nxt.status_code == 403, nxt.text
    assert nxt.json()["success"] is False


def test_barber_own_allowed(client, customer_headers, barber_headers, db_session,
                            barber_profile, salon_service, salon, slot_date):
    """S10: the assigned barber (Barber.user_id link) may serve own entries."""
    data = _book(client, customer_headers, barber_profile.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    res = client.post(QUEUE_BASE + "/" + str(row.queue_id) + "/serve", headers=barber_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert res.json()["data"]["status"] == "serving"


def test_barber_other_forbidden(client, customer_headers, barber_headers, db_session,
                                salon_barber, other_barber_profile, salon_service,
                                salon, slot_date, slot_availability):
    """S11: a barber cannot serve another barber's entries (403)."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=barber_headers)
    assert res.status_code == 403, res.text
    _envelope(res.json())
    assert res.json()["success"] is False
    nxt = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=barber_headers)
    assert nxt.status_code == 403, nxt.text
    assert nxt.json()["success"] is False


def test_staff_admin_allowed(client, customer_headers, customer2_headers,
                             admin_headers, receptionist_headers, db_session,
                             salon_barber, salon_service, salon,
                             slot_date, slot_availability):
    """S12: staff (receptionist) and admin may run serve-next."""
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    first = client.post(QUEUE_BASE + "/serve-next",
                        json={"barber_id": salon_barber.barber_id},
                        headers=receptionist_headers)
    assert first.status_code == 200, first.text
    assert first.json()["success"] is True
    assert client.post(QUEUE_BASE + "/" + str(_qid(first.json()["data"])) + "/complete",
                       headers=admin_headers).status_code == 200
    second = client.post(QUEUE_BASE + "/serve-next",
                         json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert second.status_code == 200, second.text
    assert second.json()["success"] is True


def test_servenext_unknown_barber_404(client, admin_headers):
    """S13: serve-next for an unknown barber -> 404 + envelope."""
    res = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": 999999}, headers=admin_headers)
    assert res.status_code == 404, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_failed_serve_atomicity(client, customer_headers, admin_headers, db_session,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """S14: rejected serves (404/400) write no queue/appointment/history rows
    and leave statuses untouched (single-transaction rollback)."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    before = _counts(db_session)
    db_session.expire_all()
    status_before = db_session.query(_Queue).filter(
        _Queue.queue_id == qid).one().status
    assert client.post(QUEUE_BASE + "/999999/serve", headers=admin_headers).status_code == 404
    repeat = client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=admin_headers)
    assert repeat.status_code == 400, repeat.text
    db_session.expire_all()
    assert _counts(db_session) == before
    assert db_session.query(_Queue).filter(_Queue.queue_id == qid).one().status == status_before
    assert db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one().status == "in_progress"


# ---------------------------------------------------------------------------
# COMPLETE (7)
# ---------------------------------------------------------------------------


def test_complete_serving(client, customer_headers, admin_headers, db_session,
                          salon_barber, salon_service, salon,
                          slot_date, slot_availability):
    """P1: serving -> completed (200 + envelope)."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/complete", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["status"] == "completed"


def test_complete_waiting_direct_rejected(client, customer_headers, admin_headers,
                                          db_session, salon_barber, salon_service, salon,
                                          slot_date, slot_availability):
    """P2: completing a waiting entry directly -> 400."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/complete", headers=admin_headers)
    assert res.status_code == 400, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_complete_twice_rejected(client, customer_headers, admin_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """P3: completing an already-completed entry -> 400/409 (terminal)."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/complete",
                       headers=admin_headers).status_code == 200
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/complete", headers=admin_headers)
    assert res.status_code in (400, 409), res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_complete_syncs_appointment(client, customer_headers, admin_headers, db_session,
                                    salon_barber, salon_service, salon,
                                    slot_date, slot_availability):
    """P4: complete mirrors the appointment to completed."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/complete",
                       headers=admin_headers).status_code == 200
    db_session.expire_all()
    appt = db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one()
    assert appt.status == "completed"


def test_complete_writes_history(client, customer_headers, admin_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """P5: complete appends (in_progress -> completed) history."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/complete",
                       headers=admin_headers).status_code == 200
    rows = _history(db_session, data["appointment_id"])
    assert [(h.old_status, h.new_status) for h in rows] == [
        (None, "booked"), ("booked", "in_progress"), ("in_progress", "completed")]


def test_complete_updates_estimates(client, customer_headers, customer2_headers,
                                    admin_headers, db_session, salon_barber,
                                    salon_service, salon, slot_date, slot_availability):
    """P6: completing the head recomputes stored estimates for the scope
    (B waits 0, C waits B's 45)."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          svc45.service_id, day, "10:30", salon.salon_id)
    _book(client, h3, salon_barber.barber_id,
          salon_service.service_id, day, "11:15", salon.salon_id)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/complete",
                       headers=admin_headers).status_code == 200
    db_session.expire_all()
    stored = {q.queue_position: q.estimated_wait_minutes for q in _queues(db_session)}
    assert stored[2] == 0
    assert stored[3] == 45


def test_complete_unauthorized(client, customer_headers, db_session,
                               salon_barber, salon_service, salon,
                               slot_date, slot_availability):
    """P7: customers cannot complete (403); anonymous -> 401."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/complete", headers=customer_headers)
    assert res.status_code == 403, res.text
    _envelope(res.json())
    assert res.json()["success"] is False
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/complete").status_code == 401


# ---------------------------------------------------------------------------
# SKIP (7): waiting -> no_show
# ---------------------------------------------------------------------------


def test_skip_waiting(client, customer_headers, admin_headers, db_session,
                      salon_barber, salon_service, salon,
                      slot_date, slot_availability):
    """K1: waiting -> no_show (200 + envelope)."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/skip", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["status"] == "no_show"


def test_skip_syncs_appointment(client, customer_headers, admin_headers, db_session,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """K2: skip mirrors the appointment to no_show."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/skip",
                       headers=admin_headers).status_code == 200
    db_session.expire_all()
    appt = db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one()
    assert appt.status == "no_show"


def test_skip_writes_history(client, customer_headers, admin_headers, db_session,
                             salon_barber, salon_service, salon,
                             slot_date, slot_availability):
    """K3: skip appends a (* -> no_show) history row."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/skip",
                       headers=admin_headers).status_code == 200
    rows = _history(db_session, data["appointment_id"])
    assert len(rows) == 2
    assert rows[-1].new_status == "no_show"


def test_skip_removed_from_waiting(client, customer_headers, customer2_headers,
                                   admin_headers, db_session, salon_barber,
                                   salon_service, salon, slot_date, slot_availability):
    """K4: skipped rows leave the waiting list; serve-next passes them over."""
    day = slot_date.isoformat()
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, customer2_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:30", salon.salon_id)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/skip",
                       headers=admin_headers).status_code == 200
    waiting = client.get(QUEUE_BASE, headers=admin_headers).json()["data"]
    assert [e["queue_position"] for e in waiting] == [2]
    nxt = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id}, headers=admin_headers)
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["data"]["queue_position"] == 2


def test_skip_completed_rejected(client, customer_headers, admin_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """K5: skipping a completed entry -> 400/409."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/complete",
                       headers=admin_headers).status_code == 200
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/skip", headers=admin_headers)
    assert res.status_code in (400, 409), res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_skip_cancelled_rejected(client, customer_headers, admin_headers, db_session,
                                 salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """K6: skipping a cancelled entry -> 400/409."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    cancel = client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                           headers=customer_headers)
    assert cancel.status_code == 200, cancel.text
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/skip", headers=admin_headers)
    assert res.status_code in (400, 409), res.text
    _envelope(res.json())
    assert res.json()["success"] is False


def test_skip_unauthorized(client, customer_headers, db_session,
                           salon_barber, salon_service, salon,
                           slot_date, slot_availability):
    """K7: customers cannot skip (403); anonymous -> 401."""
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    qid = _queues(db_session)[0].queue_id
    res = client.post(QUEUE_BASE + "/" + str(qid) + "/skip", headers=customer_headers)
    assert res.status_code == 403, res.text
    _envelope(res.json())
    assert res.json()["success"] is False
    assert client.post(QUEUE_BASE + "/" + str(qid) + "/skip").status_code == 401


# ---------------------------------------------------------------------------
# CANCEL (5): appointment cancel syncs the queue row to cancelled
# ---------------------------------------------------------------------------


def test_cancel_syncs_queue(client, customer_headers, db_session,
                            salon_barber, salon_service, salon,
                            slot_date, slot_availability):
    """X1: owner DELETE cancels the appointment and syncs queue->cancelled."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    res = client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                        headers=customer_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert res.json()["success"] is True
    db_session.expire_all()
    appt = db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one()
    assert appt.status == "cancelled"
    row = db_session.query(_Queue).filter(
        _Queue.appointment_id == data["appointment_id"]).one()
    assert row.status == "cancelled"


def test_cancel_not_served(client, customer_headers, admin_headers, db_session,
                           salon_barber, salon_service, salon,
                           slot_date, slot_availability):
    """X2: a cancelled entry can no longer be served or skipped (409)."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    assert client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                         headers=customer_headers).status_code == 200
    qid = _queues(db_session)[0].queue_id
    serve = client.post(QUEUE_BASE + "/" + str(qid) + "/serve", headers=admin_headers)
    assert serve.status_code == 409, serve.text
    skip = client.post(QUEUE_BASE + "/" + str(qid) + "/skip", headers=admin_headers)
    assert skip.status_code == 409, skip.text


def test_cancel_excluded_from_estimate(client, customer_headers, customer2_headers,
                                       admin_headers, db_session, salon_barber,
                                       salon_service, salon, slot_date, slot_availability):
    """X3: cancelled rows are excluded from people-ahead and wait estimates."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    a, b, c = _trio(client, customer_headers, customer2_headers, h3,
                    salon_barber, salon_service, svc45, salon, slot_date)
    assert client.delete(APPT_BASE + "/" + str(b["appointment_id"]),
                         headers=customer2_headers).status_code == 200
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30
    assert a["appointment_id"] != b["appointment_id"] != c["appointment_id"]


def test_cancel_no_dupe_history(client, customer_headers, db_session,
                                salon_barber, salon_service, salon,
                                slot_date, slot_availability):
    """X4: book + cancel yields exactly 2 history rows; recancel adds none."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    assert client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                         headers=customer_headers).status_code == 200
    rows = _history(db_session, data["appointment_id"])
    assert [(h.old_status, h.new_status) for h in rows] == [
        (None, "booked"), ("booked", "cancelled")]
    assert client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                         headers=customer_headers).status_code == 200
    assert len(_history(db_session, data["appointment_id"])) == 2


def test_cancel_ownership(client, customer_headers, customer2_headers, db_session,
                          salon_barber, salon_service, salon,
                          slot_date, slot_availability):
    """X5: only the owner (or staff/admin) may cancel: other customer -> 403,
    anonymous -> 401."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00", salon.salon_id)
    other = client.delete(APPT_BASE + "/" + str(data["appointment_id"]),
                          headers=customer2_headers)
    assert other.status_code == 403, other.text
    _envelope(other.json())
    assert other.json()["success"] is False
    assert client.delete(APPT_BASE + "/" + str(data["appointment_id"])).status_code == 401
    db_session.expire_all()
    assert db_session.query(_Appointment).filter(
        _Appointment.appointment_id == data["appointment_id"]).one().status == "booked"


# ---------------------------------------------------------------------------
# WAIT (6): my-position estimates from DB service durations
# ---------------------------------------------------------------------------


def test_wait_base_estimate(client, customer_headers, customer2_headers,
                            db_session, salon_barber, salon_service, salon,
                            slot_date, slot_availability):
    """W1: A(30) + B(45) ahead of C => people_ahead 2, wait ~75."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    _trio(client, customer_headers, customer2_headers, h3,
          salon_barber, salon_service, svc45, salon, slot_date)
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3)
    assert pos.status_code == 200, pos.text
    data = pos.json()["data"]
    _envelope(pos.json())
    assert data["has_queue"] is True
    assert data["queue_position"] == 3
    assert data["people_ahead"] == 2
    assert data["estimated_wait_minutes"] == 75


def test_wait_excludes_cancelled(client, customer_headers, customer2_headers,
                                 db_session, salon_barber, salon_service, salon,
                                 slot_date, slot_availability):
    """W2: cancelled rows are excluded (B cancelled => C waits only A=30)."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    a, b, c = _trio(client, customer_headers, customer2_headers, h3,
                    salon_barber, salon_service, svc45, salon, slot_date)
    assert a["queue_position"] == 1 and b["queue_position"] == 2 and c["queue_position"] == 3
    assert client.delete(APPT_BASE + "/" + str(b["appointment_id"]),
                         headers=customer2_headers).status_code == 200
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30


def test_wait_excludes_no_show(client, customer_headers, customer2_headers,
                               admin_headers, db_session, salon_barber,
                               salon_service, salon, slot_date, slot_availability):
    """W3: no_show rows are excluded (B skipped => C waits only A=30)."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    _trio(client, customer_headers, customer2_headers, h3,
          salon_barber, salon_service, svc45, salon, slot_date)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[1].queue_id) + "/skip",
                       headers=admin_headers).status_code == 200
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 30


def test_wait_excludes_completed(client, customer_headers, customer2_headers,
                                 admin_headers, db_session, salon_barber,
                                 salon_service, salon, slot_date, slot_availability):
    """W4: completed rows are excluded (A done => C waits only B=45)."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    _trio(client, customer_headers, customer2_headers, h3,
          salon_barber, salon_service, svc45, salon, slot_date)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/serve",
                       headers=admin_headers).status_code == 200
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/complete",
                       headers=admin_headers).status_code == 200
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert pos["people_ahead"] == 1
    assert pos["estimated_wait_minutes"] == 45


def test_wait_same_barber_only(client, customer_headers,
                               db_session, salon_barber, second_barber,
                               salon_service, salon, slot_date, slot_availability):
    """W5: rows for another barber (same date) do not count as ahead."""
    day = slot_date.isoformat()
    h3 = _third_headers(client, db_session)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    _book(client, h3, second_barber.barber_id,
          salon_service.service_id, day, "10:00", salon.salon_id)
    pos = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert pos["has_queue"] is True
    assert pos["people_ahead"] == 0
    assert pos["estimated_wait_minutes"] == 0
    pos1 = client.get(QUEUE_BASE + "/my-position", headers=customer_headers).json()["data"]
    assert pos1["people_ahead"] == 0
    assert pos1["estimated_wait_minutes"] == 0


def test_wait_active_handled(client, customer_headers, customer2_headers,
                             admin_headers, db_session, salon_barber,
                             salon_service, salon, slot_date, slot_availability):
    """W6: serving remainder counts (A=30 serving): B waits 30 with
    currently_serving=1; C waits B(45)+serving(30)=75."""
    svc45 = _svc45(db_session, salon)
    h3 = _third_headers(client, db_session)
    _trio(client, customer_headers, customer2_headers, h3,
          salon_barber, salon_service, svc45, salon, slot_date)
    rows = _queues(db_session)
    assert client.post(QUEUE_BASE + "/" + str(rows[0].queue_id) + "/serve",
                       headers=admin_headers).status_code == 200
    mid = client.get(QUEUE_BASE + "/my-position", headers=customer2_headers).json()["data"]
    assert mid["people_ahead"] == 0
    assert mid["estimated_wait_minutes"] == 30
    assert mid["currently_serving"] == 1
    last = client.get(QUEUE_BASE + "/my-position", headers=h3).json()["data"]
    assert last["people_ahead"] == 1
    assert last["estimated_wait_minutes"] == 75
    assert last["currently_serving"] == 1
