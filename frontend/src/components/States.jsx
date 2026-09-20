export function LoadingState({ message = 'Loading...' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      <p className="text-slate-500 text-sm">{message}</p>
    </div>
  );
}

export function EmptyState({ title, message, action }) {
  return (
    <div className="text-center py-12">
      <h2 className="text-xl font-semibold text-slate-800 mb-2">{title}</h2>
      {message && <p className="text-slate-500 mb-6">{message}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message = 'Something went wrong.', onRetry }) {
  return (
    <div className="text-center py-12">
      <p className="text-red-600 mb-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg font-medium hover:bg-blue-700 transition"
        >
          Retry
        </button>
      )}
    </div>
  );
}
