// frontend/src/routes/classify/lib/categoryUtils.ts
import { fetchWithTimeout } from '$lib/api/client';

export interface Category {
  id: number;
  name: string;
  full_path: string;
  parent_id: number | null;
  children?: Category[];
}

/**
 * 트리 구조 카테고리 배열을 id → full_path 맵으로 변환
 */
export function flattenCategories(categories: Category[]): Map<number, string> {
  const map = new Map<number, string>();
  function walk(cats: Category[]) {
    for (const cat of cats) {
      map.set(cat.id, cat.full_path);
      if (cat.children) walk(cat.children);
    }
  }
  walk(categories);
  return map;
}

/**
 * /api/ic/categories/tree 호출 → Map<number, string> 반환
 */
export async function loadCategoryMap(): Promise<Map<number, string>> {
  const res = await fetchWithTimeout('/api/ic/categories/tree');
  const data = await res.json();
  return flattenCategories(data);
}

/**
 * categoryMap에서 id에 해당하는 카테고리 경로 반환 (없으면 '미분류')
 */
export function getCategoryName(
  categoryMap: Map<number, string>,
  categoryId: number | null | undefined
): string {
  if (!categoryId) return '미분류';
  return categoryMap.get(categoryId) ?? '미분류';
}
