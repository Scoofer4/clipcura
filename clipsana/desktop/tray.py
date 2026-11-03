"""Notification-area icon on the plain Win32 API (Shell_NotifyIconW through ctypes).

No tray library: the common one (pystray) is LGPL, which complicates shipping it frozen inside an Apache-2.0
app. The icon lives on its own thread with its own message loop; other threads only change the wanted state
and post a message, so every Win32 call happens on the thread that owns the window.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_APP = 0x8000
WM_TRAY, WM_REFRESH, WM_SHOW = WM_APP + 1, WM_APP + 2, WM_APP + 3
CLASS_NAME = "ClipsanaTray"
NIN_BALLOONUSERCLICK = 0x0405
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO, NIIF_USER, NIIF_LARGE_ICON = 0x01, 0x04, 0x20
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0000, 0x0800, 0x0008
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
SM_CXSMICON = 49
LR_DEFAULTCOLOR = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


def _prototypes() -> None:
    # Explicit signatures: without them ctypes truncates 64-bit handles and LPARAMs to 32 bits.
    sig = {
        (user32, "RegisterClassW"): (wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]),
        (user32, "UnregisterClassW"): (wintypes.BOOL, [wintypes.LPCWSTR, wintypes.HINSTANCE]),
        (user32, "CreateWindowExW"): (wintypes.HWND, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                      ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                                      wintypes.HINSTANCE, wintypes.LPVOID]),
        (user32, "DestroyWindow"): (wintypes.BOOL, [wintypes.HWND]),
        (user32, "DefWindowProcW"): (LRESULT, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32, "GetMessageW"): (wintypes.BOOL, [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                                  wintypes.UINT]),
        (user32, "TranslateMessage"): (wintypes.BOOL, [ctypes.POINTER(wintypes.MSG)]),
        (user32, "DispatchMessageW"): (LRESULT, [ctypes.POINTER(wintypes.MSG)]),
        (user32, "PostMessageW"): (wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                                   wintypes.LPARAM]),
        (user32, "PostQuitMessage"): (None, [ctypes.c_int]),
        (user32, "RegisterWindowMessageW"): (wintypes.UINT, [wintypes.LPCWSTR]),
        (user32, "CreatePopupMenu"): (wintypes.HMENU, []),
        (user32, "AppendMenuW"): (wintypes.BOOL, [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]),
        (user32, "TrackPopupMenu"): (wintypes.BOOL, [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                                     ctypes.c_int, wintypes.HWND, wintypes.LPVOID]),
        (user32, "DestroyMenu"): (wintypes.BOOL, [wintypes.HMENU]),
        (user32, "GetCursorPos"): (wintypes.BOOL, [ctypes.POINTER(wintypes.POINT)]),
        (user32, "SetForegroundWindow"): (wintypes.BOOL, [wintypes.HWND]),
        (user32, "GetSystemMetrics"): (ctypes.c_int, [ctypes.c_int]),
        (user32, "CreateIconFromResourceEx"): (wintypes.HICON, [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                                               wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                                               wintypes.UINT]),
        (user32, "DestroyIcon"): (wintypes.BOOL, [wintypes.HICON]),
        (user32, "FindWindowW"): (wintypes.HWND, [wintypes.LPCWSTR, wintypes.LPCWSTR]),
        (shell32, "Shell_NotifyIconW"): (wintypes.BOOL, [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]),
        (kernel32, "GetModuleHandleW"): (wintypes.HMODULE, [wintypes.LPCWSTR]),
    }
    for (dll, name), (restype, argtypes) in sig.items():
        fn = getattr(dll, name)
        fn.restype, fn.argtypes = restype, argtypes


_prototypes()


def show_running_instance() -> bool:
    """If Clipsana already runs, ask it to show its window and return True (one app per user session)."""
    hwnd = user32.FindWindowW(CLASS_NAME, None)
    return bool(hwnd) and bool(user32.PostMessageW(hwnd, WM_SHOW, 0, 0))


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None] | None = None   # None = separator
    checked: bool = False


class Tray:
    """One notification-area icon. `icon_png(size)` returns the artwork at the size Windows asks for, so the
    icon stays sharp at every display scale. `menu()` is rebuilt on each right click (labels and checks can
    change), and a left click or a click on a notification calls `on_open`."""

    def __init__(self, icon_png: Callable[[int], bytes], tooltip: str, menu: Callable[[], list[MenuItem]],
                 on_open: Callable[[], None]) -> None:
        self._icon_png, self._tooltip, self._menu, self._on_open = icon_png, tooltip, menu, on_open
        self._lock = threading.Lock()
        self._pending_info: tuple[str, str] | None = None
        self._hwnd: int | None = None
        self._hicon: int | None = None
        self._old_icon: int | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._class = CLASS_NAME
        self._wndproc = WNDPROC(self._proc)   # kept referenced: Windows calls it for the window's lifetime
        self._taskbar_created = 0

    # --- called from any thread -------------------------------------------------------------------------
    def start(self, timeout: float = 5.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="clipsana-tray", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout) and self._hwnd is not None

    def update(self, icon_png: Callable[[int], bytes] | None = None, tooltip: str | None = None) -> None:
        with self._lock:
            if icon_png is not None:
                self._icon_png = icon_png
            if tooltip is not None:
                self._tooltip = tooltip
        self._post(WM_REFRESH)

    def notify(self, title: str, message: str) -> None:
        """A Windows notification from the icon (shown as a toast on Windows 10 and 11)."""
        with self._lock:
            self._pending_info = (title, message)
        self._post(WM_REFRESH)

    def stop(self) -> None:
        self._post(WM_CLOSE)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(5)

    def _post(self, msg: int) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, msg, 0, 0)

    # --- tray thread ------------------------------------------------------------------------------------
    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=hinst, lpszClassName=self._class)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.warning("tray: RegisterClassW failed (%s)", ctypes.get_last_error())
            self._ready.set()
            return
        # A hidden top-level window (not message-only): only those receive "TaskbarCreated" after Explorer
        # restarts, which is when the icon has to be added again.
        self._hwnd = user32.CreateWindowExW(0, self._class, "Clipsana", 0, 0, 0, 0, 0, None, None, hinst, None)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        ok = bool(self._hwnd) and self._add()
        self._ready.set()
        if not ok:
            log.warning("tray: could not add the notification-area icon")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterClassW(self._class, hinst)

    def _data(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags, nid.uCallbackMessage = self._hwnd, 1, flags, WM_TRAY
        return nid

    def _make_icon(self) -> int | None:
        size = user32.GetSystemMetrics(SM_CXSMICON) or 16
        with self._lock:
            data = self._icon_png(size)
        buf = ctypes.create_string_buffer(data, len(data))
        # Windows Vista and newer read PNG data straight into an icon.
        return user32.CreateIconFromResourceEx(buf, len(data), True, 0x00030000, size, size, LR_DEFAULTCOLOR)

    def _apply_icon(self, nid: NOTIFYICONDATAW) -> None:
        # The previous icon is destroyed only after Windows has switched to the new one.
        self._old_icon, self._hicon = self._hicon, self._make_icon()
        nid.hIcon = self._hicon
        with self._lock:
            nid.szTip = self._tooltip[:127]

    def _add(self) -> bool:
        nid = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self._apply_icon(nid)
        added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if self._old_icon:
            user32.DestroyIcon(self._old_icon)
            self._old_icon = None
        return added

    def _refresh(self) -> None:
        nid = self._data(NIF_ICON | NIF_TIP)
        self._apply_icon(nid)
        with self._lock:
            info, self._pending_info = self._pending_info, None
        if info:
            nid.uFlags |= NIF_INFO
            nid.szInfoTitle, nid.szInfo = info[0][:63], info[1][:255]
            nid.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON  # the app's own icon instead of a generic "i"
            nid.hBalloonIcon = self._hicon
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        if self._old_icon:
            user32.DestroyIcon(self._old_icon)
            self._old_icon = None

    def _show_menu(self) -> None:
        items = self._menu()
        hmenu = user32.CreatePopupMenu()
        for i, item in enumerate(items, start=1):
            if item.action is None:
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(hmenu, MF_STRING | (MF_CHECKED if item.checked else 0), i, item.label)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # Without the foreground switch the menu would not close when the user clicks elsewhere.
        user32.SetForegroundWindow(self._hwnd)
        chosen = user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0,
                                       self._hwnd, None)
        user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(hmenu)
        if chosen and items[chosen - 1].action:
            self._call(items[chosen - 1].action)

    @staticmethod
    def _call(fn: Callable[[], None]) -> None:
        # Menu actions may block (closing the window, stopping the service): keep the tray responsive.
        threading.Thread(target=fn, name="clipsana-tray-action", daemon=True).start()

    def _proc(self, hwnd, msg, wparam, lparam) -> int:
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, NIN_BALLOONUSERCLICK):
                    self._call(self._on_open)
                elif event == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_SHOW:  # a second start of the app asks this one to come forward
                self._call(self._on_open)
                return 0
            if msg == WM_REFRESH:
                self._refresh()
                return 0
            if msg == self._taskbar_created and msg:
                self._add()
                return 0
            if msg == WM_CLOSE:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
                if self._hicon:
                    user32.DestroyIcon(self._hicon)
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # an exception escaping into Windows' callback would kill the message loop
            log.exception("tray: message %#x failed", msg)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
