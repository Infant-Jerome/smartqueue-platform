import Card from '../ui/Card';
import Button from '../ui/Button';
import StatusBadge from '../ui/StatusBadge';
import Field from '../ui/Field';
import Input from '../ui/Input';
import Select from '../ui/Select';
import ConfirmDialog from '../ui/ConfirmDialog';
import { EmptyState } from '../States';

/** Service CRUD. Same endpoints, payloads and confirm flow as before. */
export default function AdminServices({
  services, form, setForm, editingId, pendingSave, onSubmit, onCancelEdit,
  onEdit, deleteTarget, setDeleteTarget, pendingDelete, onDelete,
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-2 mb-1">
        <h2 className="sq-h2 mr-auto">Services</h2>
      </div>
      <p className="sq-caption text-[var(--sq-text-subtle)] mb-4">The services list shows active services only; deactivated rows leave this list.</p>
      <form onSubmit={onSubmit} className="grid sm:grid-cols-3 gap-2 mb-3">
        <Field label="Service name" required>
          <Input value={form.service_name} onChange={(e) => setForm({ ...form, service_name: e.target.value })} placeholder="Service name" required />
        </Field>
        <Field label="Duration (min)" required>
          <Input value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })} placeholder="30" type="number" min="1" required />
        </Field>
        <Field label="Price" required>
          <Input value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} placeholder="250" type="number" min="0" step="0.01" required />
        </Field>
        <Field label="Description">
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Description" />
        </Field>
        <Field label="Status">
          <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
            <option value="active">active</option>
            <option value="inactive">inactive</option>
          </Select>
        </Field>
        <div className="flex items-end gap-2">
          <Button type="submit" loading={pendingSave} className="flex-1">
            {pendingSave ? 'Saving...' : editingId ? 'Update service' : 'Add service'}
          </Button>
          {editingId && (
            <Button tone="secondary" onClick={onCancelEdit}>Cancel</Button>
          )}
        </div>
      </form>

      {services.length === 0 ? (
        <EmptyState title="No services yet." message="Add the first service above." />
      ) : (
        <div className="space-y-2">
          {services.map((s) => (
            <div key={s.service_id} className="flex flex-col sm:flex-row sm:items-center gap-2 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-sm truncate">{s.service_name} <span className="font-normal text-[var(--sq-text-subtle)] sq-tnum">#{s.service_id}</span></p>
                <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">{s.duration_minutes} min · ₹{s.price}</p>
              </div>
              <div className="flex items-center gap-1.5 ml-0 sm:ml-auto">
                <StatusBadge status={s.status} />
                <Button size="sm" tone="secondary" onClick={() => onEdit(s)}>Edit</Button>
                <Button size="sm" tone="danger" onClick={() => setDeleteTarget(s)}>Delete</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete this service?"
        description={deleteTarget ? `${deleteTarget.service_name} (#${deleteTarget.service_id}) will be permanently removed.` : ''}
        confirmLabel="Delete"
        danger
        loading={deleteTarget ? pendingDelete(deleteTarget.service_id) : false}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && onDelete(deleteTarget.service_id)}
      />
    </Card>
  );
}
