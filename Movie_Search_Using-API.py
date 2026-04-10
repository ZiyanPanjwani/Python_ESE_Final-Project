import tkinter as tk
from tkinter import messagebox
import requests
from PIL import Image, ImageTk
from io import BytesIO
import threading
import webbrowser
import time

API_KEY  = "f2879d329b801ef734305dbbd0ba58f9"
BASE     = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w185"
FILE     = "users.txt"

current_user = None
image_refs   = []
main_canvas  = None
scroll_frame = None

# ── PALETTE ──────────────────────────────────────────────────
BG         = "#0A0A0A"
SURFACE    = "#141414"
SURFACE2   = "#1E1E1E"
BORDER     = "#2A2A2A"
TEXT_PRI   = "#F0F0F0"
TEXT_SEC   = "#888888"
ACCENT     = "#E8FF47"
ACCENT_DIM = "#B8CC30"
STAR       = "#F5C518"
ERR        = "#FF5F5F"
TRAILER    = "#FF4444"
TRAILER_DIM= "#CC2222"

FONT_HEAD  = ("Courier New", 13, "bold")
FONT_BODY  = ("Helvetica", 10)
FONT_SMALL = ("Helvetica", 9)
FONT_HERO  = ("Courier New", 20, "bold")
FONT_LABEL = ("Helvetica", 9)
FONT_BTN   = ("Courier New", 10, "bold")

COLS = 5  # number of columns in grid


# ── USER AUTH ────────────────────────────────────────────────

def load_users():
    users = {}
    try:
        with open(FILE, "r") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 2:
                    users[parts[0]] = parts[1]
    except FileNotFoundError:
        pass
    return users


def save_user(username, password):
    with open(FILE, "a") as f:
        f.write(f"{username},{password}\n")


def login():
    global current_user
    users = load_users()
    u, p = entry_user.get().strip(), entry_pass.get().strip()
    if not u or not p:
        _flash(login_err_lbl, "Fill both fields")
        return
    if u in users and users[u] == p:
        current_user = u
        login_win.destroy()
        open_main()
    else:
        _flash(login_err_lbl, "Invalid credentials")


def register():
    u = entry_user.get().strip()
    p = entry_pass.get().strip()
    if not u or not p:
        _flash(login_err_lbl, "Fill both fields")
        return
    users = load_users()
    if u in users:
        _flash(login_err_lbl, "Username already exists")
        return
    save_user(u, p)
    _flash(login_err_lbl, "Registered — you can log in now", ok=True)


def _flash(label, msg, ok=False):
    label.config(text=msg, fg=ACCENT if ok else ERR)


# ── TMDB API ─────────────────────────────────────────────────

def _get(endpoint, params=None, retries=2):
    """Generic TMDB GET with retry. Returns (data, error)."""
    if params is None:
        params = {}
    params["api_key"] = API_KEY
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{endpoint}", params=params, timeout=12)
            if r.status_code == 401:
                return None, "Invalid API key. Get a free one at themoviedb.org/settings/api"
            if not r.ok:
                return None, f"Server error {r.status_code}."
            return r.json(), None
        except requests.exceptions.ConnectionError:
            if attempt < retries - 1:
                time.sleep(1.5)
                continue
            return None, "No internet connection."
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None, "Request timed out."
        except Exception as e:
            return None, str(e)


def _normalize(item):
    """Convert TMDB movie dict to internal format."""
    poster_path = item.get("poster_path") or ""
    poster_url  = f"{IMG_BASE}{poster_path}" if poster_path else ""

    rating = item.get("vote_average", 0.0)
    try:
        rating = float(rating)
    except (ValueError, TypeError):
        rating = 0.0

    return {
        "tmdb_id":      item.get("id", ""),
        "title":        item.get("title") or item.get("name") or "Untitled",
        "release_date": (item.get("release_date") or "")[:4],
        "vote_average": round(rating, 1),
        "overview":     item.get("overview") or "No description available.",
        "poster_url":   poster_url,
        "genre_ids":    item.get("genre_ids", []),
        "_raw":         item,
    }


def _fetch_movies(endpoint, params=None):
    data, err = _get(endpoint, params or {})
    if data is None:
        return [], err
    results = data.get("results", [])
    return [_normalize(m) for m in results[:20]], None


