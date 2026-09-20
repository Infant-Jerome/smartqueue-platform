import { barberId, barberStatus } from '../utils/format';

const STATUS_STYLES = {
  available: 'bg-green-100 text-green-700',
  busy: 'bg-yellow-100 text-yellow-700',
};

export function BarberCard({ barber, selected, onSelect }) {
  const status = barberStatus(barber);
  const inner = (
    <>
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center shrink-0">
          <span className="text-blue-600 font-bold">{(barber.name || '?').charAt(0)}</span>
        </div>
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-800 truncate">{barber.name}</h3>
          <p className="text-sm text-slate-500 truncate">
            {barber.specialization || 'General'}
            {barber.experience_years != null ? ` · ${barber.experience_years} yrs exp` : ''}
          </p>
        </div>
        <span className={`ml-auto text-xs px-2 py-1 rounded-full capitalize shrink-0 ${STATUS_STYLES[status] || 'bg-slate-100 text-slate-500'}`}>
          {status}
        </span>
      </div>
    </>
  );

  if (onSelect) {
    return (
      <button
        onClick={() => onSelect(barber)}
        className={`w-full text-left p-4 rounded-xl border-2 transition ${
          selected ? 'border-blue-600 bg-blue-50' : 'border-slate-200 hover:border-blue-300 bg-white'
        }`}
      >
        {inner}
      </button>
    );
  }
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
      <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4">
        <span className="text-blue-600 font-bold text-xl">{(barber.name || '?').charAt(0)}</span>
      </div>
      <h3 className="text-lg font-semibold text-slate-800">{barber.name}</h3>
      {barber.specialization && (
        <p className="text-slate-500 text-sm mt-1">{barber.specialization}</p>
      )}
      {barber.experience_years != null && (
        <p className="text-slate-500 text-sm mt-1">{barber.experience_years} years experience</p>
      )}
      <div className="mt-4">
        <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium capitalize ${STATUS_STYLES[status] || 'bg-slate-100 text-slate-500'}`}>
          {status}
        </span>
      </div>
    </div>
  );
}

export function BarberGrid({ barbers }) {
  return (
    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
      {barbers.map((b) => (
        <BarberCard key={barberId(b)} barber={b} />
      ))}
    </div>
  );
}
