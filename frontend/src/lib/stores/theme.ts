import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

export const theme = writable<Theme>('light');

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
  const resolved: Theme = saved === 'dark' ? 'dark' : 'light';
  applyTheme(resolved);
  theme.set(resolved);
}

export function setTheme(t: Theme) {
  localStorage.setItem(STORAGE_KEY, t);
  applyTheme(t);
  theme.set(t);
}

export function toggleTheme() {
  const current = localStorage.getItem(STORAGE_KEY) as Theme | null;
  setTheme(current === 'dark' ? 'light' : 'dark');
}

function applyTheme(t: Theme) {
  if (t === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}
