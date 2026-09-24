import { CalendarDays, Users, Activity, CheckCircle2, Scissors, Bell, UserX, Briefcase } from 'lucide-react';
import StatCard from '../ui/StatCard';

function count(list, key, values) {
  return list.filter((x) => values.includes(String(x[key] || '').toLowerCase())).length;
}

/** System overview — every metric derived from already-fetched API data. */
export default function AdminOverview({ todaysAppointments, queue, barbers, services, notifications }) {
  const cards = [
    { label: "Today's Appointments", value: todaysAppointments.length, icon: <CalendarDays size={18} aria-hidden="true" />, description: 'scheduled for today' },
    { label: 'Waiting', value: count(queue, 'status', ['waiting']), icon: <Users size={18} aria-hidden="true" />, description: 'in queue now' },
    { label: 'Serving', value: count(queue, 'status', ['serving', 'in_progress']), icon: <Activity size={18} aria-hidden="true" />, description: 'being served' },
    { label: 'Completed Today', value: count(todaysAppointments, 'status', ['completed']), icon: <CheckCircle2 size={18} aria-hidden="true" />, description: 'finished visits' },
    { label: 'Barbers', value: barbers.length, icon: <Briefcase size={18} aria-hidden="true" />, description: 'on the team' },
    { label: 'Active Services', value: services.length, icon: <Scissors size={18} aria-hidden="true" />, description: 'bookable now' },
    { label: 'Notifications', value: notifications.length, icon: <Bell size={18} aria-hidden="true" />, description: 'recorded events' },
    { label: 'Cancelled / No-show', value: count(todaysAppointments, 'status', ['cancelled', 'no_show']), icon: <UserX size={18} aria-hidden="true" />, description: 'needs attention' },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((c) => (
        <StatCard key={c.label} title={c.label} value={c.value} icon={c.icon} description={c.description} />
      ))}
    </div>
  );
}
