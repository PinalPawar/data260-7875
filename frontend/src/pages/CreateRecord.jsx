import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { createNotice } from "../features/notices/noticesSlice.js";
import NoticeForm, { EMPTY_NOTICE, toPayload } from "./NoticeForm.jsx";

// HW5 Part 1.III.4: on submit, dispatch the createNotice thunk. If it
// succeeds, the slice has already added the new notice to Redux state, so
// going back to Home shows it without re-fetching.
export default function CreateRecord() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_NOTICE);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await dispatch(createNotice(toPayload(form))).unwrap();
      navigate("/");
    } catch (message) {
      setError(message); // e.g. "Notice code RCL-... already exists"
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Report a Recall</div>
      </div>
      <div className="card-body">
        <NoticeForm
          form={form}
          setForm={setForm}
          onSubmit={handleSubmit}
          submitLabel="Submit Recall Notice"
          error={error}
        />
      </div>
    </div>
  );
}
