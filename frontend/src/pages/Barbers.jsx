import { useState, useEffect } from 'react';
import api from '../services/api';

export default function Barbers() {
  const [barbers, setBarbers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/barbers')
      .then((res) => setBarbers(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">Our Barbers</h1>
        <p className="text-slate-500">Meet our professional team</p>
      </div>
      {barbers.length === 0 ? (
        <div className="text-center py-12 text-slate-400">No barbers available</div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {barbers.map((barber) => (
            <div key={barber.id} className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4">
                <span className="text-blue-600 font-bold text-xl">{barber.name.charAt(0)}</span>
              </div>
              <h3 className="text-lg font-semibold text-slate-800">{barber.name}</h3>
              {barber.specialization && (
                <p className="text-slate-500 text-sm mt-1">{barber.specialization}</p>
              )}
              <div className="mt-4">
                <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${
                  barber.status === 'available' ? 'bg-green-100 text-green-700' :
                  barber.status === 'busy' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-slate-100 text-slate-500'
                }`}>
                  {barber.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
