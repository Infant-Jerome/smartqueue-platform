import { useState, useEffect } from 'react';
import api from '../services/api';

export default function Admin() {
  const [tab, setTab] = useState('queue');
  const [services, setServices] = useState([]);
  const [barbers, setBarbers] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [queueEntries, setQueueEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [s, b, a, q] = await Promise.all([
        api.get('/services'), api.get('/barbers'),
        api.get('/appointments'), api.get('/queue'),
      ]);
      setServices(s.data); setBarbers(b.data); setAppointments(a.data); setQueueEntries(q.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  const serveEntry = async (id) => {
    await api.post(`/queue/${id}/serve`);
    fetchData();
  };

  const completeEntry = async (id) => {
    await api.post(`/queue/${id}/complete`);
    fetchData();
  };

  const updateAppointmentStatus = async (id, status) => {
    await api.put(`/appointments/${id}`, { status });
    fetchData();
  };

  const tabs = [
    { id: 'queue', label: 'Queue' },
    { id: 'services', label: 'Services' },
    { id: 'barbers', label: 'Barbers' },
    { id: 'appointments', label: 'Appointments' },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Admin Dashboard</h1>

      <div className="flex gap-2 mb-6 overflow-x-auto">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition ${
              tab === t.id ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}>{t.label}</button>
        ))}
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-400">Loading...</div>
      ) : (
        <>
          {tab === 'queue' && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold text-slate-800">Live Queue</h2>
              {queueEntries.length === 0 ? (
                <p className="text-slate-400 py-8 text-center">No one in queue</p>
              ) : queueEntries.map((entry) => (
                <div key={entry.id} className="bg-white rounded-xl border border-slate-200 p-4 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 rounded-full flex items-center justify-center font-bold text-lg ${
                      entry.status === 'serving' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'
                    }`}>#{entry.queue_number}</div>
                    <div>
                      <p className="font-medium text-slate-800">Appointment #{entry.appointment_id}</p>
                      <p className="text-sm text-slate-500 capitalize">Status: {entry.status}</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {entry.status === 'waiting' && (
                      <button onClick={() => serveEntry(entry.id)}
                        className="px-3 py-2 bg-yellow-500 text-white rounded-lg text-sm font-medium hover:bg-yellow-600 transition">Serve</button>
                    )}
                    {entry.status === 'serving' && (
                      <button onClick={() => completeEntry(entry.id)}
                        className="px-3 py-2 bg-green-500 text-white rounded-lg text-sm font-medium hover:bg-green-600 transition">Complete</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'services' && (
            <div>
              <h2 className="text-lg font-semibold text-slate-800 mb-3">Services</h2>
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr><th className="text-left px-4 py-3 font-medium text-slate-600">Name</th><th className="text-left px-4 py-3 font-medium text-slate-600">Duration</th><th className="text-left px-4 py-3 font-medium text-slate-600">Price</th><th className="text-left px-4 py-3 font-medium text-slate-600">Status</th></tr>
                  </thead>
                  <tbody>
                    {services.map((s) => (
                      <tr key={s.id} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-medium">{s.name}</td>
                        <td className="px-4 py-3 text-slate-500">{s.duration} min</td>
                        <td className="px-4 py-3 text-slate-500">₹{s.price}</td>
                        <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs ${s.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>{s.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === 'barbers' && (
            <div>
              <h2 className="text-lg font-semibold text-slate-800 mb-3">Barbers</h2>
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr><th className="text-left px-4 py-3 font-medium text-slate-600">Name</th><th className="text-left px-4 py-3 font-medium text-slate-600">Specialization</th><th className="text-left px-4 py-3 font-medium text-slate-600">Status</th></tr>
                  </thead>
                  <tbody>
                    {barbers.map((b) => (
                      <tr key={b.id} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-medium">{b.name}</td>
                        <td className="px-4 py-3 text-slate-500">{b.specialization || '-'}</td>
                        <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs ${b.status === 'available' ? 'bg-green-100 text-green-700' : b.status === 'busy' ? 'bg-yellow-100 text-yellow-700' : 'bg-slate-100 text-slate-500'}`}>{b.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === 'appointments' && (
            <div>
              <h2 className="text-lg font-semibold text-slate-800 mb-3">All Appointments</h2>
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">ID</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">User</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Barber</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Date</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Time</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Status</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appointments.map((a) => (
                      <tr key={a.id} className="border-t border-slate-100">
                        <td className="px-4 py-3">#{a.id}</td>
                        <td className="px-4 py-3">{a.user_id}</td>
                        <td className="px-4 py-3">{a.barber?.name || a.barber_id}</td>
                        <td className="px-4 py-3">{a.appointment_date}</td>
                        <td className="px-4 py-3">{a.appointment_time}</td>
                        <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs ${
                          a.status === 'completed' ? 'bg-green-100 text-green-700' :
                          a.status === 'cancelled' ? 'bg-red-100 text-red-700' :
                          a.status === 'serving' ? 'bg-yellow-100 text-yellow-700' :
                          'bg-blue-100 text-blue-700'
                        }`}>{a.status}</span></td>
                        <td className="px-4 py-3">
                          {a.status !== 'completed' && a.status !== 'cancelled' && (
                            <select onChange={(e) => updateAppointmentStatus(a.id, e.target.value)}
                              className="text-xs border border-slate-200 rounded px-2 py-1" defaultValue="">
                              <option value="" disabled>Change</option>
                              <option value="waiting">Waiting</option>
                              <option value="serving">Serving</option>
                              <option value="completed">Completed</option>
                              <option value="cancelled">Cancelled</option>
                            </select>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
