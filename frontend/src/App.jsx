import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";

import Navbar from "./components/Navbar.jsx";
import Login from "./pages/Login.jsx";
import Home from "./pages/Home.jsx";
import CreateRecord from "./pages/CreateRecord.jsx";
import UpdateRecord from "./pages/UpdateRecord.jsx";

import { me, logout } from "./api.js";
import { fetchNotices, clearNotices } from "./features/notices/noticesSlice.js";

// HW5: the notice list no longer lives in useState here -- it lives in the
// Redux store. App only keeps the login state and decides when to load.
export default function App() {
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [auth, setAuth] = useState({ loggedIn: false, id: null, name: "", email: "" });
  const [checkedAuth, setCheckedAuth] = useState(false);

  // On first load (or refresh), ask the backend "am I still logged in?"
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

  // Logged in -> dispatch the fetch thunk. Logged out -> empty the store.
  useEffect(() => {
    if (auth.loggedIn) dispatch(fetchNotices());
    else dispatch(clearNotices());
  }, [auth.loggedIn, dispatch]);

  function handleLoggedIn(user) {
    setAuth({ loggedIn: true, ...user });
  }

  async function handleLogout() {
    await logout();
    setAuth({ loggedIn: false, id: null, name: "", email: "" });
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
          <Route path="/" element={<Home auth={auth} />} />
          <Route path="/login" element={<Login onLoggedIn={handleLoggedIn} />} />
          <Route path="/create" element={<CreateRecord />} />
          <Route path="/update" element={<UpdateRecord />} />
          <Route path="/update/:id" element={<UpdateRecord />} />
        </Routes>
      </div>
    </div>
  );
}
