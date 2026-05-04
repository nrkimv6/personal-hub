import { redirect } from '@sveltejs/kit';
import { getExpoRouteContract, resolvePublicRouteMode } from '$lib/utils/publicRouteMode';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, url }) => {
  const mode = await resolvePublicRouteMode({ fetch, url });
  const routeContract = getExpoRouteContract({ mode, url });

  if (routeContract.shouldRedirectExpoAuthor) {
    throw redirect(302, '/expo/coffee-expo-2026');
  }

  return {};
};
