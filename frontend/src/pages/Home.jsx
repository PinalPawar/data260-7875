import React from "react";
import { Link } from "react-router-dom";

// HW4 Part 1, Section I: "The Home component should be rendered when the
// user is on the root route /." Displays all records; shows "Login
// required" instead of data when the user isn't authenticated, since the
// backend would refuse the /api/notices call anyway (401).
export default function Home({ auth, notices, loading, onDelete }) {
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
        <div className="page-title">Recall Notices</div>
        <Link className="btn primary" to="/create">
          + Add Record
        </Link>
      </div>

      <div className="card-body">
        {loading ? (
          <div className="notice">Loading...</div>
        ) : notices.length === 0 ? (
          <div className="notice">No recall notices yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Product</th>
                <th>Manufacturer</th>
                <th>Category</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.product}</td>
                  <td>{n.manufacturer}</td>
                  <td>{n.category}</td>
                  <td className="actions">
                    <Link className="btn" to={`/update/${n.id}`}>
                      Update
                    </Link>
                    <Link className="btn danger" to={`/delete/${n.id}`}>
                      Delete
                    </Link>
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
