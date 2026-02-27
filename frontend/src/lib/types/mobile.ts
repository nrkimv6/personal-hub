export interface MobileTarget {
    id: number;
    name: string;
    url: string;
    crawl_type: string;
    parse_config: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export interface MobileRunResult {
    collected_count: number;
    new_count: number;
    updated_count: number;
    duration_seconds: number;
}

export interface MobileRun {
    id: number;
    target_id: number;
    target_name: string;
    status: 'completed' | 'failed' | 'running';
    started_at: string;
    completed_at: string | null;
    result: MobileRunResult | null;
    error_message: string | null;
}

export interface MobileItem {
    id: number;
    target_id: number;
    target_name?: string;
    run_id: number | null;
    title: string;
    item_url: string | null;
    image_url: string | null;
    attributes: Record<string, unknown>;
    raw_html: string | null;
    first_seen_at: string;
    last_seen_at: string;
    is_changed: boolean;
    created_at: string;
    updated_at: string;
}

export interface MobileStats {
    total_items: number;
    new_items_count: number;
    changed_items_count: number;
    latest_run_at: string | null;
}

export interface MobileSchedule {
    id: number;
    target_type: string;
    target_config: {
        mobile_crawl_target_id: number;
        [key: string]: unknown;
    };
    interval_seconds: number;
    enabled: boolean;
    last_run?: string;
    next_run?: string;
    created_at: string;
}
