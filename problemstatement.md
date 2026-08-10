# Problem Statement

## 1. Title

**SmartQueue — Barbershop Appointment & Queue Management Platform**

## 2. Domain

Beauty & Grooming / Customer Service / Queue Management

## 3. Who is the user?

The platform has three main user types:

- **Customer** – registers and logs in, browses services and barbers, books appointments, and tracks their live position and estimated wait time in the queue.
- **Admin / Staff** – manages services, barbers, and appointments, and controls the live queue (serve / complete customers).
- **Guest** – can view the salon's services and barbers without logging in.

## 4. What problem are we solving?

Barbershops commonly manage walk-ins and bookings manually with a paper log or a first-come-first-served rule. This causes long physical waiting times, double-booked barber slots, no visibility into when a customer will actually be served, and no way for the salon to signal current queue status. This platform provides a centralized system where customers book a specific barber and time slot online, the salon enforces double-booking prevention, and every booking is turned into a numbered queue entry that both the customer and the staff can track in real time. For example, when a customer books a haircut at 2:00 PM, the system assigns the next queue number for that day and shows the customer how many people are ahead and how long they are expected to wait.

## 5. Proposed Solution (what the application will do, feature-wise)

The application will provide:

- Secure customer and staff registration and login.
- Customer profile management with name, email, phone, and role.
- Public browsing of active services (with price and duration) and barbers (with specialization).
- Appointment booking against a single barber slot per date/time with double-booking prevention.
- Automatic queue-number assignment per day (1, 2, 3, ...) when an appointment is created.
- A live queue view (waiting / serving entries) visible to staff and, per customer, their own queue position.
- Estimated wait time calculation based on the number of people ahead and the service duration.
- Staff actions to move a queue entry to serving and then to completed, which also updates the linked appointment status.
- Admin CRUD for services and barbers (create / read / update / delete).
- Admin view and status updates for all appointments; customers may only cancel their own.
- Role-based access control so users can access only the operations permitted for their role.
- REST API documentation through Swagger UI (`/docs`) and ReDoc (`/redoc`).
- JWT-based authentication with bcrypt password hashing for secure credential storage.

## 6. Core Entities / Database Tables

The core database entities will include:

1. **User** – login credentials, role, and basic customer information.
2. **Barber** – name, specialization, phone, and availability status.
3. **Service** – name, description, duration, and price.
4. **Appointment** – links a user, barber, and service to a date/time slot with a status and a queue number.
5. **QueueEntry** – queue position, status (waiting / serving / completed), and estimated wait time per appointment.

## 7. User Roles & Permissions

### Customer

- Register and log in.
- View services and barbers.
- Create and view their own appointments.
- Track their own queue position and estimated wait time.
- Update their own appointment (cancel only).
- Cannot access other customers' appointments or the admin dashboard.

### Admin / Staff

- View the live queue and all appointments.
- Serve and complete customers in the queue.
- Create, update, and delete services and barbers.
- Update any appointment's status.
- Cannot book appointments on behalf of others (reserved for customers).

### Guest (Public)

- View active services and barbers.
- Cannot book appointments or access authenticated pages.

## 8. Success Criteria

The application will be considered successful when:

- A customer can register and log in successfully.
- A customer can browse services and barbers without authentication.
- A customer can book an appointment in **under 1 minute** under normal conditions.
- The system prevents two bookings for the same barber, date, and time (double-booking prevention).
- Each booking automatically receives a per-day queue number.
- A customer can see how many people are ahead and the estimated wait time.
- Staff can move an entry from waiting → serving → completed, which updates the appointment status consistently.
- The queue and appointment views auto-refresh so data stays live.
- Unauthorized users are denied access to protected resources.
- Customer passwords are stored as secure bcrypt hashes rather than plain text.
- The complete register → book → queue → serve → complete workflow can be demonstrated end-to-end.

## 9. Out of Scope

The following are intentionally excluded from the initial version:

- Payment processing, deposits, or online payments for appointments.
- Reminders sent by SMS or email (notifications are in-app only).
- Real-time socket-based push updates (the UI polls every 10 seconds instead).
- Multiple-barber simultaneous availability scheduling beyond the single-slot rule.
- Customer reviewing/rating barbers or services.
- Multi-branch / multi-salon support (single salon only).
- Mobile applications (responsive web only).
- Advanced analytics or business-intelligence reporting dashboards.

## 10. Chosen Track

**Python (FastAPI)**