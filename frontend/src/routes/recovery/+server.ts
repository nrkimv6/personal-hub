import { json } from '@sveltejs/kit';
import { execSync, spawn } from 'child_process';
import type { RequestHandler } from './$types';

const WMI_CHECK_TIMEOUT_MS = 5000;
const API_CHECK_TIMEOUT_MS = 3000;

/** WMI 헬스체크: python -c "import platform; platform.machine()" 을 타임아웃 내에 실행 */
function checkWmiHealth(): { healthy: boolean; error?: string } {
	try {
		execSync('python -c "import platform; platform.machine()"', {
			timeout: WMI_CHECK_TIMEOUT_MS,
			stdio: 'pipe'
		});
		return { healthy: true };
	} catch (err: unknown) {
		const msg = err instanceof Error ? err.message : String(err);
		const isTimeout = msg.includes('ETIMEDOUT') || msg.includes('timed out') || msg.includes('timeout');
		return { healthy: false, error: isTimeout ? 'timeout' : msg };
	}
}

/** API 서버 상태 체크 */
async function checkApiHealth(port: number): Promise<{ up: boolean; error?: string }> {
	try {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), API_CHECK_TIMEOUT_MS);
		try {
			const res = await fetch(`http://localhost:${port}/health`, { signal: controller.signal });
			return { up: res.ok };
		} finally {
			clearTimeout(timer);
		}
	} catch (err: unknown) {
		return { up: false, error: err instanceof Error ? err.message : String(err) };
	}
}

/** GET /recovery — WMI 상태 + API 서버 상태 반환 */
export const GET: RequestHandler = async () => {
	const wmi = checkWmiHealth();
	const [api8000, api8001] = await Promise.all([
		checkApiHealth(8000),
		checkApiHealth(8001)
	]);

	return json({
		wmi: { healthy: wmi.healthy, error: wmi.error ?? null },
		api: {
			public: { port: 8000, up: api8000.up, error: api8000.error ?? null },
			admin: { port: 8001, up: api8001.up, error: api8001.error ?? null }
		},
		timestamp: new Date().toISOString()
	});
};

/** POST /recovery — WMI 재시작 실행 */
export const POST: RequestHandler = async ({ request }) => {
	let action = 'restart-wmi';
	try {
		const body = await request.json();
		action = body.action ?? action;
	} catch {
		// body 없으면 기본값 사용
	}

	if (action === 'restart-wmi') {
		try {
			execSync('powershell -Command "Restart-Service winmgmt -Force"', {
				timeout: 20000,
				stdio: 'pipe'
			});

			// 재시작 후 WMI 재체크
			await new Promise((r) => setTimeout(r, 3000));
			const wmi = checkWmiHealth();

			return json({
				success: true,
				action,
				wmi_after: { healthy: wmi.healthy, error: wmi.error ?? null },
				message: wmi.healthy ? 'WMI 재시작 완료. 서비스가 정상입니다.' : 'WMI 재시작 완료. 상태 재확인 필요.'
			});
		} catch (err: unknown) {
			const msg = err instanceof Error ? err.message : String(err);
			return json(
				{
					success: false,
					action,
					error: msg,
					message: 'WMI 재시작 실패. 관리자 권한으로 실행 중인지 확인하세요.'
				},
				{ status: 500 }
			);
		}
	}

	return json({ success: false, error: `Unknown action: ${action}` }, { status: 400 });
};
