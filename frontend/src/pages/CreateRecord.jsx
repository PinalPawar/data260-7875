import React, { useState } from "react";

const CATEGORIES = [
  "supplyShortage",
  "bacterialContamination",
  "foreignMaterial",
  "mislabelling",
];

// HW4 Part 1, Section II: rendered on /create. "primary field" = product,
// "secondary field" = manufacturer (per the spec's wording); email/
// description/category are the extra fields this domain already had from
// HW1/HW2 (DOMAIN_SCHEMA.md), so a real recall notice can be created.
export default function CreateRecord({ onAdd }) {
  const [form, setForm] = useState({
    product: "",
    manufacturer: "",
    email: "",
    description: "",
    category: CATEGORIES[0],
  });
  const [error, setError] = useState("");

  function set(field) {
    return (e) => setForm({ ...form, [field]: e.target.value });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await onAdd(form); // parent (App.jsx) calls the API + redirects to "/"
    } catch (err) {
      setError("Could not create the notice. Check the backend logs.");
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Report a Recall</div>
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
            Submit Recall Notice
          </button>
        </form>
      </div>
    </div>
  );
}
