import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { serviceId, serviceName, serviceDuration, barberId, barberStatus } from '../utils/format';
import { LoadingState, ErrorState } from '../components/States';

const TIMES = ['09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','14:00','14:30','15:00','15:30','16:00','16:30','17:00','17:30','18:00','18:30','19:00'];

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
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [confirmation, setConfirmation] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.get('/services'), api.get('/barbers')])
      .then(([sRes, bRes]) => {
        setServices(Array.isArray(sRes.data) ? sRes.data : []);
        setBarbers(Array.isArray(bRes.data) ? bRes.data : []);
      })
      .catch((err) => setLoadError(err.message || 'Failed to load booking data.'))
      .finally(() => setLoading(false));
  }, []);

  const todayStr = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };

  const friendlyError = (err) => {
    const status = err.response?.status;
    if (status === 409) return 'This time slot conflicts with another appointment. Please choose a different time.';
    if (status === 404) return 'The selected service or barber was not found. Please refresh and try again.';
    return err.message || 'Booking failed. Please try again.';
  };

  const handleBook = async () => {
    setError('');
    if (!selectedService || !selectedBarber || !selectedDate || !selectedTime) {
      setError('Please complete all booking steps before confirming.');
      return;
    }
    if (selectedDate < todayStr()) {
      setError('The booking date cannot be in the past.');
      return;
    }
    setSubmitting(true);
    try {
      // Backend derives customer from JWT and end_time from service duration.
      // Only the required fields are sent; never customer_id or end_time.
      const res = await api.post('/appointments', {
        barber_id: barberId(selectedBarber),
        service_id: serviceId(selectedService),
        appointment_date: selectedDate,
        start_time: selectedTime,
      });
      setConfirmation(res.data);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <LoadingState message="Loading booking options..." />
      </div>
      </>
    );
  }

  if (loadError) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <ErrorState message={loadError} onRetry={() => window.location.reload()} />
      </div>
      </>
    );
  }

  if (confirmation) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="bg-white rounded-xl border border-slate-200 p-8 text-center">
          <div className="text-5xl mb-4">✓</div>
          <h1 className="text-2xl font-bold text-slate-800 mb-2">Appointment booked!</h1>
          <p className="text-slate-500 mb-2">
            {serviceName(selectedService)} with {selectedBarber?.name} on {selectedDate} at {selectedTime}
          </p>
          {confirmation.queue_position != null && (
            <p className="text-slate-700 mb-6">
              Queue position <strong>#{confirmation.queue_position}</strong>
              {confirmation.estimated_wait_minutes != null && (
                <> · estimated wait <strong>{confirmation.estimated_wait_minutes} min</strong></>
              )}
            </p>
          )}
          <div className="flex gap-3 justify-center">
            <button onClick={() => navigate('/queue')} className="bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition">
              View Queue
            </button>
            <button onClick={() => navigate('/appointments')} className="bg-slate-100 text-slate-700 px-6 py-3 rounded-lg font-medium hover:bg-slate-200 transition">
              My Appointments
            </button>
          </div>
        </div>
      </div>
      </>
    );
  }

  return (
    <><Navbar />
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
          {services.length === 0 && <p className="text-slate-500">No services currently available.</p>}
          {services.map((s) => (
            <button key={serviceId(s)} onClick={() => { setSelectedService(s); setStep(2); }}
              className={`w-full text-left p-4 rounded-xl border-2 transition ${
                selectedService && serviceId(selectedService) === serviceId(s) ? 'border-blue-600 bg-blue-50' : 'border-slate-200 hover:border-blue-300 bg-white'
              }`}>
              <div className="flex justify-between items-center">
                <div>
                  <h3 className="font-semibold text-slate-800">{serviceName(s)}</h3>
                  <p className="text-sm text-slate-500">
                    {serviceDuration(s) != null ? `${serviceDuration(s)} min` : ''}
                    {s.description ? ` · ${s.description}` : ''}
                  </p>
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
          {barbers.length === 0 && <p className="text-slate-500">No barbers currently available.</p>}
          {barbers.map((b) => (
            <button key={barberId(b)} onClick={() => { setSelectedBarber(b); setStep(3); }}
              className={`w-full text-left p-4 rounded-xl border-2 transition ${
                selectedBarber && barberId(selectedBarber) === barberId(b) ? 'border-blue-600 bg-blue-50' : 'border-slate-200 hover:border-blue-300 bg-white'
              }`}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
                  <span className="text-blue-600 font-bold">{(b.name || '?').charAt(0)}</span>
                </div>
                <div>
                  <h3 className="font-semibold text-slate-800">{b.name}</h3>
                  <p className="text-sm text-slate-500">{b.specialization || 'General'}</p>
                </div>
                <span className="ml-auto text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-600 capitalize">{barberStatus(b)}</span>
              </div>
            </button>
          ))}
          <button onClick={() => setStep(1)} className="text-sm text-slate-500 hover:text-slate-700">← Back to services</button>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-800">Select Date & Time</h2>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Date</label>
            <input type="date" min={todayStr()} value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none" />
          </div>
          {selectedDate && (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Time</label>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                {TIMES.map((t) => (
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
              <span className="font-medium">{serviceName(selectedService)} ({serviceDuration(selectedService)} min)</span>
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
    </>
  );
}
