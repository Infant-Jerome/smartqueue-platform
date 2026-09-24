import Card from '../ui/Card';
import Button from '../ui/Button';
import StatusBadge from '../ui/StatusBadge';
import Field from '../ui/Field';
import Input from '../ui/Input';
import Select from '../ui/Select';
import ConfirmDialog from '../ui/ConfirmDialog';
import { EmptyState } from '../States';
import { fmtTime } from '../../utils/format';

/** Availability windows. Same create/delete endpoints and flow as before. */
export default function AdminAvailability({
  windows, barbers, form, setForm, pendingSave, onSubmit,
  deleteTarget, setDeleteTarget, pendingDelete, onDelete, today,
}) {
  return (
    <Card>
      <h2 className="sq-h2 mb-4">Availability</h2>
      <form onSubmit={onSubmit} className="grid sm:grid-cols-5 gap-2 mb-4">
        <Field label="Barber" required>
          <Select value={form.barber_id} onChange={(e) => setForm({ ...form, barber_id: e.target.value })} required>
            <option value="">Barber</option>
            {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
          </Select>
        </Field>
        <Field label="Date" required>
          <Input type="date" value={form.date} min={today} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
        </Field>
        <Field label="Start" required>
          <Input type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} required />
        </Field>
        <Field label="End" required>
          <Input type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} required />
        </Field>
        <div className="flex items-end">
          <Button type="submit" loading={pendingSave} className="w-full">Add window</Button>
        </div>
      </form>

      {windows.length === 0 ? (
        <EmptyState title="No availability windows for today." />
      ) : (
        <div className="space-y-2">
          {windows.map((v) => (
            <div key={v.availability_id} className="flex flex-wrap items-center gap-2 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)] text-sm">
              <span className="font-medium">{barbers.find((b) => b.barber_id === v.barber_id)?.name || `Barber #${v.barber_id}`}</span>
              <span className="text-[var(--sq-text-muted)] sq-tnum">{String(v.date).slice(0, 10)} · {fmtTime(v.start_time)} – {fmtTime(v.end_time)}</span>
              <StatusBadge status={v.status} />
              <Button size="sm" tone="danger" className="ml-auto" onClick={() => setDeleteTarget(v)}>Delete</Button>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Remove this availability window?"
        description="Bookings that depend on this window are unaffected; only the window is removed."
        confirmLabel="Remove"
        danger
        loading={deleteTarget ? pendingDelete(deleteTarget.availability_id) : false}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && onDelete(deleteTarget.availability_id)}
      />
    </Card>
  );
}
