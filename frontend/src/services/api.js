import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    if (
      response.data &&
      typeof response.data === 'object' &&
      'success' in response.data &&
      'data' in response.data
    ) {
      response.data = response.data.data;
    }
    return response;
  },
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      // Don't hard-redirect when the 401 came from a public auth form;
      // the form needs to display the error instead of reloading.
      const path = window.location.pathname;
      if (path !== '/login' && path !== '/register' && path !== '/forgot-password') {
        window.location.href = '/login';
      }
    }
    if (error.response?.data?.message) {
      error.message = error.response.data.message;
    } else if (status === 403) {
      error.message = "You don't have permission to access this resource.";
    } else if (status === 409) {
      error.message = error.message || 'Request conflicts with the current state.';
    } else if (status === 422) {
      error.message = error.message || 'Validation failed. Please check your input.';
    } else if (status >= 500) {
      error.message = 'Server error. Please try again later.';
    }
    return Promise.reject(error);
  }
);

export default api;
