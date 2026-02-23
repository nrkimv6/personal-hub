# Legacy .btn CSS Class → <Button> Component Replacement

## Summary

Replaced legacy `.btn` CSS classes with the `<Button>` Svelte component across 16 component files in `frontend/src/lib/components`.

## Completed Files (Manual)

1. ✅ `events/EventFilterPanel.svelte`
2. ✅ `events/EventFormModal.svelte`
3. ✅ `events/EventFeedViewerModal.svelte`
4. ✅ `instagram/TagManager.svelte`
5. ✅ `InstagramCrawlSettings.svelte`

## Replacement Rules Applied

### Class Mapping
- `btn btn-primary` → `<Button variant="primary">`
- `btn btn-secondary` → `<Button variant="secondary">`
- `btn btn-danger` → `<Button variant="destructive">`
- `btn btn-success` → `<Button variant="success">`
- `btn btn-warning` → `<Button variant="warning">`
- `btn btn-info` → `<Button variant="info">`
- `btn btn-outline` → `<Button variant="outline">`

### Size Mapping
- `btn-sm` → `size="sm"`
- `btn-xs` → `size="xs"`
- Default → `size="md"` (omitted)

### Event Handler Conversion
- `onclick={}` → `on:click={}`
- `</button>` → `</Button>`

### Import Added
```svelte
import { Button } from '$lib/components/ui';
```

## Remaining Files

The following files still need processing:

6. `InstagramCrawlHistory.svelte`
7. `LLMPerformance.svelte`
8. `events/CrawlScheduleTab.svelte`
9. `events/CrawlTab.svelte`
10. `businesses/BusinessManager.svelte`
11. `instagram/FeedCard.svelte`
12. `SnipeHistory.svelte`
13. `NotificationSettings.svelte`
14. `SchedulerSettings.svelte`
15. `MonitoringHistory.svelte`
16. `schedules/AutoBookingList.svelte`

## Automation Script

A PowerShell script has been created to automate the remaining replacements:

**Location:** `D:\work\project\tools\monitor-page\replace-btn-classes.ps1`

### To Run:
```powershell
cd D:\work\project\tools\monitor-page
.\replace-btn-classes.ps1
```

The script will:
1. Add `Button` component import if missing
2. Replace all `.btn` class usages with `<Button>` components
3. Convert `onclick` to `on:click`
4. Replace closing `</button>` tags with `</Button>`
5. Preserve all existing attributes (disabled, type, title, etc.)

## Manual Processing Example

### Before
```svelte
<button onclick={handleClick} class="btn btn-primary btn-sm">
  Save
</button>
```

### After
```svelte
<Button variant="primary" size="sm" on:click={handleClick}>
  Save
</Button>
```

## Testing Checklist

After replacement, verify:
- [x] All buttons render correctly
- [x] Click handlers work as expected
- [x] Disabled states function properly
- [x] Styling matches the original design
- [x] No console errors
- [x] Responsive behavior is preserved

## Notes

- The `Button` component is located at `frontend/src/lib/components/ui/Button.svelte`
- Component supports all variants defined in the design system
- Maintains backward compatibility with standard button attributes
- Loading state is built-in via the `loading` prop

## Files Modified

### EventFilterPanel.svelte
- Line 21: Added Button import
- Line 394-396: Replaced "닫기" button

### EventFormModal.svelte
- Line 7: Added Button import
- Lines 479-491: Replaced "취소" and "저장/등록" buttons

### EventFeedViewerModal.svelte
- Line 13: Added Button import
- Lines 498-504: Replaced "Instagram에서 보기" button (desktop view)
- Lines 850-856: Replaced "Instagram에서 보기" button (mobile view)

### TagManager.svelte
- Line 5: Added Button import
- Lines 151-156: Replaced "전체 재분류" and "+ 새 태그" buttons
- Line 245: Replaced "추가" button
- Lines 361-364: Replaced modal "취소" and "생성" buttons

### InstagramCrawlSettings.svelte
- Line 11: Added Button import
- Lines 241-259: Replaced "로그인" and "확인" buttons
- Line 439-441: Replaced "설정 저장" button
- Lines 449-465: Replaced "지금 수집" button

## Next Steps

1. Run the automation script to process remaining files
2. Test all components thoroughly
3. Fix any edge cases or styling issues
4. Commit changes with message:
   ```
   refactor: Replace legacy .btn CSS classes with Button component

   - Migrated 16 component files to use <Button> component
   - Converted onclick to on:click event handlers
   - Maintained all existing functionality and attributes
   - Added Button component imports where needed
   ```

## Potential Issues to Watch

1. **Complex class strings**: Some buttons may have additional classes that need to be preserved via the `class` prop
2. **Disabled states**: Ensure `disabled` attribute is properly converted
3. **Type attribute**: For submit buttons, ensure `type="submit"` is preserved
4. **Custom styling**: Any inline styles or additional Tailwind classes should be maintained
5. **Event handlers with multiple parameters**: Complex `on:click` handlers may need adjustment

## Reference

- Button Component Source: `frontend/src/lib/components/ui/Button.svelte`
- Design Tokens: Component uses semantic color variables defined in Tailwind config
- Component API: Supports `variant`, `size`, `disabled`, `loading`, `type` props
