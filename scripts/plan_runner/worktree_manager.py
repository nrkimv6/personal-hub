"""
WorktreeManager ??git worktree ?앸챸二쇨린 愿由??좏떥由ы떚

媛?plan-runner ?몄뒪?댁뒪瑜?寃⑸━??git worktree?먯꽌 ?ㅽ뻾?섍린 ?꾪븳 ?ы띁 ?대옒??
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import shutil
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


def _run_git(args: list, cwd: Optional[str] = None, **kwargs) -> subprocess.CompletedProcess:
    """git subprocess ?ы띁 ??`-c safe.directory=*` ?먮룞 二쇱엯.

    NSSM ?쒕퉬??SYSTEM 怨꾩젙)?먯꽌 ?ㅽ뻾 ??git 2.35.2+??CVE-2022-24765 ????뺤콉?쇰줈
    ?대뜑 ?뚯쑀沅?遺덉씪移섍? 媛먯??섏뼱 嫄곕??섎뒗 臾몄젣瑜?諛⑹??쒕떎.

    cwd=None ???꾨줈?몄뒪 ?꾩옱 ?붾젆?좊━瑜??ъ슜 (list_worktrees ??cwd 遺덊븘?뷀븳 ?몄텧 ?명솚).

    ?좑툘 以묐났 二쇱쓽: app/modules/dev_runner/services/git_utils.py?먮룄 ?숈씪??safe.directory
    二쇱엯 濡쒖쭅???덈떎. scripts/? app/ 媛?import 遺덇?濡?以묐났??遺덇??쇳븯誘濡? ?섎굹瑜??섏젙????
    諛섎뱶???ㅻⅨ 履쎈룄 ?④퍡 ?뺤씤??寃?
    """
    cmd = ["git", "-c", "safe.directory=*"] + args
    return subprocess.run(cmd, cwd=cwd, **kwargs)


class WorktreeError(Exception):
    pass


def _is_linked_worktree(project_root: Path) -> bool:
    """?꾩옱 project_root媛 linked worktree?몄? ?먮퀎."""
    # 硫붿씤 worktree??.git ?붾젆?좊━, linked worktree??.git ?뚯씪(?ъ씤?? ?뺥깭??
    return (project_root / ".git").is_file()


def ensure_main_branch(project_root: Path) -> None:
    """硫붿씤 ?덊룷媛 main 釉뚮옖移섏씤吏 ?뺤씤?섍퀬, ?꾨땲硫?main?쇰줈 蹂듦?.

    main?대㈃ 利됱떆 return (no-op).
    uncommitted changes媛 ?덉뼱 checkout 遺덇??ν븯硫?WorktreeError 諛쒖깮.
    """
    result = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
    )
    branch = result.stdout.strip(); print(f"DEBUG: branch={branch!r}, rc={result.returncode}")
    if branch == "main":
        return
    logger.warning(f"[WorktreeManager] 硫붿씤 ?덊룷媛 {branch}???덉쓬, main?쇰줈 蹂듦?")
    checkout = _run_git(
        ["checkout", "main"],
        cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
    )
    if checkout.returncode != 0:
        stderr = (checkout.stderr or "").strip()
        # linked worktree?먯꽌??main???ㅻⅨ worktree??checkout?섏뼱 ?덉쑝硫?
        # ?꾩옱 worktree?먯꽌 main checkout??援ъ“?곸쑝濡?遺덇??ν븯??
        if _is_linked_worktree(project_root) and "is already used by worktree at" in stderr:
            logger.info(
                "[WorktreeManager] linked worktree?먯꽌 main checkout ?ㅽ궢 "
                "(main? ?ㅻⅨ worktree?먯꽌 ?ъ슜 以?: %s",
                project_root,
            )
            return
        raise WorktreeError(f"硫붿씤 ?덊룷瑜?main?쇰줈 蹂듦? ?ㅽ뙣 (?꾩옱: {branch}): {checkout.stderr}")


def parse_plan_filename(plan_file: str) -> tuple:
    """plan ?뚯씪紐낆뿉???좎쭨? slug 遺꾨━

    '2026-02-27_activity-hub-fix.md' ??('2026-02-27', 'activity-hub-fix')
    ?좎쭨 ?묐몢?ш? ?놁쑝硫?('', stem) 諛섑솚
    """
    stem = Path(plan_file).stem
    # YYYY-MM-DD_ ?⑦꽩 媛먯?
    import re
    m = re.match(r'^(\d{4}-\d{2}-\d{2})_(.+)$', stem)
    if m:
        return m.group(1), m.group(2)
    return '', stem


def branch_from_plan(plan_file: str) -> str:
    """plan ?뚯씪紐낆뿉??釉뚮옖移섎챸 ?앹꽦

    '2026-02-27_activity-hub-fix.md' ??'plan/2026-02-27_activity-hub-fix'
    """
    stem = Path(plan_file).stem
    return f"plan/{stem}"


@dataclass
class MergeResult:
    success: bool
    conflict: bool
    message: str
    already_merged: bool = False
    stash_pop_conflict: bool = False
    overwritten: bool = False
    exception: str = ""


class WorktreeManager:
    @staticmethod
    def validate(worktree_path: Path) -> bool:
        """worktree媛 ?ㅼ젣濡??좏슚?쒖? 寃利?

        ?좏슚 議곌굔:
        1. ?붾젆?좊━ 議댁옱
        2. .git ?뚯씪(worktree 留곹겕) 議댁옱
        3. git rev-parse --git-dir ?깃났

        源⑥쭊 worktree(?붾젆?좊━留??덇퀬 .git ?놁쓬)??False 諛섑솚.
        """
        if not worktree_path.is_dir():
            return False
        if not (worktree_path / ".git").exists():
            return False
        result = _run_git(
            ["rev-parse", "--git-dir"],
            cwd=str(worktree_path), capture_output=True
        )
        return result.returncode == 0

    @staticmethod
    def _apply_sparse_checkout(worktree_path: Path) -> None:
        """worktree??sparse-checkout ?곸슜: docs/plan/, docs/archive/ ?쒖쇅"""
        # sparse-checkout ?쒖꽦??(?대? ?쒖꽦?댁뼱??硫깅벑)
        _run_git(
            ["sparse-checkout", "init", "--no-cone"],
            cwd=str(worktree_path), capture_output=True
        )
        # ?⑦꽩 ?ㅼ젙: ?꾩껜 ?ы븿, docs/plan/ + docs/archive/ ?쒖쇅
        _run_git(
            ["sparse-checkout", "set", "--no-cone",
             "/*", "!/docs/plan/", "!/docs/archive/"],
            cwd=str(worktree_path), capture_output=True
        )
        logger.info(f"[WorktreeManager] sparse-checkout ?곸슜: {worktree_path} (docs/plan, docs/archive ?쒖쇅)")

    @staticmethod
    def create(runner_id: str, base_dir: Path, plan_file: Optional[str] = None) -> tuple:
        """git worktree add ?ㅽ뻾 ??(worktree_path, branch) 諛섑솚

        plan_file 吏???? branch='plan/{stem}', path=base_dir/{stem}
        誘몄????? branch='runner/{runner_id}', path=base_dir/{runner_id}
        """
        if not runner_id:
            raise WorktreeError("runner_id cannot be empty")
        # Phase 2: nested .worktrees guard — 비정상 base_dir는 진입 즉시 거부
        _bd_parts = list(Path(base_dir).parts)
        if _bd_parts.count(".worktrees") >= 2:
            raise WorktreeError(
                f"비정상 base_dir 거부 (nested .worktrees): base_dir={base_dir}, "
                f"runner_id={runner_id}, plan_file={plan_file}"
            )
        if plan_file:
            stem = Path(plan_file).stem
            worktree_path = base_dir / stem
            branch = f"plan/{stem}"
        else:
            worktree_path = base_dir / runner_id
            branch = f"runner/{runner_id}"
        # Phase 1: 같은 branch가 기존 worktree에 등록되어 있으면 위치 무관 재사용
        for _w in WorktreeManager.list_worktrees(cwd=str(base_dir.parent)):
            if _w.get("branch") == branch:
                _existing = Path(_w["path"])
                if WorktreeManager.validate(_existing):
                    logger.info(
                        f"[WorktreeManager] 같은 branch 기존 worktree 재사용 "
                        f"(위치 무관): branch={branch}, path={_existing}"
                    )
                    WorktreeManager._apply_sparse_checkout(_existing)
                    return _existing, branch
                logger.warning(
                    f"[WorktreeManager] 같은 branch 기존 worktree 발견했으나 validate 실패, "
                    f"fallback 진행: branch={branch}, path={_existing}"
                )
                break
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            ensure_main_branch(base_dir.parent)
            # 釉뚮옖移?議댁옱 ?щ? ?ъ쟾 ?뺤씤: 議댁옱 ??-b ?놁씠 ?ъ궗??
            branch_check = _run_git(
                ["branch", "--list", branch],
                cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8"
            )
            branch_exists = bool(branch_check.stdout.strip())
            if branch_exists:
                result = _run_git(
                    ["worktree", "add", str(worktree_path), branch],
                    cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8"
                )
            else:
                result = _run_git(
                    ["worktree", "add", str(worktree_path), "-b", branch],
                    cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8"
                )
            if result.returncode != 0:
                _stale_markers = (
                    "already exists",
                    "already checked out",
                    "already registered worktree",
                    "missing but already registered worktree",
                )
                if any(marker in result.stderr for marker in _stale_markers):
                    # ?뚰겕?몃━ ?붾젆?좊━媛 ?ㅼ젣濡?議댁옱?섎㈃ ?ъ궗??(而ㅻ컠 蹂댁〈)
                    if worktree_path.is_dir():
                        if WorktreeManager.validate(worktree_path):
                            logger.info(f"[WorktreeManager] 湲곗〈 worktree ?ъ궗?? {branch}")
                            WorktreeManager._apply_sparse_checkout(worktree_path)
                            return worktree_path, branch
                        # .git ?녿뒗 源⑥쭊 worktree ???뺣━ ???ъ깮??
                        logger.warning(f"[WorktreeManager] 源⑥쭊 worktree ?뺣━ ???ъ깮?? {branch} ({worktree_path})")
                        shutil.rmtree(str(worktree_path))
                        _run_git(
                            ["worktree", "prune", "--expire", "now"],
                            cwd=str(base_dir.parent), capture_output=True,
                        )
                    # ?붾젆?좊━ ?놁쓬 + 釉뚮옖移섎쭔 ?⑥? 寃쎌슦: 誘몃㉧吏 而ㅻ컠 ?뺤씤 ??遺꾧린
                    _run_git(
                        ["worktree", "prune", "--expire", "now"],
                        cwd=str(base_dir.parent), capture_output=True,
                    )
                    unmerged = _run_git(
                        ["log", f"main..{branch}", "--oneline"],
                        cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8",
                    )
                    has_unmerged = unmerged.returncode == 0 and unmerged.stdout.strip()
                    if has_unmerged:
                        # 誘몃㉧吏 而ㅻ컠 ?덉쓬: branch -D ?ㅽ궢, 湲곗〈 釉뚮옖移섎줈 ?뚰겕?몃━ ?곌껐
                        result = _run_git(
                            ["worktree", "add", str(worktree_path), branch],
                            cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8",
                        )
                        if result.returncode != 0:
                            raise WorktreeError(f"git worktree add ?ㅽ뙣 (湲곗〈 釉뚮옖移??ъ궗???쒕룄): stderr={result.stderr.strip()}, stdout={result.stdout.strip()}")
                        logger.warning(f"[WorktreeManager] 誘몃㉧吏 而ㅻ컠 蹂댁〈 ??湲곗〈 釉뚮옖移??ъ궗?? {branch}")
                    else:
                        # 誘몃㉧吏 而ㅻ컠 ?놁쓬(?대? 癒몄???or 鍮?釉뚮옖移?: 湲곗〈 ?숈옉 ?좎?
                        branch_del = _run_git(
                            ["branch", "-D", branch],
                            cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8",
                        )
                        if branch_del.returncode != 0:
                            logger.warning(f"[WorktreeManager] branch -D ?ㅽ뙣: {branch} ??{branch_del.stderr.strip()}")
                        result = _run_git(
                            ["worktree", "add", str(worktree_path), "-b", branch],
                            cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8",
                        )
                        if result.returncode != 0:
                            raise WorktreeError(f"git worktree add ?ㅽ뙣 (?ъ떆????: stderr={result.stderr.strip()}, stdout={result.stdout.strip()}")
                        logger.warning(f"[WorktreeManager] dangling 釉뚮옖移??뺣━ ???ъ깮?? {branch}")
                else:
                    raise WorktreeError(f"git worktree add ?ㅽ뙣: stderr={result.stderr.strip()}, stdout={result.stdout.strip()}")
            WorktreeManager._apply_sparse_checkout(worktree_path)
            if not WorktreeManager.validate(worktree_path):
                raise WorktreeError(f"worktree ?앹꽦 ??寃利??ㅽ뙣 (.git ?꾨씫): {worktree_path}")
            logger.info(f"[WorktreeManager] ?앹꽦: {worktree_path} (釉뚮옖移? {branch})")
            return worktree_path, branch
        except WorktreeError:
            raise
        except Exception as e:
            raise WorktreeError(f"worktree ?앹꽦 以??ㅻ쪟: {e}")

    @staticmethod
    def remove(runner_id: str, base_dir: Path, plan_file: Optional[str] = None, branch: Optional[str] = None, delete_branch: bool = True) -> bool:
        """git worktree remove + (?좏깮?? git branch -D

        ?곗꽑?쒖쐞: branch ?뚮씪誘명꽣 > plan_file > runner_id 湲곕컲
        delete_branch=False: worktree ?붾젆?좊━留??쒓굅, branch??蹂댁〈 (merge ???ъ쟾 ?쒓굅 ???ъ슜)
        """
        if branch:
            # branch ?뚮씪誘명꽣媛 ?덉쑝硫?洹몃?濡??ъ슜, worktree_path??base_dir/{branch_slug}濡?異붾줎
            branch_slug = branch.replace("/", "_")
            worktree_path = base_dir / branch_slug
        elif plan_file:
            stem = Path(plan_file).stem
            worktree_path = base_dir / stem
            branch = f"plan/{stem}"
        else:
            worktree_path = base_dir / runner_id
            branch = f"runner/{runner_id}"
        # Phase 2: nested .worktrees guard (멱등성 우선 — raise 대신 False 반환)
        _bd_parts = list(Path(base_dir).parts)
        if _bd_parts.count(".worktrees") >= 2:
            logger.error(
                f"[WorktreeManager] 비정상 base_dir 거부 (nested .worktrees): "
                f"base_dir={base_dir}, runner_id={runner_id}"
            )
            return False
        try:
            result = _run_git(
                ["worktree", "remove", str(worktree_path), "--force"],
                cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8"
            )
            if result.returncode != 0 and "is not a working tree" not in result.stderr:
                logger.warning(f"[WorktreeManager] worktree ??젣 寃쎄퀬: {result.stderr}")
            if delete_branch:
                _run_git(
                    ["branch", "-D", branch],
                    cwd=str(base_dir.parent), capture_output=True, text=True, encoding="utf-8"
                )
            logger.info(f"[WorktreeManager] ?쒓굅: {runner_id} (delete_branch={delete_branch})")
            return True
        except Exception as e:
            logger.error(f"[WorktreeManager] ?쒓굅 ?ㅽ뙣: {e}")
            return True  # 硫깅벑 泥섎━

    @staticmethod
    def merge_to_main(runner_id: str, base_dir: Path, project_root: Path, plan_file: Optional[str] = None, branch: Optional[str] = None) -> MergeResult:
        """worktree 蹂寃쎌궗??쓣 main 釉뚮옖移섏뿉 癒몄?

        ?곗꽑?쒖쐞: branch ?뚮씪誘명꽣 > plan_file > runner_id 湲곕컲
        dirty working tree??merge ??stash, 寃곌낵???곕씪 pop.
        ?덉쇅 諛쒖깮 ?쒖뿉??finally?먯꽌 main 釉뚮옖移?蹂듦? 蹂댁옣.
        """
        if branch:
            pass  # 洹몃?濡??ъ슜
        elif plan_file:
            stem = Path(plan_file).stem
            branch = f"plan/{stem}"
        else:
            branch = f"runner/{runner_id}"
        stashed = False
        repo_git_path = project_root / ".git"
        try:
            # 실제 git repo일 때만 main 체크아웃 보장
            if repo_git_path.exists():
                ensure_main_branch(project_root)
            # is-ancestor ?ъ쟾 泥댄겕 ???대? 癒몄???釉뚮옖移섎㈃ skip
            ancestor_check = _run_git(
                ["merge-base", "--is-ancestor", branch, "HEAD"],
                cwd=str(project_root), capture_output=True
            )
            if ancestor_check.returncode == 0:
                logger.info(f"[WorktreeManager] ?대? 癒몄?????skip: {branch}")
                return MergeResult(success=True, conflict=False, already_merged=True, message="?대? 癒몄?????skip")
            # pre-merge stash: dirty working tree 媛먯?
            status_r = _run_git(
                ["status", "--porcelain"],
                cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
            )
            if status_r.stdout.strip():
                stash_r = _run_git(
                    ["stash", "push", "--include-untracked"],
                    cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
                )
                stashed = stash_r.returncode == 0 and "No local changes to save" not in stash_r.stdout
                logger.info(f"[WorktreeManager] pre-merge stash: rc={stash_r.returncode}, stashed={stashed}")
            result = _run_git(
                ["merge", branch, "--no-ff", "-m", f"merge: {branch}"],
                cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
            )
            if result.returncode == 0:
                # 癒몄? ?깃났 ??stash pop (?덉쑝硫?
                stash_pop_conflict = False
                if stashed:
                    pop_r = _run_git(
                        ["stash", "pop"],
                        cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
                    )
                    if pop_r.returncode != 0:
                        stash_pop_conflict = True
                        logger.warning(f"[WorktreeManager] stash pop 異⑸룎 ??drop ?ㅽ뻾: {pop_r.stderr[:200]}")
                        _run_git(["stash", "drop"], cwd=str(project_root), capture_output=True)
                    stashed = False
                logger.info(f"[WorktreeManager] 癒몄? ?깃났: {branch}")
                return MergeResult(success=True, conflict=False, stash_pop_conflict=stash_pop_conflict, message="癒몄? ?깃났")
            else:
                conflict = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
                overwritten = "would be overwritten" in result.stderr or "would be overwritten" in result.stdout
                # "overwritten" 媛먯? ??auto-commit ??1??retry
                if overwritten and not conflict:
                    logger.warning(f"[merge_to_main] 'overwritten' 媛먯? ??auto-commit ??retry")
                    _run_git(["add", "-A"], cwd=str(project_root), capture_output=True)
                    _run_git(
                        ["commit", "-m", "chore: pre-merge safety commit (retry)"],
                        cwd=str(project_root), capture_output=True
                    )
                    result = _run_git(
                        ["merge", branch, "--no-ff", "-m", f"merge: {branch}"],
                        cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
                    )
                    if result.returncode == 0:
                        stash_pop_conflict = False
                        if stashed:
                            pop_r = _run_git(
                                ["stash", "pop"],
                                cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
                            )
                            if pop_r.returncode != 0:
                                stash_pop_conflict = True
                                logger.warning(f"[WorktreeManager] stash pop 異⑸룎 ??drop ?ㅽ뻾: {pop_r.stderr[:200]}")
                                _run_git(["stash", "drop"], cwd=str(project_root), capture_output=True)
                            stashed = False
                        logger.info(f"[WorktreeManager] 癒몄? ?깃났 (auto-commit ??retry): {branch}")
                        return MergeResult(success=True, conflict=False, stash_pop_conflict=stash_pop_conflict, message="癒몄? ?깃났 (auto-commit ??retry)")
                    # retry???ㅽ뙣 ???꾨옒 conflict/error 泥섎━ 怨꾩냽
                    conflict = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
                    overwritten = "would be overwritten" in result.stderr or "would be overwritten" in result.stdout
                # CONFLICT 以꾨쭔 異붿텧?섏뿬 message???ы븿 (resolve?먯꽌 而⑦뀓?ㅽ듃濡??쒖슜)
                conflict_lines = [l.strip() for l in result.stdout.splitlines() if l.strip().startswith("CONFLICT")]
                detail = "\n".join(conflict_lines) if conflict_lines else (result.stderr.strip() + "\n" + result.stdout.strip()).strip()[:500]
                if not repo_git_path.exists():
                    detail = f"failed to restore main branch: {detail}"
                # ??긽 abort ??stash pop
                _run_git(["merge", "--abort"], cwd=str(project_root), capture_output=True)
                if stashed:
                    pop_r = _run_git(
                        ["stash", "pop"],
                        cwd=str(project_root), capture_output=True, text=True, encoding="utf-8"
                    )
                    if pop_r.returncode != 0:
                        logger.warning(f"[WorktreeManager] abort ??stash pop ?ㅽ뙣 ??drop: {pop_r.stderr[:200]}")
                        _run_git(["stash", "drop"], cwd=str(project_root), capture_output=True)
                    stashed = False
                return MergeResult(success=False, conflict=conflict, overwritten=overwritten, message=detail)
        except Exception as e:
            return MergeResult(success=False, conflict=False, exception=str(e), message=str(e))
        finally:
            # ?덉쇅 諛쒖깮 ?쒖뿉??main 蹂듦? 蹂댁옣 (stash pop? ?꾩뿉???대? 泥섎━)
            # ?덉쇅???듭젣 ???대? except?먯꽌 MergeResult瑜?諛섑솚?덇굅???곸쐞濡??꾪뙆 以?
            if repo_git_path.exists():
                try:
                    _run_git(["checkout", "main"], cwd=str(project_root), capture_output=True)
                except Exception:
                    pass

    @staticmethod
    def list_worktrees(cwd: Optional[str] = None) -> list:
        """git worktree list --porcelain ?뚯떛.

        cwd=None?대㈃ subprocess ?꾩옱 ?붾젆?좊━瑜?洹몃?濡??ъ슜?쒕떎.
        ?ㅽ뻾 ?⑥쐞媛 ?ㅻⅨ git repo濡?諛붾? ??寃쎌슦 ?몄텧痢??쒕챸?쟻 cwd瑜?꽆寃⑥빞 ?쒕떎.
        """
        try:
            result = _run_git(
                ["worktree", "list", "--porcelain"],
                cwd=cwd,
                capture_output=True, text=True, encoding="utf-8"
            )
            worktrees = []
            current: dict = {}
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    if current:
                        worktrees.append(current)
                    current = {"path": line[9:], "branch": None, "runner_id": None, "plan_slug": None}
                elif line.startswith("branch "):
                    branch = line[7:].replace("refs/heads/", "")
                    current["branch"] = branch
                    if branch.startswith("runner/"):
                        current["runner_id"] = branch[7:]
                    elif branch.startswith("plan/"):
                        current["plan_slug"] = branch[5:]
            if current:
                worktrees.append(current)
            return worktrees
        except Exception as e:
            logger.error(f"[WorktreeManager] list ?ㅽ뙣: {e}")
            return []


