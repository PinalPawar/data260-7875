import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import api from "../../api.js";

// Turn any axios error into one readable sentence for the UI.
function errorMessage(err, fallback) {
  const detail = err.response?.data?.detail;
  if (typeof detail === "string") return detail; // our 404 / 409 messages
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors: [{loc: ["body","notice_code"], msg: "..."}]
    return detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ");
  }
  if (err.response?.status === 401) return "Login required";
  return err.message ? `${fallback}: ${err.message}` : fallback;
}

// --- Async thunks (HW5 Part 1.III.2): each one calls a FastAPI endpoint ---
export const fetchNotices = createAsyncThunk("notices/fetch", async (_, thunkAPI) => {
  try {
    const res = await api.get("/api/notices", { params: { limit: 50 } });
    return res.data;
  } catch (err) {
    return thunkAPI.rejectWithValue(errorMessage(err, "Failed to fetch notices"));
  }
});

export const createNotice = createAsyncThunk("notices/create", async (payload, thunkAPI) => {
  try {
    const res = await api.post("/api/notices", payload);
    return res.data;
  } catch (err) {
    return thunkAPI.rejectWithValue(errorMessage(err, "Failed to create notice"));
  }
});

export const updateNotice = createAsyncThunk("notices/update", async ({ id, payload }, thunkAPI) => {
  try {
    const res = await api.put(`/api/notices/${id}`, payload);
    return res.data;
  } catch (err) {
    return thunkAPI.rejectWithValue(errorMessage(err, "Failed to update notice"));
  }
});

export const deleteNotice = createAsyncThunk("notices/delete", async (id, thunkAPI) => {
  try {
    await api.delete(`/api/notices/${id}`);
    return id;
  } catch (err) {
    return thunkAPI.rejectWithValue(errorMessage(err, "Failed to delete notice"));
  }
});

// --- Slice (HW5 Part 1.III.1): the notices state + how each action changes it
const noticesSlice = createSlice({
  name: "notices",
  initialState: { items: [], loading: false, error: null },
  reducers: {
    clearNotices: (state) => {
      state.items = [];
      state.error = null;
    },
    clearError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // fetch
      .addCase(fetchNotices.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchNotices.fulfilled, (state, action) => {
        state.loading = false;
        state.items = action.payload;
      })
      .addCase(fetchNotices.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload;
      })
      // add (newest first, same order the API returns)
      .addCase(createNotice.fulfilled, (state, action) => {
        state.items.unshift(action.payload);
        state.error = null;
      })
      .addCase(createNotice.rejected, (state, action) => {
        state.error = action.payload;
      })
      // update
      .addCase(updateNotice.fulfilled, (state, action) => {
        const index = state.items.findIndex((n) => n.id === action.payload.id);
        if (index !== -1) state.items[index] = action.payload;
        state.error = null;
      })
      .addCase(updateNotice.rejected, (state, action) => {
        state.error = action.payload;
      })
      // delete
      .addCase(deleteNotice.fulfilled, (state, action) => {
        state.items = state.items.filter((n) => n.id !== action.payload);
        state.error = null;
      })
      .addCase(deleteNotice.rejected, (state, action) => {
        state.error = action.payload;
      });
  },
});

export const { clearNotices, clearError } = noticesSlice.actions;
export default noticesSlice.reducer;
