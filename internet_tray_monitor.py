import os
import time
import threading
import subprocess
from datetime import datetime, timedelta
from collections import deque

import tkinter as tk
from PIL import Image, ImageTk
from plyer import notification

import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import style
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from pystray import Icon, MenuItem, Menu



# Konfiguration
PING_TARGETS = {
    "gateway": "192.168.178.1",
    "google": "8.8.8.8",
    "cloudflare": "1.1.1.1",
    "quad4": "4.4.4.4"
}
MIN_SUCCESSFUL_PINGS = 2
NORMAL_INTERVAL = 5
FAST_INTERVAL = 0.1
MAX_POINTS = 60

# Datenstruktur für Graphen
graph_data = {
    label: {"timestamps": deque(maxlen=MAX_POINTS), "rtts": deque(maxlen=MAX_POINTS)}
    for label in PING_TARGETS
}

# Systempfade
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
LOGFILE = os.path.join(DESKTOP, "internet_log.txt")
ICON_PATH = os.path.join(DESKTOP, "internet_monitor_no_border.ico")
OVERLAY_IMAGE_PATH = os.path.join(DESKTOP, "NoInternet.png")

# Statusvariablen
disconnected = False
disconnect_time = None
icon = None
running = True
overlay_window = None
graph_window = None
ani = None
outage_durations_by_day = {}
last_checked_date = datetime.now().date()

# Tkinter-Hauptinstanz
root = tk.Tk()
root.withdraw()

# Ping-Funktion: Prüft die Verbindung zu den definierten Hosts und misst RTTs.
def is_connected():
    success = 0
    rtts = {}

    for label, host in PING_TARGETS.items():
        try:
            output = subprocess.check_output(
                ["ping", host, "-n", "1"],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="cp850",
                errors="ignore"
            )

            if "TTL=" in output:
                success += 1
                if "Zeit=" in output:
                    time_part = output.split("Zeit=")[1].split("ms")[0].strip()
                    rtts[label] = int(time_part)
        except subprocess.CalledProcessError:
            pass

    return success >= MIN_SUCCESSFUL_PINGS, rtts



# Overlay bei Offline: Zeigt ein Overlay-Bild an, wenn keine Verbindung besteht.
def show_overlay_image():
    global overlay_window

    if overlay_window is not None:
        return

    def create_window():
        global overlay_window
        overlay_window = tk.Toplevel()
        overlay_window.overrideredirect(True)
        overlay_window.attributes("-topmost", True)
        overlay_window.configure(bg='black')
        overlay_window.wm_attributes("-transparentcolor", "black")

        screen_width = overlay_window.winfo_screenwidth()
        screen_height = overlay_window.winfo_screenheight()
        size = 100
        overlay_window.geometry(f"{size}x{size}+{screen_width - size - 30}+{screen_height - size - 80}")

        img = Image.open(OVERLAY_IMAGE_PATH).resize((size, size), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        label = tk.Label(overlay_window, image=photo, bg="black")
        label.image = photo
        label.pack()

    root.after(0, create_window)

# Overlay ausblenden: Entfernt das Overlay-Bild, wenn die Verbindung wiederhergestellt ist.
def hide_overlay_image():
    global overlay_window
    if overlay_window:
        overlay_window.destroy()
        overlay_window = None

# Tägliche Zusammenfassung: Schreibt eine Zusammenfassung der Ausfälle pro Tag in eine Datei.
def write_daily_summary(date_str, durations):
    if not durations:
        return

    summary_path = os.path.join(DESKTOP, "internet_summary.txt")

    total = sum(durations, timedelta())
    start_time = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), datetime.min.time())
    end_time = datetime.now()
    messdauer = end_time - start_time

    content = (
        f"📅 Datum: {date_str}\n"
        f"📊 Messzeit: {str(messdauer).split('.')[0]}\n"
        f"🔁 Ausfälle: {len(durations)}\n"
        f"🕒 Gesamtausfallzeit: {total}\n"
        f"⏱️ Längster Ausfall: {max(durations)}\n"
        f"🧘 Kürzester Ausfall: {min(durations)}\n\n"
    )

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(content)


