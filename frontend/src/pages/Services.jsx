import { useState, useEffect } from 'react';
import api from '../services/api';

export default function Services() {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/services')
      .then((res) => setServices(res.data))
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
        <h1 className="text-2xl font-bold text-slate-800">Our Services</h1>
        <p className="text-slate-500">Choose from our range of professional grooming services</p>
      </div>
      {services.length === 0 ? (
        <div className="text-center py-12 text-slate-400">No services available yet</div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {services.map((service) => (
            <div key={service.id} className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
              <h3 className="text-lg font-semibold text-slate-800">{service.name}</h3>
              {service.description && (
                <p className="text-slate-500 text-sm mt-2">{service.description}</p>
              )}
              <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
                <span className="text-slate-500 text-sm">{service.duration} min</span>
                <span className="text-blue-600 font-bold text-lg">₹{service.price}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
