import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchNoticeById } from "../api.js";

const CATEGORIES = [
  "supplyShortage",
  "bacterialContamination",
  "foreignMaterial",
  "mislabelling",
];

// HW4 Part 1, Section III: rendered on /update. Uses /update/:id (the id
// comes from the URL, via the "Update" link on Home.jsx) rather than a bare
// /update -- that way refreshing the page or sharing the link still works,
// instead of relying on data only passed in memory. Talking point if asked
// "why not just /update": React state passed between pages disappears on a
// page refresh; the id in the URL doesn't.
export default function UpdateRecord({ onUpdate }) {
  const { id } = useParams();
  const noticeId = Number(id);

  const [form, setForm] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const notice = await fetchNoticeById(noticeId);
        setForm(notice);
      } catch (err) {
        setError("Could not load that notice.");
      }
    })();
  }, [noticeId]);

  function set(field) {
    return (e) => setForm({ ...form, [field]: e.target.value });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await onUpdate(noticeId, form);
    } catch (err) {
      setError("Could not update the notice.");
    }
  }

  if (error) return <div className="notice error">{error}</div>;
  if (!form) return <div className="notice">Loading...</div>;

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Update Recall Notice (ID: {noticeId})</div>
      </div>

      <div className="card-body">
        <form className="form" onSubmit={handleSubmit}>
          <label>
            Product (primary field)
            <input value={form.product} onChange={set("product")} required />
          </label>

          <label>
            Manufacturer (secondary field)
            <input value={form.manufacturer} onChange={set("manufacturer")} required />
          </label>

          <label>
            Contact email
            <input type="email" value={form.email} onChange={set("email")} required />
          </label>

          <label>
            Description
            <textarea value={form.description} onChange={set("description")} required />
          </label>

          <label>
            Category
            <select value={form.category} onChange={set("category")}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          {error && <div className="notice error">{error}</div>}

          <button className="btn primary" type="submit">
            Save Changes
          </button>
        </form>
      </div>
    </div>
  );
}
