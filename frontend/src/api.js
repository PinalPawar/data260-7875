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

// --- Notices (the domain entity) ---
export const fetchNotices = () => api.get("/api/notices").then((r) => r.data);

export const fetchNoticeById = (id) =>
  api.get(`/api/notices/${id}`).then((r) => r.data);

export const createNotice = (payload) =>
  api.post("/api/notices", payload).then((r) => r.data);

export const updateNotice = (id, payload) =>
  api.put(`/api/notices/${id}`, payload).then((r) => r.data);

export const deleteNotice = (id) =>
  api.delete(`/api/notices/${id}`).then((r) => r.data);

export default api;
