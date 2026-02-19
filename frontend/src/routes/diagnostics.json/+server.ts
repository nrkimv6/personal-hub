import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { readFile } from 'fs/promises';
import { join } from 'path';

export const prerender = false;

export const GET: RequestHandler = async () => {
	try {
		const filePath = join(process.cwd(), 'static', 'diagnostics.json');
		const content = await readFile(filePath, 'utf-8');
		return json(JSON.parse(content));
	} catch {
		return json({ status: 'api_healthy' });
	}
};
