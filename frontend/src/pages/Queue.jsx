import { useState, useEffect } from 'react';
import api from '../services/api';

export default function Queue() {
  const [queueInfo, setQueueInfo] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchQueue = () => {
    api.get('/queue/my-position')
      .then((res) => setQueueInfo(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchQueue();
    const interval = setInterval(fetchQueue, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!queueInfo?.has_queue) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center">
        <div className="text-6xl mb-4">#</div>
        <h1 className="text-2xl font-bold text-slate-800 mb-2">No Active Queue</h1>
        <p className="text-slate-500">Book an appointment to join the queue</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Live Queue</h1>

      <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-2xl p-8 text-white mb-6">
        <div className="text-center mb-6">
          <p className="text-blue-200 text-sm mb-1">Your Queue Number</p>
          <p className="text-6xl font-bold">#{queueInfo.queue_number}</p>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
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

      {queueInfo.currently_serving && (
        <div className="bg-white rounded-xl border border-slate-200 p-6 mb-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-500">Currently Serving</p>
              <p className="text-2xl font-bold text-slate-800">#{queueInfo.currently_serving}</p>
            </div>
            <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <p className="text-sm text-slate-500 text-center">Queue updates automatically every 10 seconds</p>
      </div>
    </div>
  );
}
