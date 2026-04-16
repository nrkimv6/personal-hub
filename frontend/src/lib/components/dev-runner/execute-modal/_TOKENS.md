# Execute Modal Tokens

This file freezes the layout and token contract for the dev-runner execute modal.

## Color Mapping

| Source | Target | Notes |
|---|---|---|
| `text-foreground` | `text-foreground` | Semantic token already defined in `frontend/src/app.css`. |
| `bg-background` | `bg-background` or `bg-card` | Modal surfaces should prefer `bg-card`. |
| `text-muted-foreground` | `text-muted-foreground` | Use as-is. |
| `border-border` | `border-border` | Use as-is. |
| `bg-muted` | `bg-muted` | Used for the summary banner background. |
| `bg-surface-sunken` | `bg-muted` | No dedicated token exists. |
| `bg-surface-raised` | `bg-card` | No dedicated token exists. |
| `bg-destructive text-destructive-foreground` | `bg-destructive text-destructive-foreground` | Use as-is. |
| `bg-primary text-primary-foreground` | Existing dev-runner start-button styling | Keep existing green/coded-button convention. |
| `bg-status-online` / `bg-status-offline` | `bg-success` / `bg-gray-300` | Prefer semantic success; offline stays gray. |
| State color literals | Existing 한글 status → utility mapping | Keep the current DevRunnerTab status badge mapping. |
| Progress completion color | `bg-success` | Prefer semantic token. |
| Focus ring | `focus:outline-none focus:ring-2 focus:ring-primary` | Ring token is already defined. |

Principle: prefer semantic tokens such as `bg-card`, `text-foreground`, and `text-muted-foreground` over new `bg-white` / `text-black` / `text-gray-*` literals. Existing dev-runner literals like `bg-gray-50`, `bg-green-50`, and `bg-red-50` may stay when they already match established patterns.

## Typography

| Element | Class |
|---|---|
| filename | `truncate font-mono text-sm font-medium text-foreground` |
| section label | `text-xs font-medium text-muted-foreground uppercase tracking-wider` |
| field label | `text-xs text-muted-foreground` |
| form value | `text-xs font-mono` |
| summary body | `text-sm leading-relaxed line-clamp-3` |
| meta text | `text-xs` |

## Layout

| Element | Value |
|---|---|
| modal width | `w-full max-w-2xl mx-4` |
| modal height | `max-h-[90vh] flex flex-col` |
| mobile modal | `max-sm:h-full max-sm:max-h-full max-sm:rounded-none` |
| scroll area | `flex-1 min-h-0 overflow-y-auto` |
| action bar | `sticky bottom-0 border-t` |

## Borders & Radii

| Element | Value |
|---|---|
| modal | `rounded-xl` on sm+ |
| badges / buttons | `rounded-md` |
| status dot | `h-2 w-2 rounded-full` |
| separators | `border-b` / `border-t` with `border-border` |

