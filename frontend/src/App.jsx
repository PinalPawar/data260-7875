import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

import Navbar from "./components/Navbar.jsx";
import Login from "./pages/Login.jsx";
import Home from "./pages/Home.jsx";
import CreateRecord from "./pages/CreateRecord.jsx";
import UpdateRecord from "./pages/UpdateRecord.jsx";
import DeleteRecord from "./pages/DeleteRecord.jsx";

import { me, logout, fetchNotices, createNotice, updateNotice, deleteNotice } from "./api.js";

// HW4 Part 1, Section V: hooks (useState/useEffect) + react-router-dom for
// routing + props passed down into the Create/Update/Delete components,
// all required explicitly by the spec.
export default function App() {
  const navigate = useNavigate();

  const [auth, setAuth] = useState({ loggedIn: false, id: null, name: "", email: "" });
  const [notices, setNotices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [checkedAuth, setCheckedAuth] = useState(false);

  // On first load (or refresh), ask the backend "am I still logged in?"
  // using whatever cookie the browser already has -- this is what makes a
  // page refresh not immediately kick you back to "logged out".
  useEffect(() => {
    (async () => {
      try {
        const data = await me();
        setAuth({ loggedIn: true, id: data.id, name: data.name, email: data.email });
      } catch {
        setAuth({ loggedIn: false, id: null, name: "", email: "" });
      } finally {
        setCheckedAuth(true);
      }
    })();
  }, []);

  // Load the notice list only once we know the user is logged in.
  useEffect(() => {
    if (!auth.loggedIn) {
      setNotices([]);
      return;
    }
    (async () => {
      setLoading(true);
      try {
        setNotices(await fetchNotices());
      } finally {
        setLoading(false);
      }
    })();
  }, [auth.loggedIn]);

  function handleLoggedIn(user) {
    setAuth({ loggedIn: true, ...user });
  }

  async function handleLogout() {
    await logout();
    setAuth({ loggedIn: false, id: null, name: "", email: "" });
    navigate("/");
  }

  async function handleAdd(payload) {
    const created = await createNotice(payload);
    setNotices((prev) => [...prev, created]);
    navigate("/");
  }

  async function handleUpdate(id, payload) {
    const updated = await updateNotice(id, payload);
    setNotices((prev) => prev.map((n) => (n.id === id ? updated : n)));
    navigate("/");
  }

  async function handleDelete(id) {
    await deleteNotice(id);
    setNotices((prev) => prev.filter((n) => n.id !== id));
    navigate("/");
  }

  if (!checkedAuth) {
    return <div className="notice">Loading...</div>;
  }

  return (
    <div>
      <Navbar auth={auth} onLogout={handleLogout} />
      <div className="container">
        <Routes>
          <Route
            path="/"
            element={<Home auth={auth} notices={notices} loading={loading} />}
          />
          <Route path="/login" element={<Login onLoggedIn={handleLoggedIn} />} />
          <Route path="/create" element={<CreateRecord onAdd={handleAdd} />} />
          <Route path="/update/:id" element={<UpdateRecord onUpdate={handleUpdate} />} />
          <Route path="/delete/:id" element={<DeleteRecord onDelete={handleDelete} />} />
        </Routes>
      </div>
    </div>
  );
}