# Verbindung prüfen und Logik: Überwacht die Verbindung und steuert Benachrichtigungen, Logging und Overlay.
def check_connection():
    global disconnected, disconnect_time, running, last_checked_date
    while running:
        current_date = datetime.now().date()
        if current_date != last_checked_date:
            prev_str = last_checked_date.strftime("%Y-%m-%d")
            if prev_str in outage_durations_by_day:
                write_daily_summary(prev_str, outage_durations_by_day[prev_str])
            last_checked_date = current_date

        connected, rtts = is_connected()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if connected:
            if rtts:
                now_dt = datetime.now()
                for label, rtt in rtts.items():
                    graph_data[label]["timestamps"].append(now_dt)
                    graph_data[label]["rtts"].append(rtt)

                avg_rtt = sum(rtts.values()) / len(rtts)
                with open(LOGFILE, "a", encoding="utf-8") as f:
                    f.write(f"[RTT] {now}: Ø {avg_rtt:.2f} ms → {rtts}\n")

            if disconnected:
                reconnect_time = datetime.now()
                duration = reconnect_time - disconnect_time
                date_str = disconnect_time.date().strftime("%Y-%m-%d")
                outage_durations_by_day.setdefault(date_str, []).append(duration)

                with open(LOGFILE, "a") as f:
                    f.write(f"[WIEDER ONLINE] {now} (dauerte {duration})\n")

                disconnected = False
                hide_overlay_image()

                notification.notify(
                    title="Internet wieder da",
                    message="Du bist wieder online.",
                    timeout=5
                )

            time.sleep(NORMAL_INTERVAL)

        else:
            if not disconnected:
                disconnect_time = datetime.now()
                with open(LOGFILE, "a") as f:
                    f.write(f"[OFFLINE] {now}\n")
                disconnected = True

                notification.notify(
                    title="Internet unterbrochen",
                    message="Verbindung getrennt.",
                    timeout=5
                )
                show_overlay_image()

            time.sleep(FAST_INTERVAL)

# RTT-Tracker: Misst regelmäßig die RTTs für die Diagrammdaten.
def rtt_tracker():
    while running:
        _, rtts = is_connected()
        now_dt = datetime.now()
        if rtts:
            for label, rtt in rtts.items():
                graph_data[label]["timestamps"].append(now_dt)
                graph_data[label]["rtts"].append(rtt)
        time.sleep(1)

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from datetime import timedelta

# Öffnet das Fenster mit den Live-RTT-Diagrammen.
def open_graph_window():
    global graph_window, ani
    if graph_window is not None:
        return

    graph_window = tk.Toplevel()
    graph_window.title("Live RTT-Diagramme")
    graph_window.geometry("1000x700")

    style.use("dark_background")
    fig, axes = plt.subplots(len(PING_TARGETS), 1, figsize=(10, 6), sharex=True)
    fig.tight_layout(pad=4.0)

    # Canvas + Toolbar
    canvas = FigureCanvasTkAgg(fig, master=graph_window)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill=tk.BOTH, expand=True)

    toolbar = NavigationToolbar2Tk(canvas, graph_window)
    toolbar.update()
    toolbar.pack(side=tk.TOP, fill=tk.X)

    lines = {}
    for ax, (label, data) in zip(axes, graph_data.items()):
        ax.set_title(f"RTT zu {label}", fontsize=10)
        ax.set_ylabel("ms")
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.grid(True, linestyle="--", alpha=0.3)
        lines[label], = ax.plot([], [], lw=2, color="lime", label=label)

    axes[-1].set_xlabel("Zeit")

    def update(frame):
        for i, (label, data) in enumerate(graph_data.items()):
            timestamps = data["timestamps"]
            rtts = data["rtts"]
            if len(timestamps) > 1:
                lines[label].set_data(timestamps, rtts)
                axes[i].set_xlim(timestamps[0], timestamps[-1])
                axes[i].set_ylim(0, max(rtts, default=50) + 10)
            elif len(timestamps) == 1:
                # Nur ein Punkt vorhanden → künstlicher X-Bereich
                t = timestamps[0]
                lines[label].set_data(timestamps, rtts)
                axes[i].set_xlim(t - timedelta(seconds=1), t + timedelta(seconds=1))
                axes[i].set_ylim(0, rtts[0] + 10)
        canvas.draw()
        return lines.values()

    ani = animation.FuncAnimation(fig, update, interval=1000, cache_frame_data=False)

    def on_close():
        global graph_window
        graph_window.destroy()
        graph_window = None

    graph_window.protocol("WM_DELETE_WINDOW", on_close)



# Tray-Icon Bild laden.
def create_image():
    return Image.open(ICON_PATH)

# Beenden-Funktion für das Tray-Icon.
def on_exit(icon, item):
    global running
    running = False
    icon.stop()

# Startet das Tray-Icon und die Hintergrund-Threads.
def start_tray():
    global icon
    menu = Menu(
        MenuItem("Live-Diagramm öffnen", lambda icon, item: root.after(0, open_graph_window)),
        MenuItem("Beenden", on_exit)
    )
    icon = Icon("InternetMonitor", create_image(), "Internet-Monitor", menu)
    
    # Startet Verbindungstracker
    threading.Thread(target=check_connection, daemon=True).start()
    
    # Startet separaten RTT-Tracker für Diagramme
    threading.Thread(target=rtt_tracker, daemon=True).start()
    
    icon.run()


# Hauptausführung: Startet das Tray-Icon und die Tkinter-Hauptschleife.
if __name__ == "__main__":
    threading.Thread(target=start_tray, daemon=True).start()
    root.mainloop()
