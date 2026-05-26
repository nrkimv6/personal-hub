import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const prerender = false;

export const load: PageServerLoad = ({ url }) => {
  const tab = url.searchParams.get('tab');
  const target = new URL('/monitoring', url.origin);

  for (const [key, value] of url.searchParams) {
    if (key !== 'tab') {
      target.searchParams.append(key, value);
    }
  }

  target.searchParams.set('type', 'naver');
  target.searchParams.set('view', 'schedules');
  if (tab) {
    target.searchParams.set('sub', tab);
  }

  throw redirect(301, `${target.pathname}${target.search}`);
};
