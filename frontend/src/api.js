import axios from "axios";

// PORT_BASE = 8675 (SID4 7875). withCredentials is required so the browser
// actually sends/receives the HttpOnly session cookie on every call, since
// the frontend (5173) and backend (8675) are different origins.
const api = axios.create({
  baseURL: "http://localhost:8675",
  withCredentials: true,
});

// --- Auth ---
export const login = (email, password) =>
  api.post("/api/auth/login", { email, password }).then((r) => r.data);

export const logout = () => api.post("/api/auth/logout").then((r) => r.data);

export const me = () => api.get("/api/auth/me").then((r) => r.data);

// --- Helpers used by the forms (HW5) ---
// The notice list/create/update/delete calls now live in the Redux thunks
// (features/notices/noticesSlice.js). These two are simple lookups.
export const fetchNoticeById = (id) =>
  api.get(`/api/notices/${id}`).then((r) => r.data);

export const fetchManufacturers = () =>
  api.get("/api/manufacturers", { params: { page: 1, page_size: 100 } }).then((r) => r.data.items);

export default api;
