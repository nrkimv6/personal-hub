@{
    Source = 'D:\work\project\service\wtools\common\docs\guide\project-management\worktree-write-scope.md'
    WriteTargetResult = @{
        InScope             = 'in_scope'
        RerouteRequired     = 'reroute_required'
        RootDirtyOnly       = 'root_dirty_only'
        InvalidOwnerContext = 'invalid_owner_context'
    }
    RootWorktreeAllowPatterns = @(
        '^TODO\.md$',
        '^docs/DONE\.md$',
        '^docs/(plan|archive)/',
        '^\.worktrees/plans(?:/|$)',
        '^\.worktrees/impl-[^/]+(?:/|$)'
    )
    ImplementationScopeExamples = @(
        '.claude/skills/',
        '.agents/skills/',
        'scripts/git-hooks/',
        'app/',
        'frontend/',
        'tests/'
    )
}
