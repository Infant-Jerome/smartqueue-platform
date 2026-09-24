import Card from '../ui/Card';
import Button from '../ui/Button';
import StatusBadge from '../ui/StatusBadge';
import Field from '../ui/Field';
import Select from '../ui/Select';
import { EmptyState } from '../States';
import { fmtTime } from '../../utils/format';

const STATUS_OPTIONS = ['All', 'Booked', 'Confirmed', 'Waiting', 'In Progress', 'Completed', 'Cancelled', 'No Show'];

/** Appointment operations. Same list, filters and cancel flow as before. */
export default function AdminAppointments({
  rows, barbers, pending,
  statusFilter, setStatusFilter, barberFilter, setBarberFilter,
  barberOf, serviceOf, onCancel,
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <h2 className="sq-h2 mr-auto">Appointments</h2>
        <Field>
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter appointments by status" className="!w-auto !min-h-0 py-1.5">
            {STATUS_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
          </Select>
        </Field>
        <Field>
          <Select value={barberFilter} onChange={(e) => setBarberFilter(e.target.value)} aria-label="Filter appointments by barber" className="!w-auto !min-h-0 py-1.5">
            <option value="All">All barbers</option>
            {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
          </Select>
        </Field>
      </div>

      {rows.length === 0 ? (
        <EmptyState title="No appointments match." message="Adjust the filters or check back later." />
      ) : (
        <div className="space-y-2">
          {rows.map((a) => {
            const st = String(a.status || '').toLowerCase();
            const terminal = ['completed', 'cancelled', 'no_show'].includes(st);
            return (
              <div key={a.appointment_id} className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
                <span className="font-semibold sq-tnum text-sm whitespace-nowrap">
                  {fmtTime(a.start_time)}{a.end_time ? ` – ${fmtTime(a.end_time)}` : ''}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">
                    #{a.appointment_id} · {barberOf(a.barber_id)?.name || `#${a.barber_id}`} · {serviceOf(a.service_id)?.service_name || '—'}
                  </p>
                  <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">
                    {String(a.appointment_date).slice(0, 10)} · {String(a.booking_type || 'online').replace(/_/g, ' ')}
                  </p>
                </div>
                <div className="flex items-center gap-1.5 ml-0 sm:ml-auto">
                  <StatusBadge status={a.status} />
                  {!terminal && (
                    <Button size="sm" tone="danger" loading={pending[`cancel-${a.appointment_id}`]} onClick={() => onCancel(a.appointment_id)}>
                      Cancel
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
