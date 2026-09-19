"""Phase 3 availability tests (B4-Tests scope, tests only).

Assumed contract (API agent to implement if missing):
  POST   /api/v1/availability            {barber_id, date, start_time, end_time, status?} -> 201
  GET    /api/v1/availability?barber_id= -> 200 (list; barbers see own only)
  GET    /api/v1/availability/{id}       -> 200
  PUT    /api/v1/availability/{id}       -> 200 (admin; barber own only)
  DELETE /api/v1/availability/{id}       -> 200 (admin)
RBAC: admin manages all; barber reads/owns own; customer gets 403 on write.
Envelope {success, message, data} on every response.
Isolated in-memory SQLite only.
"""

AVAIL_BASE = "/api/v1/availability"


def _envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}, body
    assert isinstance(body["success"], bool), body
    assert isinstance(body["message"], str), body


def _payload(barber_id, date_str, start="09:00", end="17:00"):
    return {
        "barber_id": barber_id,
        "date": date_str,
        "start_time": start,
        "end_time": end,
        "status": "available",
    }


def test_availability_admin_create_valid(client, admin_headers, salon_barber, slot_date):
    """AVAIL 1: admin creates a valid window -> 201 + envelope, correct barber."""
    res = client.post(
        AVAIL_BASE,
        json=_payload(salon_barber.barber_id, slot_date.isoformat()),
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    assert body["data"]["barber_id"] == salon_barber.barber_id


def test_availability_start_after_end_rejected(
    client, admin_headers, salon_barber, slot_date
):
    """AVAIL 2: start_time >= end_time rejected -> 400/422, success False."""
    res = client.post(
        AVAIL_BASE,
        json=_payload(salon_barber.barber_id, slot_date.isoformat(), start="17:00", end="09:00"),
        headers=admin_headers,
    )
    assert res.status_code in (400, 422), res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


def test_availability_customer_create_forbidden(
    client, customer_headers, salon_barber, slot_date
):
    """AVAIL 3: customer cannot create availability -> 403."""
    res = client.post(
        AVAIL_BASE,
        json=_payload(salon_barber.barber_id, slot_date.isoformat()),
        headers=customer_headers,
    )
    assert res.status_code == 403, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


def test_availability_barber_reads_own(
    client, barber_headers, db_session, barber_user, barber_profile, slot_date
):
    """AVAIL 4: barber reads own availability -> 200, only own rows."""
    from app.models.availability import BarberAvailability
    from datetime import time as _time

    db_session.add(
        BarberAvailability(
            barber_id=barber_profile.barber_id,
            date=slot_date,
            start_time=_time(9, 0),
            end_time=_time(17, 0),
            status="available",
        )
    )
    db_session.commit()
    res = client.get(
        AVAIL_BASE,
        params={"barber_id": barber_profile.barber_id},
        headers=barber_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is True
    rows = body["data"] if isinstance(body["data"], list) else body["data"].get("items", [])
    assert len(rows) >= 1
    assert all(r["barber_id"] == barber_profile.barber_id for r in rows)


def test_availability_barber_cannot_modify_other(
    client,
    admin_headers,
    barber_headers,
    other_barber_profile,
    slot_date,
):
    """AVAIL 5: barber cannot modify another barber's window -> 403."""
    created = client.post(
        AVAIL_BASE,
        json=_payload(other_barber_profile.barber_id, slot_date.isoformat()),
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    avail_id = created.json()["data"].get("availability_id", created.json()["data"].get("id"))
    res = client.put(
        f"{AVAIL_BASE}/{avail_id}",
        json={"start_time": "10:00", "end_time": "16:00"},
        headers=barber_headers,
    )
    assert res.status_code == 403, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False


def test_availability_admin_can_manage(client, admin_headers, salon_barber, slot_date):
    """AVAIL 6: admin full manage (create/update/delete) -> 201/200/200."""
    created = client.post(
        AVAIL_BASE,
        json=_payload(salon_barber.barber_id, slot_date.isoformat()),
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    avail_id = created.json()["data"].get("availability_id", created.json()["data"].get("id"))

    updated = client.put(
        f"{AVAIL_BASE}/{avail_id}",
        json={"start_time": "10:00", "end_time": "16:00"},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["success"] is True

    fetched = client.get(f"{AVAIL_BASE}/{avail_id}", headers=admin_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["success"] is True

    deleted = client.delete(f"{AVAIL_BASE}/{avail_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["success"] is True


def test_availability_belongs_to_correct_barber(
    client, admin_headers, salon_barber, slot_date
):
    """AVAIL 7: created window belongs to the requested barber."""
    res = client.post(
        AVAIL_BASE,
        json=_payload(salon_barber.barber_id, slot_date.isoformat()),
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["barber_id"] == salon_barber.barber_id


def test_availability_nonexistent_barber_404(client, admin_headers, slot_date):
    """AVAIL 8: create for nonexistent barber -> 404."""
    res = client.post(
        AVAIL_BASE,
        json=_payload(999999, slot_date.isoformat()),
        headers=admin_headers,
    )
    assert res.status_code == 404, res.text
    body = res.json()
    _envelope(body)
    assert body["success"] is False
