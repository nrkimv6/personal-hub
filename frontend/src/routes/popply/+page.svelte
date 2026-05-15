<script lang="ts">
	import { onMount } from 'svelte';
	import { popplyReservationApi, type PopplySchedule, type PopplyTarget } from '$lib/api/popplyReservation';

	let targets: PopplyTarget[] = [];
	let schedules: PopplySchedule[] = [];
	let sourceUrl = '';
	let targetName = '';
	let selectedTargetId = '';
	let scheduleDate = '';
	let loading = false;
	let error = '';

	async function load() {
		loading = true;
		error = '';
		try {
			[targets, schedules] = await Promise.all([
				popplyReservationApi.listTargets(),
				popplyReservationApi.listSchedules()
			]);
			if (!selectedTargetId && targets[0]) selectedTargetId = String(targets[0].id);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	async function createTarget() {
		if (!sourceUrl.trim()) return;
		await popplyReservationApi.createTarget({
			source_url: sourceUrl.trim(),
			name: targetName.trim() || undefined
		});
		sourceUrl = '';
		targetName = '';
		await load();
	}

	async function createSchedule() {
		if (!selectedTargetId || !scheduleDate) return;
		await popplyReservationApi.createSchedules({
			biz_item_id: Number(selectedTargetId),
			dates: [scheduleDate]
		});
		scheduleDate = '';
		await load();
	}

	async function toggleSchedule(schedule: PopplySchedule) {
		if (schedule.is_enabled) await popplyReservationApi.disableSchedule(schedule.id);
		else await popplyReservationApi.enableSchedule(schedule.id);
		await load();
	}

	async function checkNow(schedule: PopplySchedule) {
		await popplyReservationApi.checkNow(schedule.id);
		await load();
	}

	onMount(load);
</script>

<svelte:head>
	<title>POPPLY 예약</title>
</svelte:head>

<main class="mx-auto max-w-6xl space-y-6 p-6">
	<header class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold text-slate-900">POPPLY 예약</h1>
		<button class="rounded border px-3 py-2 text-sm" on:click={load} disabled={loading}>새로고침</button>
	</header>

	{#if error}
		<p class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
	{/if}

	<section class="grid gap-3 md:grid-cols-[1fr_220px_120px]">
		<input class="rounded border px-3 py-2" bind:value={sourceUrl} placeholder="POPPLY 예약 URL" />
		<input class="rounded border px-3 py-2" bind:value={targetName} placeholder="이름" />
		<button class="rounded bg-slate-900 px-3 py-2 text-sm text-white" on:click={createTarget}>등록</button>
	</section>

	<section class="grid gap-3 md:grid-cols-[1fr_180px_120px]">
		<select class="rounded border px-3 py-2" bind:value={selectedTargetId}>
			{#each targets as target}
				<option value={target.id}>{target.name} · {target.store_id}</option>
			{/each}
		</select>
		<input class="rounded border px-3 py-2" type="date" bind:value={scheduleDate} />
		<button class="rounded bg-slate-900 px-3 py-2 text-sm text-white" on:click={createSchedule}>일정 추가</button>
	</section>

	<section class="overflow-hidden rounded border">
		<table class="w-full text-left text-sm">
			<thead class="bg-slate-50 text-slate-600">
				<tr>
					<th class="p-3">대상</th>
					<th class="p-3">날짜</th>
					<th class="p-3">상태</th>
					<th class="p-3">마지막 체크</th>
					<th class="p-3"></th>
				</tr>
			</thead>
			<tbody>
				{#each schedules as schedule}
					<tr class="border-t">
						<td class="p-3">{schedule.item_name}</td>
						<td class="p-3">{schedule.date}</td>
						<td class="p-3">{schedule.is_enabled ? (schedule.last_event_status ?? 'idle') : 'disabled'}</td>
						<td class="p-3">{schedule.last_check_time ?? '-'}</td>
						<td class="space-x-2 p-3 text-right">
							<button class="rounded border px-2 py-1" on:click={() => toggleSchedule(schedule)}>
								{schedule.is_enabled ? '비활성' : '활성'}
							</button>
							<button class="rounded border px-2 py-1" on:click={() => checkNow(schedule)}>체크</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</section>
</main>
