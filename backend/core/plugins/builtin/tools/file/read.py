import unicodedata
from pathlib import Path
import asyncio
from typing import Dict, Any, List, Optional
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


def _get_allowed_absolute_roots() -> List[str]:
    """Allowed roots for absolute paths: from config (comma-separated). Empty => [home] only."""
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if not roots:
            roots = [str(Path.home())]
        return roots
    except Exception:
        return [str(Path.home())]

class FileReadTool(Tool):
    async def _search_file_smart(self, filename: str, allowed_roots: List[str]) -> Optional[Path]:
        """
        智能搜索文件：在允许的根目录下递归搜索文件名匹配的文件
        为了避免性能问题，限制搜索深度和文件数量
        """
        if not filename or not allowed_roots:
            return None
            
        logger.info(f"[file.read] Smart search for file: {filename}")
        
        # 常见的用户目录
        search_paths = [
            str(Path.home()),  # 用户主目录
            str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"),
            str(Path.home() / "Downloads"),
            "/tmp",
        ]
        
        # 也包括允许的根目录
        for root in allowed_roots:
            root_path = Path(root).expanduser().resolve()
            if root_path.exists() and str(root_path) not in search_paths:
                search_paths.append(str(root_path))
        
        # 限制搜索的文件数量，避免长时间扫描
        max_files_to_check = 1000
        files_checked = 0
        
        try:
            for search_root in search_paths:
                root_path = Path(search_root)
                if not root_path.exists() or not root_path.is_dir():
                    continue
                    
                logger.debug(f"[file.read] Searching in: {search_root}")
                
                # 限制递归深度为2层（避免过度扫描）
                try:
                    for item in root_path.rglob('*'):
                        if files_checked >= max_files_to_check:
                            logger.warning(f"[file.read] Stopped smart search after checking {max_files_to_check} files")
                            return None
                            
                        files_checked += 1
                        
                        # 只检查文件，跳过目录
                        if not item.is_file():
                            continue
                            
                        # 检查文件名是否匹配（NFC/NFD 归一化）
                        if (unicodedata.normalize("NFC", item.name) == filename or 
                            unicodedata.normalize("NFD", item.name) == unicodedata.normalize("NFD", filename)):
                            logger.info(f"[file.read] Found file via smart search: {item}")
                            return item
                            
                        # 限制递归深度
                        try:
                            relative_path = item.relative_to(root_path)
                            if len(relative_path.parts) > 2:  # 最多2层深度
                                continue
                        except ValueError:
                            continue
                            
                except (OSError, PermissionError) as e:
                    logger.debug(f"[file.read] Cannot access {search_root}: {e}")
                    continue
                    
        except Exception as e:
            logger.warning(f"[file.read] Smart search failed: {e}")
            
        logger.info(f"[file.read] Smart search completed, file not found: {filename}")
        return None

    @property
    def name(self) -> str:
        return "file.read"

    @property
    def description(self) -> str:
        return "Read the content of a file. Accepts: (1) relative path under workspace, (2) absolute path under allowed roots (configurable, e.g. / or /Users/xxx)."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "File path: relative to workspace root, or absolute path under allowed roots (e.g. /Users/tony/file.txt or /path/to/file.txt if allowed)."
            }
        }, required=["path"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "string"}

    @property
    def required_permissions(self):
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File Read",
            "icon": "FileText",
            "category": "file",
            "permissions_hint": [
                {"key": "file.read", "label": "Read files within the workspace sandbox."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            if not path:
                return ToolResult(success=False, data=None, error="Path is required")

            # 便于排查：记录收到的 path 与 workspace（上传文件时 workspace 应为会话工作目录的绝对路径）
            workspace_val = (ctx.workspace or "").strip() or "."
            logger.info(f"[file.read] path={path!r} workspace={workspace_val!r}")

            # 路径做 NFC 归一化，与保存上传文件时一致，避免 macOS NFD 导致找不到
            path_normalized = unicodedata.normalize("NFC", path.strip())
            target_abs: Optional[Path] = None

            # 仅文件名（无路径）且 workspace 已设置：优先通过 listdir 按 NFC/NFD 匹配真实路径，避免 macOS 上 is_file() 因 Unicode 形式不同而误判
            if "/" not in path_normalized and "\\" not in path_normalized and workspace_val not in (".", "", None):
                try:
                    workspace_abs = Path(workspace_val).expanduser().resolve()
                    if workspace_abs.is_dir():
                        path_nfd = unicodedata.normalize("NFD", path_normalized)
                        for p in workspace_abs.iterdir():
                            if not p.is_file():
                                continue
                            if unicodedata.normalize("NFC", p.name) == path_normalized:
                                target_abs = p
                                break
                            if unicodedata.normalize("NFD", p.name) == path_nfd:
                                target_abs = p
                                break
                except OSError as e:
                    logger.warning(f"[file.read] listdir failed workspace={workspace_val!r} err={e}")

            # 未通过 listdir 命中则走 resolve_in_workspace（含绝对路径或子路径）
            if target_abs is None or not target_abs.is_file():
                try:
                    resolved = resolve_in_workspace(
                        workspace=ctx.workspace,
                        path=path_normalized,
                        allowed_absolute_roots=_get_allowed_absolute_roots(),
                    )
                    if target_abs is None:
                        target_abs = resolved
                    elif not target_abs.is_file() and resolved.is_file():
                        target_abs = resolved
                    
                    # 如果 resolved 路径存在但 is_file() 为 False，可能是 Unicode 形式不同（macOS NFD vs NFC）
                    # 尝试 NFD 形式
                    if target_abs and not target_abs.is_file():
                        target_abs_nfd = Path(unicodedata.normalize("NFD", str(target_abs)))
                        if target_abs_nfd.is_file():
                            target_abs = target_abs_nfd
                            logger.info(f"[file.read] Found file using NFD normalization: {target_abs}")
                except WorkspacePathError as e:
                    if target_abs is None or not target_abs.is_file():
                        return ToolResult(success=False, data=None, error=str(e))

            if not target_abs or not target_abs.is_file():
                # 再次尝试 listdir 匹配（workspace 为 "." 时也会列 CWD）
                if "/" not in path_normalized and "\\" not in path_normalized:
                    try:
                        workspace_abs = Path(ctx.workspace or ".").resolve()
                        if workspace_abs.is_dir():
                            path_nfd = unicodedata.normalize("NFD", path_normalized)
                            for p in workspace_abs.iterdir():
                                if not p.is_file():
                                    continue
                                if unicodedata.normalize("NFC", p.name) == path_normalized:
                                    target_abs = p
                                    break
                                if unicodedata.normalize("NFD", p.name) == path_nfd:
                                    target_abs = p
                                    break
                    except OSError as e:
                        logger.warning(f"[file.read] listdir fallback failed workspace={ctx.workspace!r} err={e}")
                
                # 如果还是找不到，且路径看起来像文件名（不含路径分隔符），尝试智能搜索
                if (not target_abs or not target_abs.is_file()) and "/" not in path_normalized and "\\" not in path_normalized:
                    logger.info(f"[file.read] Attempting smart search for: {path_normalized}")
                    target_abs = await self._search_file_smart(path_normalized, _get_allowed_absolute_roots())
                    if target_abs:
                        logger.info(f"[file.read] Smart search result: {target_abs}, exists={target_abs.exists()}, is_file={target_abs.is_file()}")
                    else:
                        logger.info(f"[file.read] Smart search returned None")
                
                if not target_abs or not target_abs.is_file():
                    logger.warning(f"[file.read] File check failed: target_abs={target_abs}, is_file={target_abs.is_file() if target_abs else 'N/A'}")
                    try:
                        ws = Path(ctx.workspace or ".").resolve()
                        listing = list(ws.iterdir()) if ws.is_dir() else []
                        logger.warning(
                            f"[file.read] File not found path={path!r} workspace={ctx.workspace!r} "
                            f"resolved={target_abs} exists={target_abs.exists() if target_abs else False} listing={[p.name for p in listing]}"
                        )
                    except Exception:
                        pass
                    err_msg = f"未找到文件「{path}」。"
                    if workspace_val in (".", "", None):
                        err_msg += " 当前工作目录未设置（未检测到上传文件的工作目录）。若已上传文件，请在本会话中通过「带附件」方式发送消息。"
                    else:
                        err_msg += " 请确认文件名与上传时一致（含扩展名），且使用相对路径（仅文件名）。"
                    return ToolResult(success=False, data=None, error=err_msg)

            with target_abs.open('r', encoding='utf-8') as f:
                content = f.read()
            
            return ToolResult(success=True, data=content)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
