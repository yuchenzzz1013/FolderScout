import os
import stat
import string
from typing import List, Optional, Callable


def list_drives() -> List[str]:
    return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]


def _is_reparse(entry: os.DirEntry) -> bool:
    """junction / symlink 等重解析点，跳过防止目录循环。"""
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def scan_folders(
    root: str,
    on_progress: Optional[Callable[[int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    progress_every: int = 2000,
) -> List[str]:
    paths: List[str] = [root]
    stack: List[str] = [root]
    count = 0
    while stack:
        if should_stop and should_stop():
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if _is_reparse(entry):
                            continue
                        paths.append(entry.path)
                        stack.append(entry.path)
                        count += 1
                        if on_progress and count % progress_every == 0:
                            on_progress(len(paths))
                    except OSError:
                        continue
        except OSError:
            continue
    if on_progress:
        on_progress(len(paths))
    return paths