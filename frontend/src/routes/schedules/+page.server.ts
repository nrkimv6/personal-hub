import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const prerender = false;

export const load: PageServerLoad = ({ url }) => {
  // 기존 쿼리 파라미터를 sub 파라미터로 변환
  const tab = url.searchParams.get('tab');
  let redirectUrl = '/naver/schedules';

  if (tab) {
    redirectUrl += `?sub=${tab}`;
  }

  throw redirect(301, redirectUrl);
};
