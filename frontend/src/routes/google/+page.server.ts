import { redirect } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';

export const prerender = false;

export function load({ url }: RequestEvent) {
  const tab = url.searchParams.get('tab');
  const target = tab ? `/collect/google?tab=${tab}` : '/collect/google';
  redirect(301, target);
}
