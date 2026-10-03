import React, { useEffect, useState } from "react";
import { fetchManufacturers } from "../api.js";

export const CATEGORIES = [
  "supplyShortage",
  "bacterialContamination",
  "foreignMaterial",
  "mislabelling",
];

export const EMPTY_NOTICE = {
  product: "",
  notice_code: "",
  units_affected: 0,
  manufacturer_id: "",
  email: "",
  description: "",
  category: CATEGORIES[0],
};

// The fields shared by the Create and Update screens. The manufacturer is
// picked from a dropdown filled from GET /api/manufacturers, so the form
// can only ever send a manufacturer_id that really exists.
export default function NoticeForm({ form, setForm, onSubmit, submitLabel, error }) {
  const [manufacturers, setManufacturers] = useState([]);

  useEffect(() => {
    fetchManufacturers().then(setManufacturers).catch(() => setManufacturers([]));
  }, []);

  function set(field) {
    return (e) => setForm({ ...form, [field]: e.target.value });
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <label>
        Product (primary field)
        <input value={form.product} onChange={set("product")} required />
      </label>

      <label>
        Notice code (unique, format RCL-2026-00001)
        <input
          value={form.notice_code}
          onChange={set("notice_code")}
          placeholder="RCL-2026-90001"
          required
        />
      </label>

      <label>
        Units affected
        <input type="number" min="0" value={form.units_affected} onChange={set("units_affected")} />
      </label>

      <label>
        Manufacturer
        <select value={form.manufacturer_id} onChange={set("manufacturer_id")} required>
          <option value="">-- choose a manufacturer --</option>
          {manufacturers.map((m) => (
            <option key={m.id} value={m.id}>
              {m.code} - {m.name}
            </option>
          ))}
        </select>
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
        {submitLabel}
      </button>
    </form>
  );
}

// Convert the form's text values into what the API expects (numbers).
export function toPayload(form) {
  return {
    product: form.product,
    notice_code: form.notice_code,
    units_affected: Number(form.units_affected) || 0,
    manufacturer_id: Number(form.manufacturer_id),
    email: form.email,
    description: form.description,
    category: form.category,
  };
}
