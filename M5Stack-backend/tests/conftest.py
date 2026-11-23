"""Use one Tcl/Tk interpreter, as the actual Windows program does."""
import contextlib

import pytest


@pytest.fixture(scope='session')
def tk_host():
    import tkinter as tk
    host=tk.Tk();host.withdraw()
    yield host
    with contextlib.suppress(tk.TclError):host.destroy()


@pytest.fixture
def ui_root(tk_host):
    import tkinter as tk
    window=tk.Toplevel(tk_host);window.withdraw()
    yield window
    # Destroying and recreating full interpreters while old widget callbacks
    # are being collected can corrupt Tk initialization in Windows test runs.
    for timer in tk_host.tk.call('after','info'):
        with contextlib.suppress(tk.TclError):tk_host.after_cancel(timer)
    with contextlib.suppress(tk.TclError):window.destroy()
