import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, CheckCircle2, Clock, XCircle } from 'lucide-react';
import api from '../services/api';
import Navbar from '../components/Navbar';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';
import Field from '../components/ui/Field';
import Input from '../components/ui/Input';
import PageHeader from '../components/ui/PageHeader';
import { serviceId, serviceName, serviceDuration, barberId, barberStatus } from '../utils/format';
import { LoadingState, ErrorState } from '../components/States';

/** Fallback grid shown only when the barber publishes no availability
 *  windows for the date (backend treats that as openly scheduled).
 *  When windows exist, slots are generated from their bounds instead. */
const FALLBACK_TIMES = ['09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','14:00','14:30','15:00','15:30','16:00','16:30','17:00','17:30','18:00','18:30','19:00'];
const STEP_MINUTES = 30;
/** Appointment statuses that still occupy a slot for the same customer. */
const ACTIVE_STATUSES = new Set(['booked', 'confirmed', 'waiting', 'serving', 'in_progress']);

function toMinutes(t) {
  const [h, m] = String(t).split(':').map(Number);
  return h * 60 + (m || 0);
}

function toHHMM(minutes) {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function nowMinutes() {
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
}

function overlaps(aStart, aEnd, bStart, bEnd) {
  return aStart < bEnd && aEnd > bStart;
}

const STEPS = ['Service', 'Barber', 'Date & Time', 'Confirm'];

function Stepper({ step }) {
  return (
    <ol className="flex items-center gap-2 sm:gap-4 mb-8" aria-label="Booking progress">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = step > n;
        const current = step === n;
        return (
          <li key={label} className="flex items-center gap-2 min-w-0">
            <span
              aria-current={current ? 'step' : undefined}
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium shrink-0 transition-colors duration-[var(--sq-transition-normal)] ${
                done
                  ? 'bg-[var(--sq-success)] text-white'
                  : current
                    ? 'bg-[var(--sq-primary)] text-white'
                    : 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-subtle)]'
              }`}
            >
              {done ? <Check size={16} aria-hidden="true" /> : n}
            </span>
            <span className={`text-sm hidden sm:inline truncate ${current ? 'text-[var(--sq-primary)] font-medium' : done ? 'text-[var(--sq-text)]' : 'text-[var(--sq-text-subtle)]'}`}>
              {label}
            </span>
            {n < STEPS.length && <span className="hidden sm:block w-6 h-px bg-[var(--sq-border)]" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

function SlotButton({ time, state, selected, onSelect, reason }) {
  const base =
    'px-3 py-2.5 rounded-[var(--sq-radius-lg)] text-sm font-medium sq-tnum transition-colors duration-[var(--sq-transition-fast)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] min-h-[2.75rem] inline-flex items-center justify-center gap-1.5';
  if (state === 'selected' || selected) {
    return (
      <button onClick={onSelect} aria-pressed="true" title={time}
        className={`${base} bg-[var(--sq-primary)] text-white shadow-[var(--sq-shadow-md)]`}>
        <Check size={15} aria-hidden="true" />{time}
      </button>
    );
  }
  if (state === 'available') {
    return (
      <button onClick={onSelect} aria-pressed="false" title={`${time} available`}
        className={`${base} bg-[var(--sq-success-soft)] text-[var(--sq-success)] hover:ring-2 hover:ring-[var(--sq-success)]`}>
        <Clock size={14} aria-hidden="true" />{time}
      </button>
    );
  }
  return (
    <button disabled aria-disabled="true" title={reason || `${time} unavailable`}
      className={`${base} bg-[var(--sq-surface-muted)] text-[var(--sq-text-subtle)] cursor-not-allowed line-through decoration-[var(--sq-border)]`}>
      <XCircle size={14} aria-hidden="true" />{time}
    </button>
  );
}

export default function BookAppointment() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [services, setServices] = useState([]);
  const [barbers, setBarbers] = useState([]);
  const [selectedService, setSelectedService] = useState(null);
  const [selectedBarber, setSelectedBarber] = useState(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [windows, setWindows] = useState([]);
  const [ownAppointments, setOwnAppointments] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [confirmation, setConfirmation] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.get('/services'), api.get('/barbers')])
      .then(([sRes, bRes]) => {
        setServices(Array.isArray(sRes.data) ? sRes.data : []);
        setBarbers(Array.isArray(bRes.data) ? bRes.data : []);
      })
      .catch((err) => setLoadError(err.message || 'Failed to load booking data.'))
      .finally(() => setLoading(false));
  }, []);

  const duration = serviceDuration(selectedService) ?? 30;

  /** Refresh availability windows + own bookings whenever the slot inputs change. */
  const refreshSlots = useCallback(async () => {
    if (!selectedBarber || !selectedDate) {
      setWindows([]);
      setOwnAppointments([]);
      return;
    }
    setSlotsLoading(true);
    try {
      const [wRes, aRes] = await Promise.all([
        api.get('/availability', { params: { barber_id: barberId(selectedBarber), date: selectedDate } }),
        api.get('/appointments'),
      ]);
      setWindows(Array.isArray(wRes.data) ? wRes.data.filter((w) => String(w.status || '').toLowerCase() === 'available') : []);
      const mine = Array.isArray(aRes.data) ? aRes.data : [];
      setOwnAppointments(
        mine.filter(
          (a) =>
            String(a.appointment_date).slice(0, 10) === selectedDate &&
            ACTIVE_STATUSES.has(String(a.status || '').toLowerCase())
        )
      );
    } catch {
      // Availability is advisory; booking errors remain authoritative.
      setWindows([]);
      setOwnAppointments([]);
    } finally {
      setSlotsLoading(false);
    }
  }, [selectedBarber, selectedDate]);

  useEffect(() => {
    setSelectedTime('');
    refreshSlots();
  }, [refreshSlots]);

  /** Slots generated from published window bounds; fallback grid when none published. */
  const slots = useMemo(() => {
    const isToday = selectedDate === todayStr();
    const now = nowMinutes();
    const starts = [];
    if (windows.length > 0) {
      for (const w of windows) {
        const from = toMinutes(String(w.start_time).slice(0, 5));
        const to = toMinutes(String(w.end_time).slice(0, 5));
        for (let t = from; t + duration <= to; t += STEP_MINUTES) starts.push(toHHMM(t));
      }
    } else if (selectedDate) {
      starts.push(...FALLBACK_TIMES);
    }
    const unique = [...new Set(starts)].sort();
    return unique.map((t) => {
      const m = toMinutes(t);
      if (isToday && m <= now) return { time: t, state: 'past', reason: 'This time has already passed today' };
      const end = m + duration;
      const clash = ownAppointments.find((a) => {
        const s = toMinutes(String(a.start_time).slice(0, 5));
        const e = a.end_time ? toMinutes(String(a.end_time).slice(0, 5)) : s + duration;
        return overlaps(m, end, s, e);
      });
      if (clash) return { time: t, state: 'unavailable', reason: 'Overlaps one of your existing bookings' };
      return { time: t, state: 'available' };
    });
  }, [windows, ownAppointments, selectedDate, duration]);

  const friendlyError = (err) => {
    const status = err.response?.status;
    if (status === 409) return 'The selected slot is no longer available. Please choose another time.';
    if (status === 404) return 'The selected service or barber was not found. Please refresh and try again.';
    return err.message || 'Booking failed. Please try again.';
  };

  const handleBook = async () => {
    setError('');
    if (!selectedService || !selectedBarber || !selectedDate || !selectedTime) {
      setError('Please complete all booking steps before confirming.');
      return;
    }
    if (selectedDate < todayStr()) {
      setError('The booking date cannot be in the past.');
      return;
    }
    setSubmitting(true);
    try {
      // Backend derives customer from JWT and end_time from service duration.
      // Only the required fields are sent; never customer_id or end_time.
      const res = await api.post('/appointments', {
        barber_id: barberId(selectedBarber),
        service_id: serviceId(selectedService),
        appointment_date: selectedDate,
        start_time: selectedTime,
      });
      setConfirmation(res.data);
    } catch (err) {
      setError(friendlyError(err));
      // Slot may have been taken meanwhile — refresh through the same mechanism.
      refreshSlots();
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <LoadingState message="Loading booking options..." />
      </div>
      </>
    );
  }

  if (loadError) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <ErrorState message={loadError} onRetry={() => window.location.reload()} />
      </div>
      </>
    );
  }

  if (confirmation) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <Card padding="lg" className="text-center">
          <div className="flex justify-center mb-4" aria-hidden="true">
            <span className="flex w-14 h-14 rounded-full bg-[var(--sq-success-soft)] text-[var(--sq-success)] items-center justify-center">
              <CheckCircle2 size={28} />
            </span>
          </div>
          <h1 className="sq-h1">Appointment booked!</h1>
          <p className="text-[var(--sq-text-muted)] mt-2">
            {serviceName(selectedService)} with {selectedBarber?.name} on {selectedDate} at {selectedTime}
          </p>
          {confirmation.queue_position != null && (
            <p className="text-[var(--sq-text)] mt-2">
              Queue position <strong className="sq-tnum">#{confirmation.queue_position}</strong>
              {confirmation.estimated_wait_minutes != null && (
                <> · estimated wait <strong className="sq-tnum">{confirmation.estimated_wait_minutes} min</strong></>
              )}
            </p>
          )}
          <div className="flex gap-3 justify-center mt-6">
            <Button onClick={() => navigate('/queue')}>View Queue</Button>
            <Button tone="secondary" onClick={() => navigate('/appointments')}>My Appointments</Button>
          </div>
        </Card>
      </div>
      </>
    );
  }

  return (
    <><Navbar />
    <div className="max-w-3xl mx-auto px-4 py-8">
      <PageHeader title="Book Appointment" description="Follow the steps to schedule your visit" />
      <Stepper step={step} />

      {error && (
        <div className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{error}</div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          <h2 className="sq-h2">Select a Service</h2>
          {services.length === 0 && <p className="text-[var(--sq-text-muted)]">No services currently available.</p>}
          {services.map((s) => {
            const active = selectedService && serviceId(selectedService) === serviceId(s);
            return (
              <button key={serviceId(s)} onClick={() => { setSelectedService(s); setStep(2); }} aria-pressed={!!active}
                className={`w-full text-left p-4 rounded-[var(--sq-radius-xl)] border-2 transition-colors duration-[var(--sq-transition-normal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] bg-[var(--sq-surface)] ${
                  active ? 'border-[var(--sq-primary)] ring-2 ring-[var(--sq-primary-soft)]' : 'border-[var(--sq-border)] hover:border-[var(--sq-primary)]'
                }`}>
                <div className="flex justify-between items-center gap-3">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-[var(--sq-text)] flex items-center gap-2">
                      {serviceName(s)}
                      {active && <Check size={16} className="text-[var(--sq-primary)]" aria-hidden="true" />}
                    </h3>
                    <p className="text-sm text-[var(--sq-text-muted)]">
                      {serviceDuration(s) != null ? `${serviceDuration(s)} min` : ''}
                      {s.description ? ` · ${s.description}` : ''}
                    </p>
                  </div>
                  <span className="text-[var(--sq-primary)] font-bold sq-tnum shrink-0">₹{s.price}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3">
          <h2 className="sq-h2">Select a Barber</h2>
          {barbers.length === 0 && <p className="text-[var(--sq-text-muted)]">No barbers currently available.</p>}
          {barbers.map((b) => {
            const active = selectedBarber && barberId(selectedBarber) === barberId(b);
            return (
              <button key={barberId(b)} onClick={() => { setSelectedBarber(b); setStep(3); }} aria-pressed={!!active}
                className={`w-full text-left p-4 rounded-[var(--sq-radius-xl)] border-2 transition-colors duration-[var(--sq-transition-normal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] bg-[var(--sq-surface)] ${
                  active ? 'border-[var(--sq-primary)] ring-2 ring-[var(--sq-primary-soft)]' : 'border-[var(--sq-border)] hover:border-[var(--sq-primary)]'
                }`}>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-[var(--sq-primary-soft)] rounded-full flex items-center justify-center shrink-0">
                    <span className="text-[var(--sq-primary)] font-bold">{(b.name || '?').charAt(0)}</span>
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-[var(--sq-text)] flex items-center gap-2 truncate">
                      {b.name}
                      {active && <Check size={16} className="text-[var(--sq-primary)]" aria-hidden="true" />}
                    </h3>
                    <p className="text-sm text-[var(--sq-text-muted)] truncate">
                      {b.specialization || 'General'}
                      {b.experience_years != null ? ` · ${b.experience_years} yrs exp` : ''}
                      {` · ${barberStatus(b)}`}
                    </p>
                  </div>
                  <span className="ml-auto text-xs px-2 py-1 rounded-full bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)] capitalize shrink-0">{barberStatus(b)}</span>
                </div>
              </button>
            );
          })}
          <button onClick={() => setStep(1)} className="text-sm text-[var(--sq-text-muted)] hover:text-[var(--sq-text)]">← Back to services</button>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="sq-h2">Select Date &amp; Time</h2>
          <Field label="Date" required>
            <Input type="date" min={todayStr()} value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} />
          </Field>
          {selectedDate && (
            <div>
              <p className="sq-label mb-2">Time <span className="text-[var(--sq-text-subtle)] font-normal">— {duration} min service</span></p>
              {slotsLoading ? (
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2" aria-label="Loading time slots">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <div key={i} className="h-[2.75rem] rounded-[var(--sq-radius-lg)] bg-[var(--sq-surface-muted)] animate-pulse" />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <Card>
                  <p className="text-sm text-[var(--sq-text-muted)]">No available slots for this selection.</p>
                  <p className="text-sm text-[var(--sq-text-subtle)] mt-1">Try another date or barber.</p>
                </Card>
              ) : (
                <>
                  {windows.length === 0 && (
                    <p className="text-xs text-[var(--sq-text-subtle)] mb-2">
                      No restricted hours published for this date — all times shown as available, but conflicts are still possible.
                    </p>
                  )}
                  <div className="grid grid-cols-3 sm:grid-cols-5 gap-2" role="group" aria-label="Available time slots">
                    {slots.map((s) => (
                      <SlotButton key={s.time} time={s.time}
                        state={selectedTime === s.time ? 'selected' : s.state}
                        selected={selectedTime === s.time}
                        reason={s.reason}
                        onSelect={() => setSelectedTime(s.time)} />
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-[var(--sq-text-subtle)]">
                    <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--sq-success)]" /> Available</span>
                    <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--sq-primary)]" /> Selected</span>
                    <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--sq-border)]" /> Unavailable / past</span>
                  </div>
                </>
              )}
            </div>
          )}
          {selectedTime && (
            <Button fullWidth onClick={() => setStep(4)}>Continue</Button>
          )}
        </div>
      )}

      {step === 4 && (
        <Card padding="lg">
          <h2 className="sq-h2 mb-4">Confirm Booking</h2>
          <dl className="space-y-3 mb-6">
            {[
              ['Service', `${serviceName(selectedService)} (${serviceDuration(selectedService)} min)`],
              ['Barber', selectedBarber?.name],
              ['Date', selectedDate],
              ['Time', selectedTime],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between py-2 border-b border-[var(--sq-border)]">
                <dt className="text-[var(--sq-text-muted)]">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
            <div className="flex justify-between py-2">
              <dt className="text-[var(--sq-text-muted)]">Price</dt>
              <dd className="font-bold text-[var(--sq-primary)] sq-tnum">₹{selectedService?.price}</dd>
            </div>
          </dl>
          <div className="flex gap-3">
            <Button tone="secondary" fullWidth onClick={() => setStep(3)}>Back</Button>
            <Button fullWidth onClick={handleBook} loading={submitting}>
              {submitting ? 'Booking...' : 'Confirm Booking'}
            </Button>
          </div>
        </Card>
      )}
    </div>
    </>
  );
}
