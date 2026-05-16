import tkinter as tk
from tkinter import filedialog, ttk
import os


def find_atom(data, name):
    enc = name.encode('ascii')
    pos = data.find(enc)
    return pos


def check_file(path):
    size = os.path.getsize(path)
    chunk = min(200000, size)
    with open(path, 'rb') as f:
        data = f.read(chunk)
    moov = find_atom(data, 'moov')
    mdat = find_atom(data, 'mdat')
    return moov, mdat, size


def browse_file():
    path = filedialog.askopenfilename(
        title="Select a video file",
        initialdir="D:/",
        filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")]
    )
    if not path:
        return

    filename_var.set(os.path.basename(path))
    path_var.set(path)

    try:
        moov, mdat, size = check_file(path)

        size_mb = size / 1024 / 1024
        size_var.set(f"{size_mb:.1f} MB")

        moov_var.set(f"byte {moov:,}" if moov != -1 else "not found")
        mdat_var.set(f"byte {mdat:,}" if mdat != -1 else "not in first 200KB")

        if moov == -1:
            result_var.set("Cannot determine")
            detail_var.set("moov atom not found in first 200KB.")
            result_label.config(fg="#b45309")
            detail_label.config(fg="#b45309")
            frame_result.config(bg="#fef3c7")
            result_label.config(bg="#fef3c7")
            detail_label.config(bg="#fef3c7")
        elif mdat == -1 or moov < mdat:
            result_var.set("Streaming ready")
            detail_var.set("moov is before mdat — browsers can play without downloading the full file.")
            result_label.config(fg="#166534")
            detail_label.config(fg="#166534")
            frame_result.config(bg="#dcfce7")
            result_label.config(bg="#dcfce7")
            detail_label.config(bg="#dcfce7")
        else:
            result_var.set("Not streaming-ready")
            detail_var.set("moov is after mdat. Fix: ffmpeg -i input.mp4 -movflags faststart -codec copy output.mp4")
            result_label.config(fg="#991b1b")
            detail_label.config(fg="#991b1b")
            frame_result.config(bg="#fee2e2")
            result_label.config(bg="#fee2e2")
            detail_label.config(bg="#fee2e2")

        frame_result.pack(fill="x", padx=16, pady=(0, 16))
        frame_stats.pack(fill="x", padx=16, pady=(0, 16))

    except Exception as e:
        result_var.set("Error")
        detail_var.set(str(e))
        result_label.config(fg="#991b1b")
        detail_label.config(fg="#991b1b")
        frame_result.config(bg="#fee2e2")
        result_label.config(bg="#fee2e2")
        detail_label.config(bg="#fee2e2")
        frame_result.pack(fill="x", padx=16, pady=(0, 16))
        frame_stats.pack_forget()


root = tk.Tk()
root.title("MP4 Streaming Checker")
root.geometry("520x380")
root.resizable(False, False)
root.configure(bg="#f8f8f8")

filename_var = tk.StringVar(value="No file selected")
path_var = tk.StringVar()
size_var = tk.StringVar()
moov_var = tk.StringVar()
mdat_var = tk.StringVar()
result_var = tk.StringVar()
detail_var = tk.StringVar()

# Header
tk.Label(root, text="MP4 Streaming Checker", font=("Segoe UI", 14, "bold"),
         bg="#f8f8f8", fg="#111").pack(pady=(20, 4))
tk.Label(root, text="Checks whether a video file has its moov atom before mdat (web-optimized).",
         font=("Segoe UI", 9), bg="#f8f8f8", fg="#666", wraplength=460).pack(pady=(0, 16))

# Browse button + filename
frame_browse = tk.Frame(root, bg="#f8f8f8")
frame_browse.pack(fill="x", padx=16, pady=(0, 12))

tk.Button(frame_browse, text="Select file", command=browse_file,
          font=("Segoe UI", 10), bg="#1d4ed8", fg="white",
          activebackground="#1e40af", activeforeground="white",
          relief="flat", padx=12, pady=6, cursor="hand2").pack(side="left")

tk.Label(frame_browse, textvariable=filename_var,
         font=("Segoe UI", 9), bg="#f8f8f8", fg="#444",
         wraplength=340, anchor="w").pack(side="left", padx=(12, 0))

# Stats frame (hidden until file loaded)
frame_stats = tk.Frame(root, bg="white", relief="flat",
                        highlightbackground="#e5e7eb", highlightthickness=1)

def stat_row(parent, label, var):
    row = tk.Frame(parent, bg="white")
    row.pack(fill="x", padx=12, pady=3)
    tk.Label(row, text=label, font=("Segoe UI", 9), bg="white",
             fg="#6b7280", width=14, anchor="w").pack(side="left")
    tk.Label(row, textvariable=var, font=("Segoe UI", 9, "bold"),
             bg="white", fg="#111", anchor="w").pack(side="left")

tk.Frame(frame_stats, height=8, bg="white").pack()
stat_row(frame_stats, "File size:", size_var)
stat_row(frame_stats, "moov position:", moov_var)
stat_row(frame_stats, "mdat position:", mdat_var)
tk.Frame(frame_stats, height=8, bg="white").pack()

# Result frame (hidden until file loaded)
frame_result = tk.Frame(root, relief="flat",
                         highlightbackground="#e5e7eb", highlightthickness=1)

tk.Frame(frame_result, height=10, bg="#dcfce7").pack()
result_label = tk.Label(frame_result, textvariable=result_var,
                         font=("Segoe UI", 11, "bold"), bg="#dcfce7", fg="#166534")
result_label.pack(padx=12)
detail_label = tk.Label(frame_result, textvariable=detail_var,
                         font=("Segoe UI", 9), bg="#dcfce7", fg="#166534",
                         wraplength=460, justify="left")
detail_label.pack(padx=12, pady=(2, 10))

root.mainloop()