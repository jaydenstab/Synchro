"""Synchro's shared Tk controls, spacing and native keyboard focus states."""
import sys
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

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
    root.option_add('*TCombobox*Listbox.selectBackground', '#285d46')
    root.option_add('*TCombobox*Listbox.selectForeground', TEXT)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=PANEL, foreground=TEXT, font=(FONT, 10))
    # Rounded, stretchable faces replace clam's bright raised borders.
    # Keep image references on this root: Tk does not retain Python image objects.
    root._synchro_images = []

    def image(draw):
        asset = Image.new('RGBA', (48, 36))
        draw(ImageDraw.Draw(asset))
        photo = ImageTk.PhotoImage(asset, master=root)
        root._synchro_images.append(photo)
        return photo

    def face(fill, border):
        return image(lambda d: d.rounded_rectangle((0, 0, 47, 35), radius=7, fill=fill, outline=border, width=1))

    for name, fill, ink, edge in (
        ('TButton', '#1d2226', TEXT, LINE),
        ('Primary.TButton', MINT, INK, MINT),
        ('Danger.TButton', '#231c1e', DANGER, '#493034'),
    ):
        element = name + '.surface'
        normal = face(fill, edge)
        hover = face('#65e6ae' if name == 'Primary.TButton' else '#29312e', MINT if name == 'Primary.TButton' else '#46564d')
        pressed = face('#28b97b' if name == 'Primary.TButton' else INSET, edge)
        disabled = face('#19231e' if name == 'Primary.TButton' else '#171b1e', '#252b2e')
        focused = face(fill, MINT if name != 'Primary.TButton' else TEXT)
        style.element_create(element, 'image', normal, ('disabled', disabled), ('pressed', pressed),
                             ('active', hover), ('focus', focused), border=8, sticky='nsew')
        style.layout(name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
        style.configure(name, foreground=ink, padding=(13, 9), anchor='center')
        style.map(name, foreground=[('disabled', '#7c8780')])

    def checkbox(checked=False, disabled=False, focus=False):
        scale = max(1.0, float(root.tk.call('tk', 'scaling')) / 1.333)
        side = round(16 * scale)
        asset = Image.new('RGBA', (side + round(7 * scale), side))
        draw = ImageDraw.Draw(asset)
        edge = MINT if checked or focus else '#5c6961'
        fill = ('#253b30' if disabled else MINT) if checked else INSET
        draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=round(3 * scale),
                               fill=fill, outline='#39473e' if disabled else edge, width=max(1, round(scale)))
        if checked:
            draw.line([(round(4 * scale), round(8 * scale)), (round(7 * scale), round(11 * scale)),
                       (round(12 * scale), round(5 * scale))],
                      fill=MUTED if disabled else INK, width=max(2, round(2 * scale)))
        photo = ImageTk.PhotoImage(asset, master=root)
        root._synchro_images.append(photo)
        return photo

    style.element_create('Synchro.check', 'image', checkbox(),
                         ('disabled', 'selected', checkbox(True, True)),
                         ('disabled', checkbox(False, True)), ('selected', checkbox(True)),
                         ('focus', checkbox(focus=True)), sticky='w')
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nsew', 'children': [
        ('Synchro.check', {'side': 'left', 'sticky': 'w'}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [('Checkbutton.label', {'sticky': 'w'})]})]})])
    style.configure('TCheckbutton', padding=(0, 4), focuscolor=MINT)
    style.map('TCheckbutton', background=[('active', PANEL)], foreground=[('disabled', MUTED)])
    style.configure('TCombobox', fieldbackground=INSET, background='#22292d', arrowcolor=MUTED,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=7, arrowsize=13)
    style.map('TCombobox', fieldbackground=[('readonly', INSET), ('disabled', INSET)],
              bordercolor=[('focus', MINT)], lightcolor=[('focus', MINT)], darkcolor=[('focus', MINT)],
              foreground=[('disabled', MUTED), ('readonly', TEXT)],
              selectbackground=[('readonly', INSET)], selectforeground=[('readonly', TEXT)])
    style.configure('Horizontal.TProgressbar', troughcolor=INSET, background=MINT,
                    bordercolor=INSET, lightcolor=MINT, darkcolor=MINT, thickness=5)
    style.configure('Horizontal.TScale', troughcolor=INSET, background='#6e8276',
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
    style.configure('Vertical.TScrollbar', background='#354139', troughcolor=INSET,
                    bordercolor=INSET, lightcolor=INSET, darkcolor=INSET, arrowcolor=MUTED,
                    borderwidth=0, arrowsize=10, width=10)
    style.map('Vertical.TScrollbar', background=[('active', '#5a7564'), ('pressed', MINT)])
    style.layout('Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
        ('Vertical.Scrollbar.thumb', {'sticky': 'nswe', 'expand': '1'})]})])
    style.configure('TNotebook', background=PANEL, borderwidth=0, bordercolor=PANEL,
                    lightcolor=PANEL, darkcolor=PANEL, tabmargins=(0, 0, 0, 10))
    style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(15, 9),
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, focuscolor=MINT)
    style.map('TNotebook.Tab', background=[('selected', '#223129'), ('active', '#1c2520')],
              foreground=[('selected', MINT), ('active', TEXT)],
              bordercolor=[('selected', '#223129')], lightcolor=[('selected', '#223129')],
              darkcolor=[('selected', '#223129')])
    style.configure('TPanedwindow', background=BG, sashwidth=12)
    return style


def heading(parent, title, subtitle=None):
    frame = tk.Frame(parent, bg=PANEL)
    tk.Label(frame, text=title, bg=PANEL, fg=TEXT, font=(FONT, 15, 'bold'), anchor='w').pack(fill='x')
    if subtitle:
        label = tk.Label(frame, text=subtitle, bg=PANEL, fg=MUTED, font=(FONT, 10),
                         anchor='w', justify='left', wraplength=430)
        label.pack(fill='x', pady=(5, 0))
        frame.bind('<Configure>', lambda e: label.configure(wraplength=max(120, e.width)), add='+')
    return frame


class TextPane(tk.Frame):
    """Borderless transcript surface with a themed scrollbar instead of Tk's white one."""
    def __init__(self, parent):
        super().__init__(parent, bg=INSET, padx=1, pady=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.text = tk.Text(self, width=32, height=5, wrap='word', font=(FONT, 11), bg=INSET,
                            fg=TEXT, insertbackground=TEXT, selectbackground='#285d46',
                            selectforeground=TEXT, relief='flat', borderwidth=0, highlightthickness=0,
                            state='disabled', padx=12, pady=12)
        self.text.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.text.configure(yscrollcommand=scrollbar.set)


def wrap_labels(parent, *labels, inset=36):
    """Keep explanatory text inside a resizable panel without fixed-width clipping."""
    def resize(event):
        width = max(120, event.width - inset)
        for label in labels:
            if int(label.cget('wraplength')) != width:
                label.configure(wraplength=width)
    parent.bind('<Configure>', resize, add='+')
