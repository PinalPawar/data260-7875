import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { fetchNoticeById } from "../api.js";
import { updateNotice } from "../features/notices/noticesSlice.js";
import NoticeForm, { toPayload } from "./NoticeForm.jsx";

// HW5 Part 1.III.4: "a form to update an existing record (select by ID)".
// Type an ID and press Load (or arrive from Home's Update link, which puts
// the ID in the URL). On submit, dispatch the updateNotice thunk.
export default function UpdateRecord() {
  const { id } = useParams();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const items = useSelector((state) => state.notices.items);

  const [idInput, setIdInput] = useState(id || "");
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");

  async function load(rawId) {
    const noticeId = Number(rawId);
    setError("");
    setForm(null);
    if (!noticeId) return;
    // Use the copy already in Redux state if we have it; otherwise ask the API.
    const cached = items.find((n) => n.id === noticeId);
    try {
      setForm(cached || (await fetchNoticeById(noticeId)));
    } catch {
      setError(`Notice ${noticeId} not found.`);
    }
  }

  useEffect(() => {
    if (id) load(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await dispatch(updateNotice({ id: form.id, payload: toPayload(form) })).unwrap();
      navigate("/");
    } catch (message) {
      setError(message);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Update Recall Notice</div>
      </div>

      <div className="card-body">
        <div className="form">
          <label>
            Notice ID
            <input
              type="number"
              min="1"
              value={idInput}
              onChange={(e) => setIdInput(e.target.value)}
              placeholder="e.g. 5001"
            />
          </label>
          <button className="btn" type="button" onClick={() => load(idInput)}>
            Load
          </button>
        </div>

        {!form && error && <div className="notice error">{error}</div>}

        {form && (
          <>
            <p>
              Editing notice <strong>{form.id}</strong> ({form.notice_code})
            </p>
            <NoticeForm
              form={form}
              setForm={setForm}
              onSubmit={handleSubmit}
              submitLabel="Save Changes"
              error={error}
            />
          </>
        )}
      </div>
    </div>
  );
}
