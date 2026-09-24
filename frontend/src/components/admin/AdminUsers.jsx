import Card from '../ui/Card';
import Button from '../ui/Button';
import Field from '../ui/Field';
import Input from '../ui/Input';
import Select from '../ui/Select';

const VALID_ROLES = ['customer', 'barber', 'receptionist', 'staff', 'admin'];

/**
 * User lookup by ID + role assignment. The backend exposes no user-list
 * endpoint, so lookup-by-ID is preserved exactly, including the
 * self-demotion guard flow.
 */
export default function AdminUsers({
  lookupId, setLookupId, lookupUser, lookupError, newRole, setNewRole,
  confirmSelfDemote, setConfirmSelfDemote, pendingRole, onLookup, onApplyRole,
}) {
  return (
    <Card>
      <h2 className="sq-h2 mb-1">User Management</h2>
      <p className="sq-body-sm text-[var(--sq-text-muted)] mb-4">
        The backend exposes user lookup by ID (no user-list endpoint), plus admin role assignment.
      </p>
      <form onSubmit={onLookup} className="flex flex-col sm:flex-row gap-2 mb-4">
        <Field label="User ID">
          <Input value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="User ID (e.g. 1)" className="sm:max-w-48" />
        </Field>
        <div className="flex items-end">
          <Button type="submit">Look up</Button>
        </div>
      </form>
      {lookupError && <p className="text-sm text-[var(--sq-danger)] mb-4" role="alert">{lookupError}</p>}
      {lookupUser && (
        <div className="border border-[var(--sq-border)] rounded-[var(--sq-radius-lg)] p-4">
          <p className="font-semibold">{lookupUser.name} <span className="text-[var(--sq-text-subtle)] font-normal sq-tnum">#{lookupUser.user_id}</span></p>
          <p className="sq-body-sm text-[var(--sq-text-muted)]">{lookupUser.email}{lookupUser.phone ? ` · ${lookupUser.phone}` : ''}</p>
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <Field label="Role">
              <Select value={newRole} onChange={(e) => { setNewRole(e.target.value); setConfirmSelfDemote(false); }} className="!w-auto">
                {VALID_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </Select>
            </Field>
            <div className="flex items-end">
              <Button size="sm" loading={pendingRole} onClick={onApplyRole}>Update role</Button>
            </div>
          </div>
          {confirmSelfDemote && (
            <div className="mt-3 p-3 bg-[var(--sq-warning-soft)] border border-[#fde68a] rounded-[var(--sq-radius-lg)] text-sm">
              <p className="text-[var(--sq-text)] mb-2">This changes your own role and may remove your admin access. Continue?</p>
              <div className="flex gap-2">
                <Button size="sm" tone="secondary" onClick={() => setConfirmSelfDemote(false)}>Keep admin</Button>
                <Button size="sm" tone="danger" onClick={onApplyRole}>Confirm change</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
