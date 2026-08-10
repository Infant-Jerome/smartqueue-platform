import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

export default function Dashboard() {
  const { user } = useAuth();
  const [queueInfo, setQueueInfo] = useState(null);
  const [appointments, setAppointments] = useState([]);

  useEffect(() => {
    api.get('/queue/my-position').then((res) => setQueueInfo(res.data)).catch(() => {});
    api.get('/appointments').then((res) => setAppointments(res.data.slice(0, 5))).catch(() => {});
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">Welcome, {user?.name}</h1>
        <p className="text-slate-500">Here&apos;s your appointment overview</p>
      </div>

      {queueInfo?.has_queue && (
        <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-2xl p-6 text-white mb-8">
          <h2 className="text-lg font-semibold mb-4">Your Queue Status</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-blue-200 text-sm">Queue Number</p>
              <p className="text-3xl font-bold">#{queueInfo.queue_number}</p>
            </div>
            <div>
              <p className="text-blue-200 text-sm">People Ahead</p>
              <p className="text-3xl font-bold">{queueInfo.people_ahead}</p>
            </div>
            <div>
              <p className="text-blue-200 text-sm">Estimated Wait</p>
              <p className="text-3xl font-bold">{queueInfo.estimated_wait_minutes} min</p>
            </div>
            <div>
              <p className="text-blue-200 text-sm">Status</p>
              <p className="text-3xl font-bold capitalize">{queueInfo.status}</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-6 mb-8">
        <Link to="/book" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-blue-600 text-2xl mb-2">+</div>
          <h3 className="font-semibold text-slate-800">Book Appointment</h3>
          <p className="text-sm text-slate-500">Schedule a new visit</p>
        </Link>
        <Link to="/queue" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-green-600 text-2xl mb-2">#</div>
          <h3 className="font-semibold text-slate-800">View Queue</h3>
          <p className="text-sm text-slate-500">Check your position</p>
        </Link>
        <Link to="/services" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-purple-600 text-2xl mb-2">*</div>
          <h3 className="font-semibold text-slate-800">Our Services</h3>
          <p className="text-sm text-slate-500">Browse available services</p>
        </Link>
      </div>

      {appointments.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Recent Appointments</h2>
          <div className="space-y-3">
            {appointments.map((appt) => (
              <div key={appt.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div>
                  <p className="font-medium text-slate-800">
                    {appt.service?.name || 'Service'} with {appt.barber?.name || 'Barber'}
                  </p>
                  <p className="text-sm text-slate-500">{appt.appointment_date} at {appt.appointment_time}</p>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  appt.status === 'completed' ? 'bg-green-100 text-green-700' :
                  appt.status === 'cancelled' ? 'bg-red-100 text-red-700' :
                  appt.status === 'serving' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-blue-100 text-blue-700'
                }`}>
                  {appt.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
