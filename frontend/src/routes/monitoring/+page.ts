import { redirect } from '@sveltejs/kit';
import { resolvePublicRouteMode } from '$lib/utils/publicRouteMode';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  // localhost fallback은 resolvePublicRouteMode() 내부에서 fetch 실패/비정상 응답까지 함께 처리한다.
  if (await resolvePublicRouteMode({ fetch, url }) === 'public') {
    throw redirect(302, '/events');
  }

  return {};
};
