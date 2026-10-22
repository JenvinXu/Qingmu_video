"""Encrypt API credentials with Windows DPAPI; never return them to the renderer."""

from __future__ import annotations
import base64
import ctypes
import os
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("此发行版使用 Windows DPAPI，需要在 Windows 上运行")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = (
        ctypes.windll.crypt32.CryptUnprotectData
        if decrypt
        else ctypes.windll.crypt32.CryptProtectData
    )
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def encrypt(value: str) -> str:
    return base64.b64encode(_crypt(value.encode("utf-8"))).decode("ascii")


def decrypt(value: str) -> str:
    return _crypt(base64.b64decode(value), True).decode("utf-8") if value else ""
