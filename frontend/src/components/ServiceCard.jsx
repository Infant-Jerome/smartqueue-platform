import { Link } from 'react-router-dom';
import { serviceId, serviceName, serviceDuration } from '../utils/format';

export function ServiceCard({ service, actionTo, actionLabel = 'Book' }) {
  const card = (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition h-full">
      <h3 className="text-lg font-semibold text-slate-800">{serviceName(service)}</h3>
      {service.description && (
        <p className="text-slate-500 text-sm mt-2">{service.description}</p>
      )}
      <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
        <span className="text-slate-500 text-sm">
          {serviceDuration(service) != null ? `${serviceDuration(service)} min` : '—'}
        </span>
        <span className="text-blue-600 font-bold text-lg">₹{service.price}</span>
      </div>
      {actionTo && (
        <span className="inline-block mt-4 text-sm text-blue-600 font-medium">{actionLabel} →</span>
      )}
    </div>
  );
  return actionTo ? <Link to={actionTo}>{card}</Link> : card;
}

export function ServiceGrid({ services, actionTo }) {
  return (
    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
      {services.map((s) => (
        <ServiceCard key={serviceId(s)} service={s} actionTo={actionTo} />
      ))}
    </div>
  );
}