def get_movies(section):
    endpoints = {
        "trending":  "/trending/movie/week",
        "popular":   "/movie/popular",
        "top_rated": "/movie/top_rated",
    }
    ep = endpoints.get(section, "/trending/movie/week")
    return _fetch_movies(ep)


def search_movies(query):
    return _fetch_movies("/search/movie", {"query": query, "include_adult": "false"})


def get_movie_detail(tmdb_id):
    data, err = _get(f"/movie/{tmdb_id}", {"append_to_response": "credits"})
    return data, err


def get_trailers(tmdb_id):
    data, err = _get(f"/movie/{tmdb_id}/videos")
    if data is None:
        return [], err
    videos = data.get("results", [])
    trailers = [
        v for v in videos
        if v.get("site") == "YouTube"
        and v.get("type") in ("Trailer", "Teaser")
    ]
    return trailers, None


# ── POSTER LOADER ────────────────────────────────────────────

def _widget_exists(widget):
    """Return True if the tkinter widget still exists."""
    try:
        return widget.winfo_exists()
    except Exception:
        return False


def show_poster(label, url):
    def load():
        try:
            data  = requests.get(url, timeout=8).content
            img   = Image.open(BytesIO(data)).resize((130, 195), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            image_refs.append(photo)
            if _widget_exists(label):
                label.config(image=photo, bg=SURFACE)
        except Exception:
            if _widget_exists(label):
                label.config(text="🎬", font=("Helvetica", 28), fg=TEXT_SEC)
    threading.Thread(target=load, daemon=True).start()


# ── MOVIE GRID ───────────────────────────────────────────────

def _clear_grid():
    for w in scroll_frame.winfo_children():
        w.destroy()


def _make_card(parent, movie, row, col):
    """Create a single movie card and place it at (row, col)."""
    card = tk.Frame(parent, bg=SURFACE,
                    highlightbackground=BORDER,
                    highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8, sticky="n")

    poster = tk.Label(card, bg=SURFACE2, width=130, height=195,
                      text="…", fg=TEXT_SEC, font=FONT_SMALL)
    poster.pack()

    if movie.get("poster_url"):
        show_poster(poster, movie["poster_url"])

    info = tk.Frame(card, bg=SURFACE, padx=8, pady=6)
    info.pack(fill="x")

    title = (movie.get("title") or "Untitled")[:20]
    tk.Label(info, text=title, bg=SURFACE, fg=TEXT_PRI,
             font=("Courier New", 9, "bold"), anchor="w").pack(fill="x")

    rating_row = tk.Frame(info, bg=SURFACE)
    rating_row.pack(fill="x", pady=(2, 0))

    tk.Label(rating_row, text="★", bg=SURFACE,
             fg=STAR, font=FONT_SMALL).pack(side="left")
    rating = movie.get("vote_average", 0)
    rating_text = f" {rating:.1f}" if rating else " N/A"
    tk.Label(rating_row, text=rating_text,
             bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL).pack(side="left")

    year = movie.get("release_date", "")
    if year:
        tk.Label(rating_row, text=f"  {year}",
                 bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL).pack(side="left")

    all_widgets = (
        [card, poster, info]
        + list(info.winfo_children())
        + list(rating_row.winfo_children())
    )

    def _enter(e, c=card): c.config(highlightbackground=ACCENT)
    def _leave(e, c=card): c.config(highlightbackground=BORDER)

    for w in all_widgets:
        w.bind("<Button-1>", lambda e, m=movie: open_detail(m))
        w.bind("<Enter>",    _enter)
        w.bind("<Leave>",    _leave)


def show_movies(movies, error=None):
    _clear_grid()

    # ── configure uniform column weights so grid is always left-aligned ──
    for c in range(COLS):
        scroll_frame.columnconfigure(c, weight=0, minsize=0)

    if error:
        err_frame = tk.Frame(scroll_frame, bg=BG)
        err_frame.grid(row=0, column=0, columnspan=COLS, pady=60)

        tk.Label(err_frame, text="⚠  Could not load movies",
                 fg=ERR, bg=BG, font=FONT_HEAD).pack()
        tk.Label(err_frame, text=error,
                 fg=TEXT_SEC, bg=BG, font=FONT_BODY).pack(pady=(6, 0))
        tk.Button(err_frame, text="↺  RETRY",
                  command=load_trending,
                  bg=ACCENT, fg="#0A0A0A",
                  font=FONT_BTN, relief="flat", cursor="hand2",
                  padx=14, pady=7, bd=0).pack(pady=(16, 0))
        return

    if not movies:
        tk.Label(scroll_frame, text="No results found.",
                 fg=TEXT_SEC, bg=BG, font=FONT_BODY).grid(
                     row=0, column=0, columnspan=COLS, pady=60)
        return

    # ── layout: always COLS columns, left-to-right, top-to-bottom ──
    for i, movie in enumerate(movies[:20]):
        row = i // COLS
        col = i % COLS
        _make_card(scroll_frame, movie, row, col)

    # fill empty cells in the last row with spacer frames so alignment is even
    total       = len(movies[:20])
    remainder   = total % COLS
    if remainder != 0:
        last_row = total // COLS
        for col in range(remainder, COLS):
            spacer = tk.Frame(scroll_frame, bg=BG, width=146, height=1)
            spacer.grid(row=last_row, column=col, padx=8, pady=8, sticky="n")

    scroll_frame.update_idletasks()
    main_canvas.configure(scrollregion=main_canvas.bbox("all"))


# ── DETAIL POPUP ─────────────────────────────────────────────

def open_detail(movie):
    win = tk.Toplevel()
    win.title("")
    win.geometry("560x520")
    win.configure(bg=SURFACE)
    win.resizable(False, False)

    tk.Frame(win, bg=ACCENT, height=3).pack(fill="x")

    body = tk.Frame(win, bg=SURFACE, padx=28, pady=22)
    body.pack(fill="both", expand=True)

    tk.Label(body,
             text=(movie.get("title") or "").upper(),
             bg=SURFACE, fg=TEXT_PRI,
             font=("Courier New", 14, "bold"),
             wraplength=500, justify="left",
             anchor="w").pack(fill="x")

    meta = tk.Frame(body, bg=SURFACE)
    meta.pack(fill="x", pady=(6, 4))

    year   = movie.get("release_date", "") or "—"
    rating = movie.get("vote_average", 0)

    tk.Label(meta, text=year,
             bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL).pack(side="left")

    rating_display = f"  ★ {rating:.1f}" if rating else "  ★ N/A"
    tk.Label(meta, text=rating_display,
             bg=SURFACE, fg=STAR, font=FONT_SMALL).pack(side="left")

    extra_label = tk.Label(body, text="Loading details…",
                           bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL, anchor="w")
    extra_label.pack(fill="x", pady=(2, 0))

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(10, 14))

    overview = movie.get("overview") or "No description available."
    tk.Label(body, text=overview,
             bg=SURFACE, fg=TEXT_SEC,
             font=("Helvetica", 10),
             wraplength=500, justify="left",
             anchor="nw").pack(fill="x")

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(16, 10))

    trailer_frame = tk.Frame(body, bg=SURFACE)
    trailer_frame.pack(fill="x")

    trailer_status = tk.Label(trailer_frame, text="Fetching trailers…",
                               bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL)
    trailer_status.pack(anchor="w")

    btn_row = tk.Frame(body, bg=SURFACE)
    btn_row.pack(fill="x", pady=(16, 0))

    tk.Button(btn_row, text="+ FAVOURITE",
              command=lambda: add_favourite(movie),
              bg=ACCENT, fg="#0A0A0A",
              font=FONT_BTN, relief="flat", cursor="hand2",
              padx=14, pady=7,
              activebackground=ACCENT_DIM,
              activeforeground="#0A0A0A", bd=0).pack(side="left")

    tk.Button(btn_row, text="CLOSE",
              command=win.destroy,
              bg=SURFACE2, fg=TEXT_SEC,
              font=FONT_BTN, relief="flat", cursor="hand2",
              padx=14, pady=7,
              activebackground=BORDER,
              activeforeground=TEXT_PRI, bd=0).pack(side="left", padx=(10, 0))

    tmdb_id = movie.get("tmdb_id", "")

    def fetch_all():
        detail, _ = get_movie_detail(tmdb_id)
        if detail and _widget_exists(win):
            runtime  = detail.get("runtime", 0)
            genres   = ", ".join(g["name"] for g in detail.get("genres", []))
            credits  = detail.get("credits", {})
            director = next(
                (c["name"] for c in credits.get("crew", []) if c["job"] == "Director"),
                ""
            )
            parts = []
            if runtime:  parts.append(f"{runtime} min")
            if genres:   parts.append(genres)
            if director: parts.append(f"Dir: {director}")
            extra_text = "  ·  ".join(parts) if parts else ""
            if _widget_exists(extra_label):
                win.after(0, lambda t=extra_text: extra_label.config(text=t if t else ""))

        trailers, _ = get_trailers(tmdb_id)

        def build_trailer_ui():
            if not _widget_exists(win):
                return
            trailer_status.destroy()
            if not trailers:
                tk.Label(trailer_frame, text="No trailers available.",
                         bg=SURFACE, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w")
                return

            tk.Label(trailer_frame, text="TRAILERS",
                     bg=SURFACE, fg=TEXT_SEC,
                     font=("Courier New", 8, "bold")).pack(anchor="w", pady=(0, 6))

            for t in trailers[:3]:
                key  = t.get("key", "")
                name = t.get("name", "Trailer")
                url  = f"https://www.youtube.com/watch?v={key}"

                row = tk.Frame(trailer_frame, bg=SURFACE)
                row.pack(fill="x", pady=2)

                icon = tk.Label(row, text="▶", bg=SURFACE,
                                fg=TRAILER, font=("Helvetica", 9))
                icon.pack(side="left")

                lbl = tk.Label(row, text=f"  {name[:50]}",
                               bg=SURFACE, fg=TEXT_PRI,
                               font=("Helvetica", 9),
                               cursor="hand2", anchor="w")
                lbl.pack(side="left")

                def _open(e, u=url):
                    webbrowser.open(u)

                def _hover_in(e, l=lbl, i=icon):
                    l.config(fg=ACCENT); i.config(fg=ACCENT)

                def _hover_out(e, l=lbl, i=icon):
                    l.config(fg=TEXT_PRI); i.config(fg=TRAILER)

                for w in (lbl, icon):
                    w.bind("<Button-1>", _open)
                    w.bind("<Enter>",    _hover_in)
                    w.bind("<Leave>",    _hover_out)

        win.after(0, build_trailer_ui)

    threading.Thread(target=fetch_all, daemon=True).start()


# ── FAVOURITES ───────────────────────────────────────────────

def add_favourite(movie):
    title = movie.get("title", "")
    if not title:
        return
    fav_file = f"{current_user}_favs.txt"
    try:
        with open(fav_file, "r", encoding="utf-8") as f:
            existing = [l.strip() for l in f.readlines()]
    except FileNotFoundError:
        existing = []

    if title in existing:
        messagebox.showinfo("Already saved", f"'{title}' is already in favourites.")
        return

    with open(fav_file, "a", encoding="utf-8") as f:
        tmdb_id = movie.get("tmdb_id", "")
        year    = movie.get("release_date", "")
        f.write(f"{title}|{tmdb_id}|{year}\n")

    messagebox.showinfo("Saved", f"'{title}' added to favourites.")


def show_favourites():
    win = tk.Toplevel()
    win.title("Favourites")
    win.geometry("420x500")
    win.configure(bg=SURFACE)
    win.resizable(False, False)

    tk.Frame(win, bg=ACCENT, height=3).pack(fill="x")

    header = tk.Frame(win, bg=SURFACE, padx=24, pady=18)
    header.pack(fill="x")

    tk.Label(header, text="FAVOURITES",
             bg=SURFACE, fg=TEXT_PRI,
             font=("Courier New", 13, "bold")).pack(anchor="w")

    tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=24)

    fav_file = f"{current_user}_favs.txt"
    try:
        with open(fav_file, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        lines = []

    list_frame = tk.Frame(win, bg=SURFACE, padx=24, pady=12)
    list_frame.pack(fill="both", expand=True)

    if not lines:
        tk.Label(list_frame, text="Nothing saved yet.",
                 bg=SURFACE, fg=TEXT_SEC, font=FONT_BODY).pack(pady=30)
        return

    for i, line in enumerate(lines):
        parts = line.split("|")
        title = parts[0]
        year  = parts[2] if len(parts) > 2 else ""

        row = tk.Frame(list_frame, bg=SURFACE, pady=7)
        row.pack(fill="x")

        tk.Label(row, text=f"{i+1:02d}",
                 bg=SURFACE, fg=ACCENT,
                 font=("Courier New", 9, "bold"),
                 width=3, anchor="w").pack(side="left")

        tk.Label(row, text=title,
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Helvetica", 10),
                 anchor="w").pack(side="left", padx=(6, 0))

        if year:
            tk.Label(row, text=f"({year})",
                     bg=SURFACE, fg=TEXT_SEC,
                     font=FONT_SMALL).pack(side="left", padx=(6, 0))

        tk.Frame(list_frame, bg=BORDER, height=1).pack(fill="x")


# ── FEEDBACK ─────────────────────────────────────────────────

def give_feedback():
    win = tk.Toplevel()
    win.title("")
    win.geometry("460x400")
    win.configure(bg=SURFACE)
    win.resizable(False, False)

    tk.Frame(win, bg=ACCENT, height=3).pack(fill="x")

    body = tk.Frame(win, bg=SURFACE, padx=28, pady=22)
    body.pack(fill="both", expand=True)

    tk.Label(body, text="SEND FEEDBACK",
             bg=SURFACE, fg=TEXT_PRI,
             font=("Courier New", 13, "bold")).pack(anchor="w")

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(10, 16))

    tk.Label(body, text="RATING",
             bg=SURFACE, fg=TEXT_SEC,
             font=("Courier New", 8, "bold")).pack(anchor="w")

    star_frame = tk.Frame(body, bg=SURFACE)
    star_frame.pack(anchor="w", pady=(4, 14))

    rating_var = tk.IntVar(value=5)
    star_btns  = []

    def update_stars(val):
        rating_var.set(val)
        for j, sb in enumerate(star_btns):
            sb.config(fg=STAR if j < val else TEXT_SEC)

    for i in range(1, 6):
        sb = tk.Label(star_frame, text="★",
                      bg=SURFACE, fg=STAR,
                      font=("Helvetica", 16),
                      cursor="hand2")
        sb.pack(side="left", padx=2)
        star_btns.append(sb)
        sb.bind("<Button-1>", lambda e, v=i: update_stars(v))

    tk.Label(body, text="MESSAGE",
             bg=SURFACE, fg=TEXT_SEC,
             font=("Courier New", 8, "bold")).pack(anchor="w")

    text_box = tk.Text(body, height=7, width=44,
                       bg=SURFACE2, fg=TEXT_PRI,
                       insertbackground=ACCENT,
                       relief="flat",
                       font=("Helvetica", 10),
                       padx=10, pady=8,
                       highlightthickness=1,
                       highlightbackground=BORDER,
                       highlightcolor=ACCENT)
    text_box.pack(pady=(4, 16))

    def submit():
        feedback = text_box.get("1.0", tk.END).strip()
        if not feedback:
            messagebox.showwarning("Empty", "Please write a message.")
            return
        with open("feedback.txt", "a", encoding="utf-8") as f:
            f.write(f"{current_user} | {rating_var.get()}/5 | {feedback}\n")
        messagebox.showinfo("Done", "Feedback submitted. Thank you!")
        win.destroy()

    tk.Button(body, text="SUBMIT",
              command=submit,
              bg=ACCENT, fg="#0A0A0A",
              font=FONT_BTN, relief="flat", cursor="hand2",
              padx=16, pady=7,
              activebackground=ACCENT_DIM,
              activeforeground="#0A0A0A", bd=0).pack(anchor="w")


