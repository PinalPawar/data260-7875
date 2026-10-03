import { configureStore } from "@reduxjs/toolkit";
import noticesReducer from "../features/notices/noticesSlice.js";

// HW5 Part 1.III.1: one Redux store for the whole app. `notices` is the
// slice that holds the primary domain entity (recall notices).
export const store = configureStore({
  reducer: {
    notices: noticesReducer,
  },
});
