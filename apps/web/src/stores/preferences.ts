import { create } from "zustand";
import { persist } from "zustand/middleware";

type Preferences = {
  theme: "light" | "dark";
  toggleTheme: () => void;
};

export const usePreferences = create<Preferences>()(
  persist(
    (set) => ({
      theme: "light",
      toggleTheme: () =>
        set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),
    }),
    { name: "synapsekb-ui-preferences" },
  ),
);
