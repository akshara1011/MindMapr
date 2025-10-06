#!/usr/bin/env python3
import os
import json
import uuid
import io
import hashlib
import pathlib
import tempfile
import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox, ttk
from datetime import datetime

try:
    from PIL import Image, ImageGrab, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

APP_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
USERS_FILE = os.path.join(APP_DIR, "users.json")
MAP_INDEX = "maps_index.json"

# -------------------------
# Utilities
# -------------------------
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

def user_folder(username):
    return os.path.join(DATA_DIR, username)

def user_maps_folder(username):
    return os.path.join(user_folder(username), "maps")

def ensure_user_folders(username):
    os.makedirs(user_maps_folder(username), exist_ok=True)
    idx = os.path.join(user_folder(username), MAP_INDEX)
    if not os.path.exists(idx):
        with open(idx, "w", encoding="utf-8") as f:
            json.dump({}, f)

def load_user_maps_index(username):
    idx = os.path.join(user_folder(username), MAP_INDEX)
    if not os.path.exists(idx):
        return {}
    try:
        with open(idx, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_user_maps_index(username, index_data):
    idx = os.path.join(user_folder(username), MAP_INDEX)
    with open(idx, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

def save_map_file(username, map_id, data):
    ensure_user_folders(username)
    path = os.path.join(user_maps_folder(username), f"{map_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path

def load_map_file(username, map_id):
    path = os.path.join(user_maps_folder(username), f"{map_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def delete_map_file(username, map_id):
    path = os.path.join(user_maps_folder(username), f"{map_id}.json")
    if os.path.exists(path):
        os.remove(path)

# -------------------------
# Core mindmap data classes
# -------------------------
class Node:
    def __init__(self, canvas, x, y, text="New Node", nid=None):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.width = 160
        self.height = 52
        self.text = text
        self.id = nid or str(uuid.uuid4())

        self.rect = self.canvas.create_rectangle(
            x, y, x + self.width, y + self.height, fill="#fffacd", outline="#333", width=2
        )
        self.text_id = self.canvas.create_text(
            x + 10, y + self.height / 2, anchor="w", text=self.text, font=("Arial", 12)
        )

        # bind events
        self.canvas.tag_bind(self.rect, "<Button-1>", self.on_click)
        self.canvas.tag_bind(self.text_id, "<Button-1>", self.on_click)
        self.canvas.tag_bind(self.rect, "<B1-Motion>", self.on_drag)
        self.canvas.tag_bind(self.text_id, "<B1-Motion>", self.on_drag)
        self.canvas.tag_bind(self.rect, "<Button-3>", self.on_right_click)
        self.canvas.tag_bind(self.text_id, "<Button-3>", self.on_right_click)

        self.connections = set()

    def on_click(self, event):
        self.canvas.focus_set()
        self.canvas.selected_item = self
        # clicking also clears any temporary connection line if present
        if getattr(self.canvas, "temp_line", None):
            try:
                self.canvas.delete(self.canvas.temp_line)
            except Exception:
                pass
            self.canvas.temp_line = None

    def on_right_click(self, event):
        new = simpledialog.askstring("Edit Node Text", "Text:", initialvalue=self.text)
        if new is not None:
            self.text = new
            self.canvas.itemconfigure(self.text_id, text=self.text)
            self.canvas.app.log(f"Node '{self.id}' text updated.")

    def on_drag(self, event):
        new_x = event.x - self.width / 2
        new_y = event.y - self.height / 2
        dx = new_x - self.x
        dy = new_y - self.y
        self.x = new_x
        self.y = new_y
        self.canvas.move(self.rect, dx, dy)
        self.canvas.move(self.text_id, dx, dy)
        for eid in list(self.connections):
            self.canvas.update_edge(eid)

    def serialize(self):
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "width": self.width,
            "height": self.height
        }

class Edge:
    def __init__(self, canvas, a_node: Node, b_node: Node, eid=None):
        self.canvas = canvas
        self.a = a_node
        self.b = b_node
        self.id = eid or str(uuid.uuid4())
        x1, y1 = self.center(self.a)
        x2, y2 = self.center(self.b)
        self.line = self.canvas.create_line(x1, y1, x2, y2, width=2)
        self.a.connections.add(self.id)
        self.b.connections.add(self.id)

    def center(self, node: Node):
        return node.x + node.width / 2, node.y + node.height / 2

    def update(self):
        x1, y1 = self.center(self.a)
        x2, y2 = self.center(self.b)
        self.canvas.coords(self.line, x1, y1, x2, y2)

    def serialize(self):
        return {"id": self.id, "a": self.a.id, "b": self.b.id}

# -------------------------
# Canvas Logic
# -------------------------
class MindMapCanvas(tk.Canvas):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, **kwargs)
        self.app = app
        self.nodes = {}
        self.edges = {}
        self.selected_item = None
        self.temp_line = None

        self.bind("<Double-Button-1>", self.on_double)
        self.bind("<Button-1>", self.on_single)
        self.bind("<Delete>", self.on_delete_key)
        self.bind_all("<Control-s>", self.app.save_map_shortcut)

    def on_double(self, event):
        n = Node(self, event.x - 80, event.y - 26)
        self.nodes[n.id] = n
        self.app.log(f"Created node {n.id}")

    def on_single(self, event):
        self.focus_set()
        clicked = self.find_withtag("current")
        if not clicked:
            self.selected_item = None

    def start_connection(self):
        if not self.selected_item:
            self.app.log("No node selected to start connection.")
            return
        self.bind("<Motion>", self.follow_mouse)
        self.bind("<Button-1>", self.finish_connection)
        self.app.log("Connection mode: click target node to connect.")

    def follow_mouse(self, event):
        if self.temp_line:
            try:
                self.delete(self.temp_line)
            except Exception:
                pass
        x1 = self.selected_item.x + self.selected_item.width / 2
        y1 = self.selected_item.y + self.selected_item.height / 2
        self.temp_line = self.create_line(x1, y1, event.x, event.y, dash=(4, 2))

    def finish_connection(self, event):
        items = self.find_overlapping(event.x, event.y, event.x, event.y)
        target = None
        for it in items:
            for n in self.nodes.values():
                if it == n.rect or it == n.text_id:
                    target = n
                    break
            if target:
                break
        if target and target != self.selected_item:
            e = Edge(self, self.selected_item, target)
            self.edges[e.id] = e
            self.app.log(f"Created edge {e.id} between {e.a.id} and {e.b.id}")
        else:
            self.app.log("Connection aborted or clicked same node.")
        if self.temp_line:
            try:
                self.delete(self.temp_line)
            except Exception:
                pass
            self.temp_line = None
        self.unbind("<Motion>")
        self.bind("<Button-1>", self.on_single)

    def update_edge(self, eid):
        e = self.edges.get(eid)
        if e:
            e.update()

    def delete_node(self, node: Node):
        for eid in list(node.connections):
            self.delete_edge(eid)
        try:
            self.delete(node.rect)
            self.delete(node.text_id)
        except Exception:
            pass
        if node.id in self.nodes:
            del self.nodes[node.id]
        self.app.log(f"Deleted node {node.id}")

    def delete_edge(self, eid):
        e = self.edges.get(eid)
        if not e:
            return
        e.a.connections.discard(eid)
        e.b.connections.discard(eid)
        try:
            self.delete(e.line)
        except Exception:
            pass
        if eid in self.edges:
            del self.edges[eid]
        self.app.log(f"Deleted edge {eid}")

    def on_delete_key(self, event=None):
        if self.selected_item:
            self.delete_node(self.selected_item)
            self.selected_item = None

    def serialize(self):
        return {"nodes": [n.serialize() for n in self.nodes.values()],
                "edges": [e.serialize() for e in self.edges.values()]}

    def clear(self):
        for n in list(self.nodes.values()):
            try:
                self.delete(n.rect)
                self.delete(n.text_id)
            except Exception:
                pass
        for e in list(self.edges.values()):
            try:
                self.delete(e.line)
            except Exception:
                pass
        self.nodes.clear()
        self.edges.clear()

    def load_from(self, data):
        self.clear()
        id_map = {}
        # recreate nodes
        for nd in data.get("nodes", []):
            n = Node(self, nd.get("x", 10), nd.get("y", 10), text=nd.get("text", "New Node"), nid=nd.get("id"))
            n.width = nd.get("width", n.width)
            n.height = nd.get("height", n.height)
            # adjust rectangle and text positions if sizes changed
            try:
                self.coords(n.rect, n.x, n.y, n.x + n.width, n.y + n.height)
                self.coords(n.text_id, n.x + 10, n.y + n.height / 2)
            except Exception:
                pass
            id_map[n.id] = n
            self.nodes[n.id] = n
        # recreate edges
        for ed in data.get("edges", []):
            a = id_map.get(ed.get("a"))
            b = id_map.get(ed.get("b"))
            if a and b:
                e = Edge(self, a, b, eid=ed.get("id"))
                self.edges[e.id] = e

# -------------------------
# Login Dialog
# -------------------------
class LoginDialog:
    def __init__(self, parent):
        top = self.top = tk.Toplevel(parent)
        top.title("Login / Register")
        top.geometry("320x200")
        top.transient(parent)
        top.grab_set()
        self.result = None

        frm = tk.Frame(top, padx=10, pady=10)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Username:").grid(row=0, column=0, sticky="w")
        self.username = tk.Entry(frm)
        self.username.grid(row=0, column=1, sticky="ew", pady=4)

        tk.Label(frm, text="Password:").grid(row=1, column=0, sticky="w")
        self.password = tk.Entry(frm, show="*")
        self.password.grid(row=1, column=1, sticky="ew", pady=4)

        frm.columnconfigure(1, weight=1)

        btns = tk.Frame(top)
        btns.pack(pady=8)
        tk.Button(btns, text="Login", width=10, command=self.do_login).pack(side="left", padx=6)
        tk.Button(btns, text="Register", width=10, command=self.do_register).pack(side="left", padx=6)
        tk.Button(btns, text="Cancel", width=10, command=self.do_cancel).pack(side="left", padx=6)

    def do_login(self):
        users = load_users()
        u = self.username.get().strip()
        p_raw = self.password.get()
        p = hash_password(p_raw)
        if u in users and users[u] == p:
            self.result = ("login", u)
            self.top.destroy()
        else:
            messagebox.showerror("Login Failed", "Invalid username or password")

    def do_register(self):
        users = load_users()
        u = self.username.get().strip()
        p = self.password.get().strip()
        if not u or not p:
            messagebox.showinfo("Error", "Enter both username and password")
            return
        if u in users:
            messagebox.showinfo("Error", "Username already exists")
            return
        users[u] = hash_password(p)
        save_users(users)
        ensure_user_folders(u)
        self.result = ("register", u)
        self.top.destroy()

    def do_cancel(self):
        self.top.destroy()

# -------------------------
# Main App
# -------------------------
class MindMapApp(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.title("MindMapr — Extended")
        self.geometry("1200x800")
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

        self.current_user = None
        self.current_map_id = None
        self.current_map_meta = None
        self.users = load_users()

        self.create_menu()

        # Left panel
        left = tk.Frame(self, width=260, relief="ridge", bd=1)
        left.pack(side="left", fill="y")

        user_box = tk.Frame(left, pady=6)
        user_box.pack(fill="x")
        self.user_label = tk.Label(user_box, text="Not logged in", font=("Arial", 11, "bold"))
        self.user_label.pack(anchor="w", padx=8)
        tk.Button(user_box, text="Login / Register", command=self.show_login).pack(padx=8, pady=4, fill="x")

        tk.Label(left, text="Your Maps", font=("Arial", 10, "bold")).pack(anchor="w", padx=8, pady=(10, 0))
        self.maps_list = tk.Listbox(left, height=20)
        self.maps_list.pack(fill="both", expand=True, padx=8, pady=6)
        self.maps_list.bind("<Double-Button-1>", self.open_selected_map)

        maps_btns = tk.Frame(left)
        maps_btns.pack(fill="x", padx=8, pady=6)
        tk.Button(maps_btns, text="New Map", command=self.new_map_for_user).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(maps_btns, text="Delete", command=self.delete_selected_map).pack(side="left", expand=True, fill="x", padx=2)

        # Center
        center = tk.Frame(self)
        center.pack(side="left", fill="both", expand=True)

        toolbar = tk.Frame(center, bd=1, relief="raised")
        toolbar.pack(side="top", fill="x")
        for label, cmd in [
            ("New", self.new_map_for_user),
            ("Open...", self.open_map_dialog),
            ("Save", self.save_map),
            ("Connect", self.canvas_start_connection),
            ("Export PNG", self.export_png),
            ("Logout", self.logout_user)
        ]:
            b = tk.Button(toolbar, text=label, command=cmd)
            b.pack(side="left", padx=3, pady=3)

        self.canvas = MindMapCanvas(center, app=self, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Right
        right = tk.Frame(self, width=260, relief="ridge", bd=1)
        right.pack(side="right", fill="y")
        tk.Label(right, text="Quick Info", font=("Arial", 10, "bold")).pack(anchor="w", padx=8, pady=6)
        self.info_text = tk.Text(right, height=10, state="disabled", wrap="word")
        self.info_text.pack(fill="both", padx=8, pady=6, expand=False)

        # Bottom log
        bottom = tk.Frame(self, height=140, relief="sunken", bd=1)
        bottom.pack(side="bottom", fill="x")
        tk.Label(bottom, text="Output / Log").pack(anchor="w", padx=6)
        self.log_text = tk.Text(bottom, height=6, state="disabled", wrap="word")
        self.log_text.pack(fill="x", padx=6, pady=4)

        self.status_var = tk.StringVar(value="Please login to start.")
        status = tk.Label(self, textvariable=self.status_var, bd=1, relief="sunken", anchor="w")
        status.pack(side="bottom", fill="x")

        # ask login shortly after startup
        self.after(100, self.show_login)

    # -------------------------
    # Menus and helpers
    # -------------------------
    def create_menu(self):
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New Map", command=self.new_map_for_user)
        filem.add_command(label="Open Map...", command=self.open_map_dialog)
        filem.add_command(label="Save Map", command=self.save_map)
        filem.add_separator()
        filem.add_command(label="Export PNG...", command=self.export_png)
        filem.add_separator()
        filem.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=filem)

        accountm = tk.Menu(menubar, tearoff=0)
        accountm.add_command(label="Login / Register", command=self.show_login)
        accountm.add_command(label="Logout", command=self.logout_user)
        menubar.add_cascade(label="Account", menu=accountm)

        editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="Start Connection", command=self.canvas_start_connection)
        editm.add_command(label="Delete Selected Node", command=self.delete_selected_node)
        menubar.add_cascade(label="Edit", menu=editm)

        viewm = tk.Menu(menubar, tearoff=0)
        viewm.add_command(label="Clear Log", command=self.clear_log)
        menubar.add_cascade(label="View", menu=viewm)

        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=helpm)

        self.config(menu=menubar)

    def log(self, msg):
        ts = now_str()
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.config(state="disabled")
        self.log_text.see("end")

    def info(self, msg):
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", msg)
        self.info_text.config(state="disabled")

    # -------------------------
    # User management
    # -------------------------
    def show_login(self):
        dlg = LoginDialog(self)
        self.wait_window(dlg.top)
        if getattr(dlg, "result", None):
            kind, username = dlg.result
            if kind in ("login", "register"):
                self.login_user(username)

    def login_user(self, username):
        self.current_user = username
        ensure_user_folders(username)
        self.user_label.config(text=f"User: {username}")
        self.status_var.set(f"Logged in as {username}")
        self.log(f"User '{username}' logged in.")
        self.refresh_maps_list()
        self.info(f"Welcome, {username}!\nCreate new maps, save them and they will be stored at:\n{user_maps_folder(username)}")

    def logout_user(self):
        if not self.current_user:
            self.log("No user is logged in.")
            return
        self.log(f"User '{self.current_user}' logged out.")
        self.current_user = None
        self.current_map_id = None
        self.user_label.config(text="Not logged in")
        self.maps_list.delete(0, tk.END)
        self.canvas.clear()
        self.status_var.set("Logged out.")
        self.info("Logged out. Login to access your maps.")

    # -------------------------
    # Map list management
    # -------------------------
    def refresh_maps_list(self):
        self.maps_list.delete(0, tk.END)
        if not self.current_user:
            return
        idx = load_user_maps_index(self.current_user)
        # index maps: map_id -> {title,created,modified}
        sorted_items = sorted(idx.items(), key=lambda kv: kv[1].get("modified", ""), reverse=True)
        for mid, meta in sorted_items:
            title = meta.get("title", mid)
            display = f"{title} — {meta.get('modified','')}"
            self.maps_list.insert(tk.END, f"{mid}|{display}")

    def new_map_for_user(self):
        if not self.current_user:
            messagebox.showinfo("Login required", "Please login or register first.")
            return
        title = simpledialog.askstring("New Map", "Map title:")
        if title is None:
            return
        self.canvas.clear()
        self.current_map_id = str(uuid.uuid4())
        self.current_map_meta = {"title": title, "created": now_str(), "modified": now_str()}
        # update index
        idx = load_user_maps_index(self.current_user)
        idx[self.current_map_id] = self.current_map_meta
        save_user_maps_index(self.current_user, idx)
        self.refresh_maps_list()
        self.log(f"Created new map '{title}' (id={self.current_map_id}).")
        self.status_var.set(f"Editing: {title}")

    def open_selected_map(self, event=None):
        sel = self.maps_list.curselection()
        if not sel:
            return
        val = self.maps_list.get(sel[0])
        mid = val.split("|", 1)[0]
        self.load_map(mid)

    def load_map(self, map_id):
        if not self.current_user:
            self.log("Login to open maps.")
            return
        data = load_map_file(self.current_user, map_id)
        if data is None:
            messagebox.showerror("Error", "Map file missing.")
            return
        self.canvas.load_from(data)
        idx = load_user_maps_index(self.current_user)
        self.current_map_id = map_id
        self.current_map_meta = idx.get(map_id, {"title": "Untitled"})
        self.status_var.set(f"Editing: {self.current_map_meta.get('title')}")
        self.log(f"Loaded map {map_id}")

    def delete_selected_map(self):
        sel = self.maps_list.curselection()
        if not sel:
            return
        val = self.maps_list.get(sel[0])
        mid = val.split("|", 1)[0]
        if not messagebox.askyesno("Delete map", "Are you sure you want to permanently delete this map?"):
            return
        delete_map_file(self.current_user, mid)
        idx = load_user_maps_index(self.current_user)
        if mid in idx:
            del idx[mid]
            save_user_maps_index(self.current_user, idx)
        self.refresh_maps_list()
        self.log(f"Deleted map {mid}")

    # -------------------------
    # Save / Open dialogs
    # -------------------------
    def open_map_dialog(self):
        if not self.current_user:
            messagebox.showinfo("Login required", "Please login first.")
            return
        path = filedialog.askopenfilename(initialdir=user_maps_folder(self.current_user),
                                          filetypes=[("MindMap JSON", ".json"), ("All files", ".*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.canvas.load_from(data)
            # set current map id to basename (without .json)
            mid = os.path.splitext(os.path.basename(path))[0]
            self.current_map_id = mid
            idx = load_user_maps_index(self.current_user)
            if mid not in idx:
                idx[mid] = {"title": mid, "created": now_str(), "modified": now_str()}
                save_user_maps_index(self.current_user, idx)
            self.refresh_maps_list()
            self.log(f"Opened map from {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open: {e}")

    def save_map_shortcut(self, event=None):
        self.save_map()

    def save_map(self):
        if not self.current_user:
            messagebox.showinfo("Login required", "Please login first.")
            return
        if not self.current_map_id:
            # ask for map title and create id
            title = simpledialog.askstring("Save Map", "Map title:")
            if title is None:
                return
            self.current_map_id = str(uuid.uuid4())
            self.current_map_meta = {"title": title, "created": now_str(), "modified": now_str()}
        data = self.canvas.serialize()
        save_map_file(self.current_user, self.current_map_id, data)
        # update index
        idx = load_user_maps_index(self.current_user)
        meta = self.current_map_meta or {}
        meta["modified"] = now_str()
        if "created" not in meta:
            meta["created"] = now_str()
        idx[self.current_map_id] = meta
        save_user_maps_index(self.current_user, idx)
        self.refresh_maps_list()
        self.log(f"Saved map '{meta.get('title','untitled')}' (id={self.current_map_id})")
        self.status_var.set(f"Saved: {meta.get('title')}")

    # -------------------------
    # Canvas actions
    # -------------------------
    def canvas_start_connection(self):
        if not self.canvas.selected_item:
            self.log("Select a node first (left-click).")
            return
        self.canvas.start_connection()

    def delete_selected_node(self):
        if not self.canvas.selected_item:
            self.log("No node selected to delete.")
            return
        self.canvas.delete_node(self.canvas.selected_item)
        self.canvas.selected_item = None

    # -------------------------
    # Export
    # -------------------------
    def export_png(self):
        # ask where to save
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png")])
        if not path:
            return

        # Prefer Canvas.postscript -> PIL to generate PNG
        try:
            # get bbox of all canvas elements
            self.update_idletasks()
            bbox = self.canvas.bbox("all")
            if not bbox:
                messagebox.showinfo("Export", "Canvas is empty.")
                return
            x1, y1, x2, y2 = bbox
            # create postscript of canvas region
            ps = self.canvas.postscript(colormode='color', x=x1, y=y1, width=x2-x1, height=y2-y1)
            if PIL_AVAILABLE:
                img = Image.open(io.BytesIO(ps.encode('utf-8')))
                # postscript to image often needs conversion
                img = img.convert("RGBA")
                # save
                img.save(path, "PNG")
                self.log(f"Exported canvas to PNG: {path}")
                messagebox.showinfo("Exported", f"Saved PNG to:\n{path}")
            else:
                # fallback: try ImageGrab of window region (works on some platforms)
                try:
                    # get absolute coordinates of canvas on screen
                    self.update()
                    x = self.canvas.winfo_rootx() + x1
                    y = self.canvas.winfo_rooty() + y1
                    w = x2 - x1
                    h = y2 - y1
                    img = ImageGrab.grab((x, y, x + w, y + h))
                    img.save(path, "PNG")
                    self.log(f"Exported canvas to PNG (ImageGrab): {path}")
                    messagebox.showinfo("Exported", f"Saved PNG to:\n{path}")
                except Exception:
                    messagebox.showerror("Export failed", "Pillow not available and ImageGrab failed. Install Pillow.")
        except Exception as e:
            messagebox.showerror("Export failed", f"Failed to export PNG: {e}")

    # -------------------------
    # Other utilities
    # -------------------------
    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def show_about(self):
        messagebox.showinfo("About MindMapr", "MindMapr — simple mind mapping app\nBuilt with Tkinter.\n\nFeatures: create nodes (double-click), drag nodes, connect nodes, save/load maps per user.")

    def on_exit(self):
        # optionally ask to save current unsaved map
        if self.current_user and self.current_map_id:
            if messagebox.askyesno("Exit", "Save current map before exit?"):
                try:
                    self.save_map()
                except Exception:
                    pass
        self.destroy()

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app = MindMapApp()
    app.mainloop()
