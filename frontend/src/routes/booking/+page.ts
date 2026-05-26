import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = () => {
	throw redirect(301, '/monitoring?type=naver&view=schedules&sub=booking');
};
