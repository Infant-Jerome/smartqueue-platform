import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';

export default function BookAppointment() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [services, setServices] = useState([]);
  const [barbers, setBarbers] = useState([]);
  const [selectedService, setSelectedService] = useState(null);
  const [selectedBarber, setSelectedBarber] = useState(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.get('/services'), api.get('/barbers')])
      .then(([sRes, bRes]) => { setServices(sRes.data); setBarbers(bRes.data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const times = ['09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','14:00','14:30','15:00','15:30','16:00','16:30','17:00','17:30','18:00','18:30','19:00'];

  const getMinDate = () => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().split('T')[0];
  };

  const handleBook = async () => {
    setError('');
    setSubmitting(true);
    try {
      await api.post('/appointments', {
        barber_id: selectedBarber.id,
        service_id: selectedService.id,
        appointment_date: selectedDate,
        appointment_time: selectedTime,
      });
      navigate('/queue');
    } catch (err) {
      setError(err.response?.data?.message || err.message || 'Booking failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-800 mb-2">Book Appointment</h1>
      <p className="text-slate-500 mb-6">Follow the steps to schedule your visit</p>

      <div className="flex items-center gap-4 mb-8">
        {[1,2,3,4].map((s) => (
          <div key={s} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
              step >= s ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-500'
            }`}>{s}</div>
            <span className={`text-sm hidden sm:inline ${step >= s ? 'text-blue-600 font-medium' : 'text-slate-400'}`}>
              {['Service','Barber','Date & Time','Confirm'][s-1]}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">{error}</div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-slate-800">Select a Service</h2>
          {services.map((s) => (
            <button key={s.id} onClick={() => { setSelectedService(s); setStep(2); }}
              className={`w-full text-left p-4 rounded-xl border-2 transition ${
                selectedService?.id === s.id ? 'border-blue-600 bg-blue-50' : 'border-slate-200 hover:border-blue-300 bg-white'
              }`}>
              <div className="flex justify-between items-center">
                <div>
                  <h3 className="font-semibold text-slate-800">{s.name}</h3>
                  <p className="text-sm text-slate-500">{s.duration} min</p>
                </div>
                <span className="text-blue-600 font-bold">₹{s.price}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-slate-800">Select a Barber</h2>
          {barbers.map((b) => (
            <button key={b.id} onClick={() => { setSelectedBarber(b); setStep(3); }}
              className={`w-full text-left p-4 rounded-xl border-2 transition ${
                selectedBarber?.id === b.id ? 'border-blue-600 bg-blue-50' : 'border-slate-200 hover:border-blue-300 bg-white'
              }`}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
                  <span className="text-blue-600 font-bold">{b.name.charAt(0)}</span>
                </div>
                <div>
                  <h3 className="font-semibold text-slate-800">{b.name}</h3>
                  <p className="text-sm text-slate-500">{b.specialization || 'General'}</p>
                </div>
                <span className={`ml-auto text-xs px-2 py-1 rounded-full ${
                  b.status === 'available' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                }`}>{b.status}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-800">Select Date & Time</h2>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Date</label>
            <input type="date" min={getMinDate()} value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none" />
          </div>
          {selectedDate && (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Time</label>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                {times.map((t) => (
                  <button key={t} onClick={() => setSelectedTime(t)}
                    className={`px-3 py-2 rounded-lg text-sm font-medium transition ${
                      selectedTime === t ? 'bg-blue-600 text-white' : 'bg-slate-100 hover:bg-blue-100 text-slate-700'
                    }`}>{t}</button>
                ))}
              </div>
            </div>
          )}
          {selectedTime && (
            <button onClick={() => setStep(4)} className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 transition">
              Continue
            </button>
          )}
        </div>
      )}

      {step === 4 && (
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Confirm Booking</h2>
          <div className="space-y-3 mb-6">
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="text-slate-500">Service</span>
              <span className="font-medium">{selectedService?.name}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="text-slate-500">Barber</span>
              <span className="font-medium">{selectedBarber?.name}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="text-slate-500">Date</span>
              <span className="font-medium">{selectedDate}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-100">
              <span className="text-slate-500">Time</span>
              <span className="font-medium">{selectedTime}</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-500">Price</span>
              <span className="font-bold text-blue-600">₹{selectedService?.price}</span>
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setStep(3)} className="flex-1 bg-slate-100 text-slate-700 py-3 rounded-lg font-medium hover:bg-slate-200 transition">Back</button>
            <button onClick={handleBook} disabled={submitting}
              className="flex-1 bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition">
              {submitting ? 'Booking...' : 'Confirm Booking'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
