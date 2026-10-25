"""Synchro Windows desktop styling. Development previews use the same widgets."""
import sys
import tkinter as tk
from tkinter import ttk

BG = '#0d0f11'
PANEL = '#15181b'
INSET = '#101214'
LINE = '#30363b'
TEXT = '#f3f6f4'
MUTED = '#9aa39c'
MINT = '#3ddc97'
INK = '#06281a'
WARN = '#f0b429'
DANGER = '#ff6b6b'
FONT = 'Segoe UI' if sys.platform == 'win32' else 'Helvetica Neue'


def install_theme(root):
    root.configure(bg=BG)
    root.option_add('*Font', (FONT, 10))
    root.option_add('*TCombobox*Listbox.background', INSET)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', MINT)
    root.option_add('*TCombobox*Listbox.selectForeground', INK)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=PANEL, foreground=TEXT, font=(FONT, 10))
    style.configure('TButton', background=INSET, foreground=TEXT, bordercolor=LINE,
                    padding=(12, 8), focusthickness=2, focuscolor=MINT)
    style.map('TButton', background=[('active', '#26332e')],
              foreground=[('disabled', '#626b65')])
    style.configure('Primary.TButton', background=MINT, foreground=INK)
    style.map('Primary.TButton', background=[('disabled', '#253d31'), ('active', '#65e6ae')],
              foreground=[('disabled', MUTED)])
    style.configure('Danger.TButton', foreground=DANGER)
    style.configure('TCheckbutton', padding=(2, 5), focuscolor=MINT)
    style.map('TCheckbutton', background=[('active', PANEL)], foreground=[('disabled', MUTED)])
    style.configure('TCombobox', fieldbackground=INSET, background=INSET, arrowcolor=MUTED,
                    bordercolor=LINE, padding=6)
    style.map('TCombobox', fieldbackground=[('readonly', INSET)],
              foreground=[('readonly', TEXT), ('disabled', MUTED)],
              selectbackground=[('readonly', INSET)], selectforeground=[('readonly', TEXT)])
    style.configure('Horizontal.TProgressbar', troughcolor=INSET, background=MINT,
                    bordercolor=INSET, lightcolor=MINT, darkcolor=MINT)
    style.configure('Horizontal.TScale', troughcolor=INSET, background=MINT)
    style.configure('Vertical.TScrollbar', background=LINE, troughcolor=INSET, arrowcolor=MUTED, borderwidth=0)
    style.map('Vertical.TScrollbar', background=[('active', MINT)])
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', background=INSET, foreground=MUTED, padding=(18, 10))
    style.map('TNotebook.Tab', background=[('selected', PANEL)], foreground=[('selected', MINT)])
    style.configure('TPanedwindow', background=BG)
    return style


def heading(parent, title, subtitle=None):
    frame = tk.Frame(parent, bg=PANEL)
    tk.Label(frame, text=title, bg=PANEL, fg=TEXT, font=(FONT, 16, 'bold'), anchor='w').pack(fill='x')
    if subtitle:
        tk.Label(frame, text=subtitle, bg=PANEL, fg=MUTED, font=(FONT, 10),
                 anchor='w', justify='left', wraplength=460).pack(fill='x', pady=(4, 0))
    return frame
