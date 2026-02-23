import { redirect } from '@sveltejs/kit';

export const prerender = false;

export function load() {
  redirect(301, '/collect/google?tab=results');
}
