import React from "react";
import { Link } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { deleteNotice } from "../features/notices/noticesSlice.js";

// HW5 Part 1.III.3 + 5: the list is read straight from Redux state, so it
// re-renders by itself whenever a notice is created, updated or deleted.
export default function Home({ auth }) {
  const dispatch = useDispatch();
  const { items, loading, error } = useSelector((state) => state.notices);

  if (!auth.loggedIn) {
    return (
      <div className="card">
        <div className="card-header">
          <div className="page-title">Recall Notices</div>
        </div>
        <div className="card-body">
          <div className="notice">Login required to view recall notices.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Recall Notices ({items.length} shown)</div>
        <div className="actions">
          <Link className="btn" to="/update">
            Update by ID
          </Link>
          <Link className="btn primary" to="/create">
            + Add Record
          </Link>
        </div>
      </div>

      <div className="card-body">
        {error && <div className="notice error">{error}</div>}

        {loading ? (
          <div className="notice">Loading...</div>
        ) : items.length === 0 ? (
          <div className="notice">No recall notices yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Code</th>
                <th>Product</th>
                <th>Manufacturer</th>
                <th>Units</th>
                <th>Category</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.notice_code}</td>
                  <td>{n.product}</td>
                  <td>{n.manufacturer_name}</td>
                  <td>{n.units_affected}</td>
                  <td>{n.category}</td>
                  <td className="actions">
                    <Link className="btn" to={`/update/${n.id}`}>
                      Update
                    </Link>
                    <button className="btn danger" onClick={() => dispatch(deleteNotice(n.id))}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