# ── MAIN WINDOW ──────────────────────────────────────────────

def show_loading():
    _clear_grid()
    tk.Label(scroll_frame, text="Loading…",
             fg=TEXT_SEC, bg=BG, font=FONT_BODY).grid(
                 row=0, column=0, columnspan=COLS, pady=60)


def _set_section(text):
    section_label.config(text=text)


def _fetch_and_show(label_text, section):
    _set_section(label_text)
    show_loading()
    def fetch():
        movies, err = get_movies(section)
        root.after(0, lambda: show_movies(movies, err))
    threading.Thread(target=fetch, daemon=True).start()


def load_trending():
    _fetch_and_show("TRENDING  /  This Week", "trending")


def load_top_rated():
    _fetch_and_show("TOP RATED", "top_rated")


def load_popular():
    _fetch_and_show("POPULAR", "popular")


def do_search():
    query = search_entry.get().strip()
    if not query:
        return
    _set_section(f'SEARCH  /  "{query}"')
    show_loading()
    def fetch():
        movies, err = search_movies(query)
        root.after(0, lambda: show_movies(movies, err))
    threading.Thread(target=fetch, daemon=True).start()


def _nav_btn(parent, text, cmd):
    btn = tk.Button(parent, text=text, command=cmd,
                    bg="#0A0A0A", fg=TEXT_SEC,
                    font=("Courier New", 9, "bold"),
                    relief="flat", cursor="hand2",
                    padx=10, pady=6,
                    activebackground="#0A0A0A",
                    activeforeground=ACCENT, bd=0)
    btn.pack(side="left", padx=2)
    btn.bind("<Enter>", lambda e: btn.config(fg=ACCENT))
    btn.bind("<Leave>", lambda e: btn.config(fg=TEXT_SEC))
    return btn


