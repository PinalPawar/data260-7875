import React from "react";
import { Link } from "react-router-dom";

// "and/or disable/hide navigation buttons like Add Record" (HW4 spec) --
// this hides the Add Record link entirely when logged out, and swaps
// Login <-> Logout depending on auth state.
export default function Navbar({ auth, onLogout }) {
  return (
    <nav className="navbar">
      <Link className="brand" to="/">
        Grocery Recall Notices
      </Link>

      <div className="nav-links">
        {auth.loggedIn && (
          <Link className="btn" to="/create">
            + Add Record
          </Link>
        )}

        {auth.loggedIn ? (
          <>
            <span className="nav-user">{auth.name}</span>
            <button className="btn danger" onClick={onLogout}>
              Logout
            </button>
          </>
        ) : (
          <Link className="btn primary" to="/login">
            Login
          </Link>
        )}
      </div>
    </nav>
  );
}
