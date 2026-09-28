import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchNoticeById } from "../api.js";

// HW4 Part 1, Section IV: rendered on /delete (here /delete/:id, same
// reasoning as UpdateRecord). Shows what you're about to delete before you
// confirm it, rather than deleting on page load.
export default function DeleteRecord({ onDelete }) {
  const { id } = useParams();
  const noticeId = Number(id);

  const [notice, setNotice] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchNoticeById(noticeId);
        setNotice(data);
      } catch {
        setError("Notice not found (or already deleted).");
      }
    })();
  }, [noticeId]);

  async function handleDelete() {
    await onDelete(noticeId);
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="page-title">Delete Recall Notice</div>
      </div>

      <div className="card-body">
        {error && <div className="notice error">{error}</div>}

        {notice && (
          <>
            <p>
              Delete recall notice for <strong>{notice.product}</strong> ({notice.manufacturer})?
              This cannot be undone.
            </p>
            <button className="btn danger" onClick={handleDelete}>
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
