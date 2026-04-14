import { redirect } from '@sveltejs/kit';
import { resolvePublicRouteMode } from '$lib/utils/publicRouteMode';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => {
  if (await resolvePublicRouteMode() === 'public') {
    throw redirect(302, '/events');
  }

  return {};
};