def open_main():
    global root, scroll_frame, main_canvas, section_label, search_entry

    root = tk.Tk()
    root.title("CINEMIN")
    root.geometry("980x680")
    root.configure(bg=BG)

    # ── Header ──────────────────────────────────────────────
    header = tk.Frame(root, bg="#0A0A0A")
    header.pack(fill="x")

    logo_frame = tk.Frame(header, bg="#0A0A0A", padx=16, pady=12)
    logo_frame.pack(side="left")
    tk.Label(logo_frame, text="CINE", font=("Courier New", 18, "bold"),
             fg=TEXT_PRI, bg="#0A0A0A").pack(side="left")
    tk.Label(logo_frame, text="MIN", font=("Courier New", 18, "bold"),
             fg=ACCENT, bg="#0A0A0A").pack(side="left")

    tk.Frame(header, bg=BORDER, width=1).pack(side="left", fill="y", pady=8)

    nav = tk.Frame(header, bg="#0A0A0A", padx=8)
    nav.pack(side="left", fill="y")

    _nav_btn(nav, "TRENDING",   load_trending)
    _nav_btn(nav, "TOP RATED",  load_top_rated)
    _nav_btn(nav, "POPULAR",    load_popular)
    _nav_btn(nav, "FAVOURITES", show_favourites)
    _nav_btn(nav, "FEEDBACK",   give_feedback)

    user_frame = tk.Frame(header, bg="#0A0A0A", padx=12, pady=14)
    user_frame.pack(side="right")
    tk.Label(user_frame, text=f"● {current_user}",
             bg="#0A0A0A", fg=ACCENT,
             font=("Courier New", 9, "bold")).pack(side="right")

    search_outer = tk.Frame(header, bg="#0A0A0A", padx=10, pady=12)
    search_outer.pack(side="right")

    search_box = tk.Frame(search_outer, bg=SURFACE2,
                          highlightthickness=1,
                          highlightbackground=BORDER,
                          highlightcolor=ACCENT)
    search_box.pack(side="left")

    search_entry = tk.Entry(search_box, width=22,
                            bg=SURFACE2, fg=TEXT_PRI,
                            insertbackground=ACCENT,
                            relief="flat",
                            font=("Helvetica", 10), bd=0)
    search_entry.pack(side="left", padx=(10, 4), ipady=7)
    search_entry.bind("<Return>", lambda e: do_search())

    tk.Button(search_box, text="→",
              command=do_search,
              bg=ACCENT, fg="#0A0A0A",
              font=("Courier New", 11, "bold"),
              relief="flat", cursor="hand2",
              padx=10, pady=4,
              activebackground=ACCENT_DIM, bd=0).pack(side="left")

    # ── Divider ─────────────────────────────────────────────
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

    # ── Section label ───────────────────────────────────────
    section_row = tk.Frame(root, bg=BG, padx=20, pady=14)
    section_row.pack(fill="x")

    section_label = tk.Label(section_row, text="",
                             font=("Courier New", 11, "bold"),
                             fg=TEXT_PRI, bg=BG, anchor="w")
    section_label.pack(side="left")

    tk.Label(section_row,
             text="Powered by TMDB",
             bg=BG, fg=TEXT_SEC,
             font=("Helvetica", 8)).pack(side="right")

    # ── Scrollable grid ─────────────────────────────────────
    container = tk.Frame(root, bg=BG)
    container.pack(fill="both", expand=True)

    main_canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
    scrollbar   = tk.Scrollbar(container, orient="vertical",
                               command=main_canvas.yview,
                               bg=SURFACE, troughcolor=BG,
                               activebackground=ACCENT)
    main_canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    main_canvas.pack(side="left", fill="both", expand=True)

    # inner frame — fixed width so grid never stretches or floats
    scroll_frame = tk.Frame(main_canvas, bg=BG)
    canvas_window = main_canvas.create_window(
        (16, 10), window=scroll_frame, anchor="nw"
    )

    def _on_canvas_resize(event):
        # keep scroll_frame at a fixed width; do not stretch it
        pass

    scroll_frame.bind(
        "<Configure>",
        lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
    )

    root.bind_all("<MouseWheel>",
                  lambda e: main_canvas.yview_scroll(
                      -1 * (e.delta // 120), "units"))
    root.bind_all("<Button-4>",
                  lambda e: main_canvas.yview_scroll(-1, "units"))
    root.bind_all("<Button-5>",
                  lambda e: main_canvas.yview_scroll(1, "units"))

    # delay first load slightly to let the window + network stack settle
    root.after(300, load_trending)
    root.mainloop()


# ── LOGIN WINDOW ─────────────────────────────────────────────

login_win = tk.Tk()
login_win.title("CINEMIN")
login_win.geometry("360x480")
login_win.resizable(False, False)
login_win.configure(bg=BG)

tk.Frame(login_win, bg=ACCENT, height=3).pack(fill="x")

wrap = tk.Frame(login_win, bg=BG, padx=40, pady=0)
wrap.pack(fill="both", expand=True)

logo_row = tk.Frame(wrap, bg=BG)
logo_row.pack(pady=(36, 4))
tk.Label(logo_row, text="CINE", font=("Courier New", 28, "bold"),
         fg=TEXT_PRI, bg=BG).pack(side="left")
tk.Label(logo_row, text="MIN", font=("Courier New", 28, "bold"),
         fg=ACCENT, bg=BG).pack(side="left")

tk.Label(wrap, text="Your minimal movie companion",
         bg=BG, fg=TEXT_SEC,
         font=("Helvetica", 9)).pack(pady=(0, 6))

tk.Label(wrap, text="Powered by TMDB",
         bg=BG, fg=TEXT_SEC,
         font=("Helvetica", 8)).pack(pady=(0, 28))

tk.Label(wrap, text="USERNAME", bg=BG, fg=TEXT_SEC,
         font=("Courier New", 8, "bold"), anchor="w").pack(fill="x")
entry_user = tk.Entry(wrap, bg=SURFACE2, fg=TEXT_PRI,
                      insertbackground=ACCENT, relief="flat",
                      font=("Helvetica", 11),
                      highlightthickness=1,
                      highlightbackground=BORDER,
                      highlightcolor=ACCENT, bd=0)
entry_user.pack(fill="x", ipady=9, pady=(4, 14))

tk.Label(wrap, text="PASSWORD", bg=BG, fg=TEXT_SEC,
         font=("Courier New", 8, "bold"), anchor="w").pack(fill="x")
entry_pass = tk.Entry(wrap, show="•", bg=SURFACE2, fg=TEXT_PRI,
                      insertbackground=ACCENT, relief="flat",
                      font=("Helvetica", 11),
                      highlightthickness=1,
                      highlightbackground=BORDER,
                      highlightcolor=ACCENT, bd=0)
entry_pass.pack(fill="x", ipady=9, pady=(4, 6))

login_err_lbl = tk.Label(wrap, text="", bg=BG, fg=ERR,
                          font=("Helvetica", 9))
login_err_lbl.pack(pady=(0, 16))

tk.Button(wrap, text="LOG IN", command=login,
          bg=ACCENT, fg="#0A0A0A",
          font=("Courier New", 10, "bold"),
          relief="flat", cursor="hand2",
          padx=0, pady=10,
          activebackground=ACCENT_DIM,
          activeforeground="#0A0A0A", bd=0).pack(fill="x")

reg_row = tk.Frame(wrap, bg=BG)
reg_row.pack(pady=(12, 0))
tk.Label(reg_row, text="No account?",
         bg=BG, fg=TEXT_SEC,
         font=("Helvetica", 9)).pack(side="left")
reg_btn = tk.Label(reg_row, text="  Register",
                   bg=BG, fg=ACCENT,
                   font=("Courier New", 9, "bold"),
                   cursor="hand2")
reg_btn.pack(side="left")
reg_btn.bind("<Button-1>", lambda e: register())

entry_pass.bind("<Return>", lambda e: login())
entry_user.bind("<Return>", lambda e: entry_pass.focus_set())

login_win.mainloop()
