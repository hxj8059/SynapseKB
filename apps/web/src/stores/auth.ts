import { create } from "zustand";

import type { User } from "../lib/types";

type AuthState = {
  accessToken: string | null;
  user: User | null;
  ready: boolean;
  setSession: (accessToken: string, user: User) => void;
  clear: () => void;
  markReady: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  ready: false,
  setSession: (accessToken, user) => set({ accessToken, user, ready: true }),
  clear: () => set({ accessToken: null, user: null, ready: true }),
  markReady: () => set({ ready: true }),
}));
