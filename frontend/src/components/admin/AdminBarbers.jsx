import Card from '../ui/Card';
import Button from '../ui/Button';
import StatusBadge from '../ui/StatusBadge';
import Field from '../ui/Field';
import Input from '../ui/Input';
import Select from '../ui/Select';
import ConfirmDialog from '../ui/ConfirmDialog';
import { EmptyState } from '../States';

/** Barber CRUD. Same endpoints, payloads and confirm flow as before. */
export default function AdminBarbers({
  barbers, form, setForm, editingId, pendingSave, onSubmit, onCancelEdit,
  onEdit, deleteTarget, setDeleteTarget, pendingDelete, onDelete,
}) {
  return (
    <Card>
      <h2 className="sq-h2 mb-4">Barbers</h2>
      <form onSubmit={onSubmit} className="grid sm:grid-cols-3 gap-2 mb-3">
        <Field label="Name" required>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name" required />
        </Field>
        <Field label="Specialization">
          <Input value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })} placeholder="Specialization" />
        </Field>
        <Field label="Phone">
          <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Phone" />
        </Field>
        <Field label="Experience (yrs)">
          <Input value={form.experience_years} onChange={(e) => setForm({ ...form, experience_years: e.target.value })} placeholder="0" type="number" min="0" />
        </Field>
        <Field label="Status">
          <Select value={form.availability_status} onChange={(e) => setForm({ ...form, availability_status: e.target.value })}>
            <option value="available">available</option>
            <option value="busy">busy</option>
            <option value="inactive">inactive</option>
          </Select>
        </Field>
        <div className="flex items-end gap-2">
          <Button type="submit" loading={pendingSave} className="flex-1">
            {pendingSave ? 'Saving...' : editingId ? 'Update barber' : 'Add barber'}
          </Button>
          {editingId && (
            <Button tone="secondary" onClick={onCancelEdit}>Cancel</Button>
          )}
        </div>
      </form>

      {barbers.length === 0 ? (
        <EmptyState title="No barbers yet." message="Add the first barber above." />
      ) : (
        <div className="space-y-2">
          {barbers.map((b) => (
            <div key={b.barber_id} className="flex flex-col sm:flex-row sm:items-center gap-2 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
              <span className="flex w-9 h-9 rounded-full bg-[var(--sq-primary-soft)] text-[var(--sq-primary)] items-center justify-center font-bold shrink-0" aria-hidden="true">
                {(b.name || '?').charAt(0)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-sm truncate">{b.name} <span className="font-normal text-[var(--sq-text-subtle)] sq-tnum">#{b.barber_id}</span></p>
                <p className="text-xs text-[var(--sq-text-muted)] truncate">
                  {b.specialization || 'General'}
                  {b.experience_years != null ? ` · ${b.experience_years} yrs` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1.5 ml-9 sm:ml-0">
                <StatusBadge status={b.availability_status} />
                <Button size="sm" tone="secondary" onClick={() => onEdit(b)}>Edit</Button>
                <Button size="sm" tone="danger" onClick={() => setDeleteTarget(b)}>Delete</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete this barber?"
        description={deleteTarget ? `${deleteTarget.name} (#${deleteTarget.barber_id}) will be permanently removed.` : ''}
        confirmLabel="Delete"
        danger
        loading={deleteTarget ? pendingDelete(deleteTarget.barber_id) : false}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && onDelete(deleteTarget.barber_id)}
      />
    </Card>
  );
}
