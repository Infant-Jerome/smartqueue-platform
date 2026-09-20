/** Canonical backend roles (see backend/app/models/user.py UserRole).
 * `staff` is a compatibility alias of `receptionist`. There is no
 * doctor/patient role and `user` is the entity name, not a role.
 */
export const ROLES = Object.freeze({
  CUSTOMER: 'customer',
  BARBER: 'barber',
  RECEPTIONIST: 'receptionist',
  STAFF: 'staff',
  ADMIN: 'admin',
});

export function normalizeRole(role) {
  const value = role?.value ?? role;
  return String(value ?? '').trim().toLowerCase();
}

export function isStaffRole(role) {
  const r = normalizeRole(role);
  return r === ROLES.STAFF || r === ROLES.RECEPTIONIST;
}

/** Landing dashboard per role. Staff shares the receptionist dashboard. */
export function getDashboardPath(role) {
  const r = normalizeRole(role);
  switch (r) {
    case ROLES.ADMIN:
      return '/admin/dashboard';
    case ROLES.BARBER:
      return '/barber/dashboard';
    case ROLES.RECEPTIONIST:
    case ROLES.STAFF:
      return '/receptionist/dashboard';
    case ROLES.CUSTOMER:
    default:
      return '/dashboard';
  }
}
