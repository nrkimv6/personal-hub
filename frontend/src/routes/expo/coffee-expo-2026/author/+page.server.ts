import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch }) => {
  try {
    const response = await fetch('/api/v1/system/mode', {
      headers: {
        Accept: 'application/json'
      }
    });

    if (response.ok) {
      const payload = await response.json();
      if (payload?.mode === 'public') {
        redirect(302, '/expo/coffee-expo-2026');
      }
    }
  } catch {
    // If mode lookup fails, keep the admin helper reachable in local/dev usage.
  }

  return {};
};
