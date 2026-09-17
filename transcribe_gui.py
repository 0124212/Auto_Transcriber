#!/usr/bin/env python3
"""
Modern GUI launcher for Mojidori
Provides an easy-to-use interface with presets and advanced settings
Cross-platform: Works on Windows and macOS
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import sys
import platform
from pathlib import Path

# Detect OS and set appropriate font
def get_system_font():
    """Return the best system font for the current OS"""
    system = platform.system()
    if system == "Windows":
        return "Segoe UI"
    elif system == "Darwin":  # macOS
        return "SF Pro Display"  # Falls back to Helvetica Neue if not available
    else:  # Linux
        return "Ubuntu"  # Falls back to system default

FONT_FAMILY = get_system_font()

# Font configuration (optimized for readability)
TITLE_FONT = (FONT_FAMILY, 22, "bold")
SECTION_FONT = (FONT_FAMILY, 16, "bold")
BUTTON_FONT = (FONT_FAMILY, 14, "bold")
LABEL_FONT = (FONT_FAMILY, 13)
SMALL_FONT = (FONT_FAMILY, 12)

# Color palette (accessible & easy on eyes)
TEXT_PRIMARY = "#1F2937"    # Dark gray (not black)
TEXT_SECONDARY = "#4B5563"  # Medium gray
TEXT_MUTED = "#9CA3AF"      # Light gray

BG_MAIN = "#F9FAFB"         # Light gray background
BG_SECTION = "#FFFFFF"      # White sections

GREEN_PRIMARY = "#16A34A"   # Modern green
GREEN_HOVER = "#15803D"     # Darker green on hover

BLUE_PRIMARY = "#2563EB"    # Modern blue
BLUE_HOVER = "#1D4ED8"      # Darker blue on hover

# Default preset settings
PRESETS = {
    "Fast (Lower Quality)": {
        "model": "small",
        "normalize_audio": True,
        "timestamps": False,
        "segments": True,
        "language": "en",
        "device": "auto"
    },
    "Balanced (Recommended)": {
        "model": "large-v3",
        "normalize_audio": True,
        "timestamps": True,
        "segments": True,
        "language": "en",
        "device": "auto"
    },
    "Best Quality (Slow)": {
        "model": "large-v3",
        "normalize_audio": True,
        "timestamps": True,
        "segments": True,
        "language": "en",
        "device": "auto"
    }
}

# Common languages
LANGUAGES = {
    "Auto-detect": None,
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko"
}


class TranscriptionGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mojidori")
        self.root.geometry("620x850")
        self.root.resizable(True, True)
        self.root.minsize(620, 850)
        self.root.configure(bg=BG_MAIN)
        
        # Set default font for all widgets
        self.root.option_add("*Font", LABEL_FONT)
        
        # Configure ttk styles
        self.setup_styles()
        
        # Variables
        self.model_var = tk.StringVar(value="large-v3")
        self.normalize_var = tk.BooleanVar(value=True)
        self.timestamps_var = tk.BooleanVar(value=True)
        self.segments_var = tk.BooleanVar(value=True)
        self.language_var = tk.StringVar(value="English")
        self.device_var = tk.StringVar(value="auto")
        self.target_dBFS_var = tk.StringVar(value="Auto")
        self.show_advanced = tk.BooleanVar(value=False)
        self.processing = False
        
        self.create_widgets()
    
    def setup_styles(self):
        """Configure ttk styles for modern appearance"""
        style = ttk.Style()
        style.theme_use("clam")
        
        # Primary button style (blue)
        style.configure(
            "Primary.TButton",
            font=BUTTON_FONT,
            foreground="white",
            background=BLUE_PRIMARY,
            padding=(20, 12),
            borderwidth=0,
            focuscolor="none"
        )
        style.map(
            "Primary.TButton",
            background=[("active", BLUE_HOVER), ("pressed", BLUE_HOVER)]
        )
        
        # Secondary button style (blue)
        style.configure(
            "Secondary.TButton",
            font=BUTTON_FONT,
            foreground="white",
            background=BLUE_PRIMARY,
            padding=(15, 10),
            borderwidth=0,
            focuscolor="none"
        )
        style.map(
            "Secondary.TButton",
            background=[("active", BLUE_HOVER), ("pressed", BLUE_HOVER)]
        )
        
        # Default button style (gray)
        style.configure(
            "Default.TButton",
            font=LABEL_FONT,
            foreground="white",
            background="#6B7280",
            padding=(15, 8),
            borderwidth=0,
            focuscolor="none"
        )
        style.map(
            "Default.TButton",
            background=[("active", "#4B5563"), ("pressed", "#4B5563")]
        )
        
        # Checkbutton style with better spacing
        style.configure(
            "TCheckbutton",
            font=LABEL_FONT,
            padding=6,
            background=BG_SECTION,
            foreground=TEXT_PRIMARY
        )
        
        # Combobox style
        style.configure(
            "TCombobox",
            font=LABEL_FONT,
            padding=5
        )
        
        # LabelFrame style
        style.configure(
            "TLabelframe",
            background=BG_SECTION,
            borderwidth=1,
            relief="flat"
        )
        style.configure(
            "TLabelframe.Label",
            font=SECTION_FONT,
            background=BG_SECTION,
            foreground=TEXT_PRIMARY
        )
        
    def create_widgets(self):
        # Main container with padding - use scrollable canvas if needed
        main_container = tk.Frame(self.root, bg=BG_MAIN, padx=24, pady=15)
        main_container.pack(fill="both", expand=True)
        
        # Title
        title_label = tk.Label(
            main_container,
            text="Mojidori",
            font=TITLE_FONT,
            fg=TEXT_PRIMARY,
            bg=BG_MAIN
        )
        title_label.pack(pady=(0, 15))
        
        # Presets section
        preset_frame = ttk.LabelFrame(
            main_container,
            text="Quick Presets",
            padding=15
        )
        preset_frame.pack(pady=(0, 15), fill="x")
        
        preset_buttons_frame = tk.Frame(preset_frame, bg=BG_SECTION)
        preset_buttons_frame.pack(fill="x")
        
        for i, (preset_name, preset_config) in enumerate(PRESETS.items()):
            if i == 1:  # Recommended preset gets primary style (blue)
                btn = ttk.Button(
                    preset_buttons_frame,
                    text=preset_name,
                    command=lambda p=preset_config: self.apply_preset(p),
                    style="Secondary.TButton"
                )
            else:
                btn = ttk.Button(
                    preset_buttons_frame,
                    text=preset_name,
                    command=lambda p=preset_config: self.apply_preset(p),
                    style="Default.TButton"
                )
            btn.pack(fill="x", pady=6)
        
        # Basic Settings section
        basic_frame = ttk.LabelFrame(
            main_container,
            text="Basic Settings",
            padding=15
        )
        basic_frame.pack(pady=(0, 15), fill="x")
        
        # Model selection
        model_row = tk.Frame(basic_frame, bg=BG_SECTION)
        model_row.pack(fill="x", pady=8)
        tk.Label(
            model_row,
            text="Model:",
            font=LABEL_FONT,
            bg=BG_SECTION,
            fg=TEXT_PRIMARY,
            width=18,
            anchor="w"
        ).pack(side="left")
        model_combo = ttk.Combobox(
            model_row,
            textvariable=self.model_var,
            values=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
            state="readonly",
            width=25
        )
        model_combo.pack(side="left", padx=8)
        
        # Language selection
        language_row = tk.Frame(basic_frame, bg=BG_SECTION)
        language_row.pack(fill="x", pady=8)
        tk.Label(
            language_row,
            text="Language:",
            font=LABEL_FONT,
            bg=BG_SECTION,
            fg=TEXT_PRIMARY,
            width=18,
            anchor="w"
        ).pack(side="left")
        language_combo = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            values=list(LANGUAGES.keys()),
            state="readonly",
            width=25
        )
        language_combo.pack(side="left", padx=8)
        
        # Checkboxes with better spacing
        checkbox_frame = tk.Frame(basic_frame, bg=BG_SECTION)
        checkbox_frame.pack(fill="x", pady=(8, 0))
        
        self.normalize_check = ttk.Checkbutton(
            checkbox_frame,
            text="Normalize Audio",
            variable=self.normalize_var
        )
        self.normalize_check.pack(anchor="w", pady=6)
        
        self.timestamps_check = ttk.Checkbutton(
            checkbox_frame,
            text="Include Timestamps",
            variable=self.timestamps_var
        )
        self.timestamps_check.pack(anchor="w", pady=6)
        
        self.segments_check = ttk.Checkbutton(
            checkbox_frame,
            text="Smart Paragraph Formatting",
            variable=self.segments_var
        )
        self.segments_check.pack(anchor="w", pady=6)
        
        # Advanced Settings (Collapsible)
        advanced_header = tk.Frame(main_container, bg=BG_MAIN)
        advanced_header.pack(fill="x", pady=(5, 0))
        
        advanced_toggle = ttk.Checkbutton(
            advanced_header,
            text="Show Advanced Settings",
            variable=self.show_advanced,
            command=self.toggle_advanced
        )
        advanced_toggle.pack(anchor="w", padx=5)
        
        self.advanced_frame = ttk.LabelFrame(
            main_container,
            text="Advanced Settings",
            padding=15
        )
        self.advanced_frame.pack_forget()  # Hidden by default
        
        # Advanced settings content
        # Device selection
        device_row = tk.Frame(self.advanced_frame, bg=BG_SECTION)
        device_row.pack(fill="x", pady=8)
        tk.Label(
            device_row,
            text="Device:",
            font=LABEL_FONT,
            bg=BG_SECTION,
            fg=TEXT_PRIMARY,
            width=18,
            anchor="w"
        ).pack(side="left")
        device_combo = ttk.Combobox(
            device_row,
            textvariable=self.device_var,
            values=["auto", "cpu", "cuda"],
            state="readonly",
            width=25
        )
        device_combo.pack(side="left", padx=8)
        tk.Label(
            device_row,
            text="(auto = detect GPU automatically)",
            font=SMALL_FONT,
            bg=BG_SECTION,
            fg=TEXT_MUTED
        ).pack(side="left", padx=8)
        
        # Target dBFS
        dbfs_row = tk.Frame(self.advanced_frame, bg=BG_SECTION)
        dbfs_row.pack(fill="x", pady=8)
        tk.Label(
            dbfs_row,
            text="Target Loudness:",
            font=LABEL_FONT,
            bg=BG_SECTION,
            fg=TEXT_PRIMARY,
            width=18,
            anchor="w"
        ).pack(side="left")
        dbfs_combo = ttk.Combobox(
            dbfs_row,
            textvariable=self.target_dBFS_var,
            values=["Auto", "-16.0", "-18.0", "-20.0", "-22.0", "-24.0"],
            state="readonly",
            width=25
        )
        dbfs_combo.pack(side="left", padx=8)
        tk.Label(
            dbfs_row,
            text="(dBFS, lower = quieter)",
            font=SMALL_FONT,
            bg=BG_SECTION,
            fg=TEXT_MUTED
        ).pack(side="left", padx=8)
        
        # Status/Info
        self.info_frame = tk.Frame(main_container, bg=BG_MAIN)
        self.info_frame.pack(pady=(15, 10), fill="x")
        self.status_label = tk.Label(
            self.info_frame,
            text="Ready to process files from 'queue' folder",
            font=LABEL_FONT,
            fg=TEXT_MUTED,
            bg=BG_MAIN,
            wraplength=560,
            justify="center"
        )
        self.status_label.pack()
        
        # Go button - use tk.Button for reliable color display on Windows
        button_frame = tk.Frame(main_container, bg=BG_MAIN)
        button_frame.pack(pady=(8, 15), fill="x")
        self.go_button = tk.Button(
            button_frame,
            text="▶ START TRANSCRIPTION",
            command=self.start_processing,
            font=BUTTON_FONT,
            bg=BLUE_PRIMARY,
            fg="white",
            activebackground=BLUE_HOVER,
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            padx=30,
            pady=12,
            cursor="hand2"
        )
        self.go_button.pack(fill="x", padx=10)
        # Bind hover effects
        self.go_button.bind("<Enter>", lambda e: self.go_button.config(bg=BLUE_HOVER))
        self.go_button.bind("<Leave>", lambda e: self.go_button.config(bg=BLUE_PRIMARY))
        
    def toggle_advanced(self):
        """Show/hide advanced settings"""
        if self.show_advanced.get():
            self.advanced_frame.pack(pady=(8, 15), fill="x", before=self.info_frame)
        else:
            self.advanced_frame.pack_forget()
    
    def apply_preset(self, preset):
        """Apply preset configuration"""
        self.model_var.set(preset["model"])
        self.normalize_var.set(preset["normalize_audio"])
        self.timestamps_var.set(preset["timestamps"])
        self.segments_var.set(preset["segments"])
        if "language" in preset:
            # Find language key from value
            lang_value = preset["language"]
            for key, value in LANGUAGES.items():
                if value == lang_value:
                    self.language_var.set(key)
                    break
        if "device" in preset:
            self.device_var.set(preset["device"])
        self.status_label.config(
            text="✓ Preset applied! Click START TRANSCRIPTION to begin.",
            fg=BLUE_PRIMARY
        )
        
    def start_processing(self):
        """Start the transcription process"""
        if self.processing:
            messagebox.showwarning("Already Processing", "Transcription is already in progress!")
            return
        
        # Check if queue folder exists
        script_dir = Path(__file__).parent.resolve()
        queue_folder = script_dir / "queue"
        
        if not queue_folder.exists():
            response = messagebox.askyesno(
                "Queue Folder Not Found",
                "The 'queue' folder doesn't exist yet.\n\n"
                "It will be created on first run.\n\n"
                "Continue anyway?"
            )
            if not response:
                return
        
        # Build command
        cmd = [sys.executable, "transcribe_lecture.py", "--non-interactive"]
        
        # Add model
        cmd.extend(["-m", self.model_var.get()])
        
        # Add language
        lang_code = LANGUAGES.get(self.language_var.get())
        if lang_code:
            cmd.extend(["-l", lang_code])
        
        # Add device
        device = self.device_var.get()
        if device != "auto":
            cmd.extend(["--device", device])
        
        # Add normalize audio
        if self.normalize_var.get():
            cmd.append("--normalize-audio")
            # Add target dBFS if specified
            dbfs = self.target_dBFS_var.get()
            if dbfs != "Auto":
                try:
                    cmd.extend(["--target-dBFS", str(float(dbfs))])
                except:
                    pass
        
        # Add timestamps
        if not self.timestamps_var.get():
            cmd.append("--no-timestamps")
        
        # Add segments
        if not self.segments_var.get():
            cmd.append("--no-segments")
        
        # Disable button and show status
        self.processing = True
        self.go_button.config(state="disabled", text="Processing...")
        self.status_label.config(
            text="Processing started! Check the console window for progress.",
            fg=BLUE_PRIMARY
        )
        
        # Run in separate thread to keep GUI responsive
        thread = threading.Thread(target=self.run_transcription, args=(cmd,), daemon=True)
        thread.start()
        
    def run_transcription(self, cmd):
        """Run transcription in background"""
        try:
            # Run the transcription script with visible console window
            process = subprocess.Popen(
                cmd,
                cwd=Path(__file__).parent.resolve()
            )
            
            process.wait()
            
            # Re-enable button
            self.root.after(0, self.processing_complete, process.returncode == 0)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to start transcription:\n{e}"))
            self.root.after(0, self.processing_complete, False)
    
    def processing_complete(self, success):
        """Called when processing is complete"""
        self.processing = False
        self.go_button.config(state="normal", text="▶ START TRANSCRIPTION")
        
        if success:
            self.status_label.config(
                text="✓ Processing complete! Check the 'processed' folder for results.",
                fg=BLUE_PRIMARY
            )
            messagebox.showinfo(
                "Complete",
                "Transcription completed successfully!\n\n"
                "Check the 'processed' folder for your transcripts."
            )
        else:
            self.status_label.config(
                text="✗ Processing failed. Check console for details.",
                fg="#DC2626"
            )
            messagebox.showerror(
                "Error",
                "Transcription failed. Please check the console window for error details."
            )


def main():
    root = tk.Tk()
    app = TranscriptionGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
