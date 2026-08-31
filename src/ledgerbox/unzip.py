from __future__ import annotations

import zipfile
from pathlib import Path

import pyzipper

MAX_UNCOMPRESSED = 20 * 1024 * 1024
ALLOWED_SUFFIX = {".csv", ".xlsx"}


class UnsafeArchive(RuntimeError):
    pass


def _safe_member(name: str) -> Path:
    p = Path(name)
    if p.is_absolute() or ".." in p.parts:
        raise UnsafeArchive(f"拒绝危险路径: {name}")
    return p


def extract_archive(archive: Path, dest: Path, password: str | None) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    pwd = password.encode("utf-8") if password else None
    extracted: list[Path] = []

    try:
        zf: zipfile.ZipFile = pyzipper.AESZipFile(archive)
    except Exception:
        zf = zipfile.ZipFile(archive)

    with zf:
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            member = _safe_member(info.filename)
            if member.suffix.lower() not in ALLOWED_SUFFIX:
                continue
            size = int(getattr(info, "file_size", 0) or 0)
            total += size
            if total > MAX_UNCOMPRESSED:
                raise UnsafeArchive("解压体积超过 20MB 上限")
            target = dest / member.name
            data = zf.read(info, pwd=pwd) if pwd else zf.read(info)
            if len(data) > MAX_UNCOMPRESSED:
                raise UnsafeArchive("单文件过大")
            target.write_bytes(data)
            extracted.append(target)
    if not extracted:
        raise UnsafeArchive("压缩包内没有 csv/xlsx")
    return extracted
