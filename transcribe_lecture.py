#!/usr/bin/env python3
"""
High-Definition Lecture Transcription Script using OpenAI Whisper
Generates a well-formatted text file optimized for AI summarization

Workflow:
- Drop lecture files into "queue" folder (files should be named like "C188 Lecture 1.m4a")
- Run script to process all files automatically
- Each lecture gets processed and archived to "archived recordings.zip"
- Archives are organized by class code (e.g., C188, CS101) within the zip file
- Original files and transcripts are packed together in the archive
"""

import os
import sys

# Must be set BEFORE torch/whisper is imported — fixes OpenMP duplicate library
# conflict on Windows (libiomp5md.dll loaded twice by PyTorch + Intel MKL)
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

# Set UTF-8 encoding for Windows console output (fixes Whisper verbose Unicode errors)
os.environ['PYTHONIOENCODING'] = 'utf-8'

import whisper
import argparse
import shutil
import tempfile
import zipfile
import re
from pathlib import Path
from datetime import datetime
import json
from typing import List, Tuple, Optional
if sys.platform == 'win32':
    try:
        # Reconfigure stdout/stderr to use UTF-8
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass  # Python < 3.7 or other issue


def check_cuda_available() -> bool:
    """
    Check if CUDA (GPU) is available on the system
    
    Returns:
        True if CUDA is available, False otherwise
        Returns False if torch is not installed or CUDA is not available
    """
    try:
        import torch
        return torch.cuda.is_available()
    except (ImportError, AttributeError, RuntimeError):
        # torch not installed, CUDA not available, or other error
        return False


def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_transcript_for_ai(result, include_timestamps=True, include_speaker_segments=True):
    """
    Format the transcription result for optimal AI readability
    
    Args:
        result: Whisper transcription result
        include_timestamps: Whether to include timestamps in the output
        include_speaker_segments: Whether to break into logical segments
    """
    lines = []
    
    # Add header information
    lines.append("=" * 80)
    lines.append("LECTURE TRANSCRIPTION")
    lines.append("=" * 80)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Language: {result.get('language', 'Unknown')}")
    lines.append("=" * 80)
    lines.append("")
    
    # Get the full text
    full_text = result["text"].strip()
    
    if include_speaker_segments and "segments" in result:
        # Format with segments for better readability
        lines.append("[TRANSCRIPT]")
        lines.append("")
        
        current_paragraph = []
        last_end_time = 0
        
        for i, segment in enumerate(result["segments"]):
            start_time = segment["start"]
            end_time = segment["end"]
            text = segment["text"].strip()
            
            # Detect natural breaks (pauses > 2 seconds or sentence endings)
            time_gap = start_time - last_end_time if i > 0 else 0
            is_sentence_end = text.endswith(('.', '!', '?', ':', ';'))
            
            # Start new paragraph on significant pauses or sentence endings
            if time_gap > 2.0 or (is_sentence_end and time_gap > 1.0):
                if current_paragraph:
                    paragraph_text = " ".join(current_paragraph)
                    if include_timestamps:
                        timestamp = format_timestamp(start_time - time_gap)
                        lines.append(f"[{timestamp}] {paragraph_text}")
                    else:
                        lines.append(paragraph_text)
                    lines.append("")  # Empty line for paragraph break
                    current_paragraph = []
            
            current_paragraph.append(text)
            last_end_time = end_time
        
        # Add remaining paragraph
        if current_paragraph:
            paragraph_text = " ".join(current_paragraph)
            if include_timestamps:
                timestamp = format_timestamp(result["segments"][-1]["start"])
                lines.append(f"[{timestamp}] {paragraph_text}")
            else:
                lines.append(paragraph_text)
    else:
        # Simple format - just the text with minimal formatting
        lines.append("[TRANSCRIPT]")
        lines.append("")
        
        # Break into paragraphs based on sentence endings
        sentences = full_text.split('. ')
        paragraph = []
        
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Add period if it was removed by split
            if i < len(sentences) - 1 and not sentence.endswith(('.', '!', '?')):
                sentence += '.'
            
            paragraph.append(sentence)
            
            # Create paragraph breaks every 3-4 sentences or on question/exclamation
            if len(paragraph) >= 3 or sentence.endswith(('!', '?')):
                lines.append(" ".join(paragraph))
                lines.append("")  # Empty line for paragraph break
                paragraph = []
        
        # Add remaining sentences
        if paragraph:
            lines.append(" ".join(paragraph))
    
    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF TRANSCRIPT")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def copy_prompt_files_to_workspace(base_path: Path):
    """
    Copy prompt files from script directory to workspace directory
    
    Args:
        base_path: Base directory where prompt files should be copied
    """
    script_dir = Path(__file__).parent.resolve()
    prompt_files = [
        "prompt_descriptive_summary.md",
        "prompt_condensed_notes.md",
        "prompt_cheat_sheet.md"
    ]
    
    for prompt_file in prompt_files:
        source = script_dir / prompt_file
        destination = base_path / prompt_file
        
        # Only copy if source exists and destination doesn't exist (don't overwrite)
        if source.exists() and not destination.exists():
            try:
                shutil.copy2(source, destination)
            except Exception as e:
                # Silently fail if copy doesn't work
                pass


def extract_class_code(filename: str) -> str:
    """
    Extract class code from filename (e.g., "C188 Lecture 1.m4a" -> "C188")
    
    Args:
        filename: The filename to extract class code from
    
    Returns:
        Class code if found (e.g., "C188"), or "Unknown" if no pattern matches
    """
    # Pattern to match class codes like C188, CS101, MATH123, etc.
    # Matches: letter(s) followed by digits, at the start of filename
    match = re.match(r'^([A-Z]+[0-9]+)', filename.upper())
    if match:
        return match.group(1)
    return "Unknown"


def archive_lecture_to_zip(original_file: Path, archive_zip_path: Path, class_code: str) -> bool:
    """
    Archive only the original lecture file to a zip file, organized by class code
    
    Args:
        original_file: Path to the original lecture file to archive
        archive_zip_path: Path to the zip file (will be created if doesn't exist)
        class_code: Class code to organize by (e.g., "C188")
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create zip file in append mode if it exists, otherwise create new
        mode = 'a' if archive_zip_path.exists() else 'w'
        
        with zipfile.ZipFile(archive_zip_path, mode, zipfile.ZIP_DEFLATED) as zipf:
            # Archive only the original file
            # Organize by class code: ClassCode/filename
            arcname = f"{class_code}/{original_file.name}"
            zipf.write(original_file, arcname)
        
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to archive to zip: {e}")
        return False


def get_workflow_folders(base_path: Path = None, prompt_user: bool = True) -> Tuple[Path, Path]:
    """
    Get or create the workflow folders
    
    Args:
        base_path: Base directory for folders
        prompt_user: Whether to prompt user before creating folders (only used if folders don't exist)
    
    Returns:
        Tuple of (queue_folder, processed_folder) where processed_folder contains subfolders for each lecture
    """
    if base_path is None:
        base_path = Path.cwd()
    
    queue = base_path / "queue"
    processed = base_path / "processed"
    
    # If folders already exist, just return them (no prompts needed)
    if queue.exists() and processed.exists():
        return queue, processed
    
    # Only prompt if folders need to be created
    folders_to_create = []
    if not queue.exists():
        folders_to_create.append(str(queue))
    if not processed.exists():
        folders_to_create.append(str(processed))
    
    # Prompt user if folders need to be created
    if folders_to_create and prompt_user:
        print("\nThe following folders will be created:")
        for folder in folders_to_create:
            print(f"  - {folder}")
        if not queue.exists():
            print(f"\n  Please drop and rename your lecture files into the 'queue' folder.")
            print(f"  Files should be named like: 'C188 Lecture 1.m4a' (class code + lecture name)")
        
        while True:
            try:
                response = input("\nCreate these folders? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nFolder creation cancelled. Exiting.")
                return None, None
            
            if response in ['y', 'yes']:
                break
            elif response in ['n', 'no']:
                print("Folder creation cancelled. Exiting.")
                return None, None
            else:
                print("Please enter 'y' or 'n'")
    
    # Check if this is first run (folders don't exist yet)
    is_first_run = not queue.exists()
    
    # Create folders if they don't exist
    queue.mkdir(exist_ok=True)
    processed.mkdir(exist_ok=True)
    
    # On first run, check if there are any lecture files in the base directory
    # and move them to the queue folder
    if is_first_run:
        # Check for audio/video files in base directory
        audio_video_extensions = {
            '.mp3', '.mp4', '.wav', '.m4a', '.flac', '.ogg', '.webm',
            '.avi', '.mov', '.mkv', '.wmv', '.aac', '.wma', '.mpeg', '.mpg'
        }
        
        files_moved = []
        # Get list of files to skip (script file, Python files, etc.)
        files_to_skip = {'transcribe_lecture.py', '__pycache__', '.py'}
        
        for file_path in base_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in audio_video_extensions:
                # Skip Python files and the script itself
                if file_path.suffix.lower() == '.py' or file_path.name in files_to_skip:
                    continue
                # Move file to queue folder
                destination = queue / file_path.name
                # Handle duplicate names
                counter = 1
                while destination.exists():
                    stem = file_path.stem
                    suffix = file_path.suffix
                    destination = queue / f"{stem}_{counter}{suffix}"
                    counter += 1
                try:
                    shutil.move(str(file_path), str(destination))
                    files_moved.append(file_path.name)
                except Exception as e:
                    # If move fails, continue with other files
                    pass
        
        if files_moved:
            print(f"\n  [ORGANIZED] Moved {len(files_moved)} lecture file(s) from script directory to queue folder:")
            for filename in files_moved:
                print(f"    - {filename}")
    
    return queue, processed


def analyze_audio_levels(audio) -> dict:
    """
    Analyze audio to determine current levels and quality.
    
    Returns:
        Dictionary with analysis results: rms_dBFS, peak_dBFS, max_possible_amplitude, dynamic_range
    """
    # Get RMS (average loudness) - better indicator than peak
    rms_dBFS = audio.dBFS
    
    # Get peak level
    peak_dBFS = audio.max_possible_amplitude
    peak_amplitude = audio.max
    
    # Calculate dynamic range (difference between peak and RMS)
    dynamic_range = peak_dBFS - rms_dBFS
    
    # Determine if audio is clipped or too quiet
    is_quiet = rms_dBFS < -30.0
    is_very_quiet = rms_dBFS < -40.0
    is_loud = rms_dBFS > -12.0
    is_clipped = peak_amplitude >= audio.max_possible_amplitude * 0.95
    
    return {
        'rms_dBFS': rms_dBFS,
        'peak_dBFS': peak_dBFS,
        'peak_amplitude': peak_amplitude,
        'max_possible': audio.max_possible_amplitude,
        'dynamic_range': dynamic_range,
        'is_quiet': is_quiet,
        'is_very_quiet': is_very_quiet,
        'is_loud': is_loud,
        'is_clipped': is_clipped
    }


def recommend_target_level(analysis: dict) -> Tuple[float, float, str]:
    """
    Recommend optimal target level based on audio analysis.
    
    Returns:
        Tuple of (recommended_target_dBFS, recommended_gain, recommendation_reason)
    """
    rms = analysis['rms_dBFS']
    is_quiet = analysis['is_quiet']
    is_very_quiet = analysis['is_very_quiet']
    is_loud = analysis['is_loud']
    is_clipped = analysis['is_clipped']
    
    # Optimal target for speech transcription (balance between clarity and avoiding distortion)
    optimal_target = -20.0  # Good for Whisper
    
    # Adjust target based on current level
    if is_very_quiet:
        # Very quiet recordings - be more aggressive but safe
        target = -16.0
        reason = "Very quiet recording detected - targeting louder level for better transcription"
    elif is_quiet:
        # Quiet but acceptable - normalize to good level
        target = -18.0
        reason = "Quiet recording - normalizing to optimal speech level"
    elif is_loud:
        # Already loud - might need reduction
        if rms > -6.0:
            target = -12.0  # Reduce but keep it loud
            reason = "Very loud recording - reducing to prevent distortion"
        else:
            target = -16.0
            reason = "Loud recording - normalizing to optimal level"
    else:
        # Normal range - use standard target
        target = optimal_target
        reason = "Normal recording level - standard normalization"
    
    # Calculate recommended gain
    recommended_gain = target - rms
    
    # Safety limits
    max_safe_gain = 25.0  # Maximum safe gain
    if recommended_gain > max_safe_gain:
        recommended_gain = max_safe_gain
        target = rms + max_safe_gain
        reason += f" (gain limited to {max_safe_gain}dB for safety)"
    elif recommended_gain < -max_safe_gain:
        recommended_gain = -max_safe_gain
        target = rms - max_safe_gain
        reason += f" (reduction limited to {max_safe_gain}dB)"
    
    return target, recommended_gain, reason


def apply_limiter(audio, threshold_dBFS: float = -3.0, ratio: float = 20.0, attack: float = 5.0, release: float = 50.0):
    """
    Apply a soft limiter to prevent clipping.
    This uses normalization with headroom as a simple limiter.
    """
    import math
    
    # First, normalize to prevent any clipping
    # Use headroom to avoid hard clipping
    headroom_dB = -1.0  # 1dB headroom
    
    # Normalize to peak at threshold + headroom
    target_peak = threshold_dBFS + headroom_dB
    
    # Calculate current peak in dBFS
    max_amplitude = audio.max
    max_possible = audio.max_possible_amplitude
    
    if max_amplitude > 0 and max_possible > 0:
        # Convert amplitude ratio to dBFS
        ratio_linear = max_amplitude / max_possible
        current_peak_dBFS = 20 * math.log10(ratio_linear) if ratio_linear > 0 else -60.0
    else:
        current_peak_dBFS = -60.0
    
    # If audio is above threshold, apply limiting
    if current_peak_dBFS > threshold_dBFS:
        # Reduce to threshold
        reduction_needed = current_peak_dBFS - target_peak
        audio = audio.apply_gain(-reduction_needed)
    
    return audio


def normalize_audio_gain(
    input_file: Path,
    output_folder: Path,
    base_name: str = None,  # Base name for output files (uses input_file.stem if None)
    target_dBFS: float = None,  # None means auto-detect
    max_gain: float = 30.0,
    auto_recommend: bool = True
) -> Optional[Tuple[Path, dict]]:
    """
    Automatically detect audio levels and normalize with limiter.
    
    Args:
        input_file: Path to input audio/video file
        target_dBFS: Target loudness in dBFS (None for auto-recommendation)
        max_gain: Maximum gain to apply in dB (safety limit)
        auto_recommend: If True, automatically detect and recommend optimal settings
    
    Returns:
        Tuple of (Path to processed file, analysis dict) or None if processing fails
    """
    try:
        from pydub import AudioSegment
        
        print(f"  [AUDIO ANALYSIS] Loading and analyzing audio file...")
        
        # Load audio (pydub handles video files by extracting audio)
        audio = AudioSegment.from_file(str(input_file))
        
        # Analyze current audio levels
        analysis = analyze_audio_levels(audio)
        
        print(f"  [AUDIO ANALYSIS] Current audio levels:")
        print(f"    RMS (average loudness): {analysis['rms_dBFS']:.2f} dBFS")
        print(f"    Peak level: {analysis['peak_dBFS']:.2f} dBFS")
        print(f"    Dynamic range: {analysis['dynamic_range']:.2f} dB")
        
        if analysis['is_clipped']:
            print(f"    [WARNING] Audio may be clipped/distorted")
        if analysis['is_very_quiet']:
            print(f"    [INFO] Very quiet recording detected")
        
        # Auto-recommend target if requested
        if auto_recommend and target_dBFS is None:
            recommended_target, recommended_gain, reason = recommend_target_level(analysis)
            target_dBFS = recommended_target
            
            print(f"\n  [RECOMMENDATION] Audio analysis complete:")
            print(f"    Recommended target: {target_dBFS:.2f} dBFS")
            print(f"    Recommended gain: {recommended_gain:+.2f} dB")
            print(f"    Reason: {reason}")
        else:
            # Use provided target or calculate from it
            recommended_gain = target_dBFS - analysis['rms_dBFS'] if target_dBFS else 0
            print(f"\n  [NORMALIZATION] Using target: {target_dBFS:.2f} dBFS")
            print(f"    Required gain: {recommended_gain:+.2f} dB")
        
        # Limit gain to prevent excessive amplification
        if abs(recommended_gain) > max_gain:
            original_gain = recommended_gain
            recommended_gain = max_gain if recommended_gain > 0 else -max_gain
            target_dBFS = analysis['rms_dBFS'] + recommended_gain
            print(f"    [SAFETY] Gain limited from {original_gain:+.2f} dB to {recommended_gain:+.2f} dB")
        
        # Apply gain if needed (only if difference is significant, > 0.5 dB)
        if abs(recommended_gain) > 0.5:
            print(f"\n  [PROCESSING] Applying audio enhancement:")
            print(f"    Applying {recommended_gain:+.2f} dB gain...")
            audio = audio.apply_gain(recommended_gain)
            
            # Apply limiter to prevent clipping
            print(f"    Applying limiter (threshold: -3.0 dBFS) to prevent distortion...")
            audio = apply_limiter(audio, threshold_dBFS=-3.0)
            
            # Verify final levels
            final_analysis = analyze_audio_levels(audio)
            print(f"\n  [RESULTS] Processing complete:")
            print(f"    Final RMS: {final_analysis['rms_dBFS']:.2f} dBFS")
            print(f"    Final peak: {final_analysis['peak_dBFS']:.2f} dBFS")
            print(f"    Status: {'Ready' if not final_analysis['is_clipped'] else 'Warning: Possible clipping'}")
            
            # Save processed audio to output folder - use base name if provided
            base = base_name if base_name else input_file.stem
            output_filename = f"{base}_enhanced.wav"
            output_file = output_folder / output_filename
            
            # Handle duplicate names
            counter = 1
            while output_file.exists():
                output_file = output_folder / f"{base}_enhanced_{counter}.wav"
                counter += 1
            
            # Export as WAV (uncompressed, best quality for Whisper)
            print(f"    Saving enhanced audio to: {output_file.name}")
            audio.export(str(output_file), format="wav")
            
            return output_file, analysis
        else:
            print(f"\n  [INFO] Audio level is already optimal ({analysis['rms_dBFS']:.2f} dBFS)")
            print(f"    Gain adjustment ({recommended_gain:+.2f} dB) is minimal - skipping normalization")
            return None, analysis
            
    except ImportError:
        print(f"  [ERROR] pydub not installed. Skipping audio normalization.")
        print(f"  Install with: pip install pydub")
        return None, None
    except Exception as e:
        print(f"  [ERROR] Audio normalization failed: {e}")
        import traceback
        traceback.print_exc()
        print(f"  Continuing with original file...")
        return None, None


def get_audio_video_files(folder: Path) -> List[Path]:
    """
    Get all audio/video files from a folder, sorted by name
    
    Supported formats: mp3, mp4, wav, m4a, flac, ogg, webm, avi, mov, mkv, wmv
    """
    audio_video_extensions = {
        '.mp3', '.mp4', '.wav', '.m4a', '.flac', '.ogg', '.webm',
        '.avi', '.mov', '.mkv', '.wmv', '.aac', '.wma', '.mpeg', '.mpg'
    }
    
    files = []
    for file_path in folder.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in audio_video_extensions:
            files.append(file_path)
    
    # Sort by filename for consistent processing order
    files.sort(key=lambda x: x.name.lower())
    return files


def transcribe_lecture(
    input_file: Path,
    output_file: Path,
    model,
    processed_folder: Path,
    language=None,
    include_timestamps=True,
    include_speaker_segments=True,
    normalize_audio=False,
    target_dBFS=-20.0,
    max_gain=30.0,
    verbose=True,
    device="cpu"
):
    """
    Transcribe a lecture audio/video file using OpenAI Whisper
    
    Args:
        input_file: Path to audio/video file
        output_file: Path to output text file
        model: Loaded Whisper model (to avoid reloading)
        processed_folder: Folder where enhanced audio and transcripts are saved
        language: Language code (e.g., 'en', 'es') or None for auto-detection
        include_timestamps: Whether to include timestamps in output
        include_speaker_segments: Whether to use segment-based formatting
        normalize_audio: Whether to normalize audio gain before transcription
        target_dBFS: Target loudness in dBFS for normalization (default: -20.0)
        max_gain: Maximum gain to apply in dB (prevents distortion)
        verbose: Whether to show Whisper's detailed progress output (default: True)
    """
    # Normalize audio if requested
    processed_file = input_file
    temp_file = None
    
    enhanced_file = None
    # Use consistent base name for all output files
    base_name = input_file.stem
    
    if normalize_audio:
        print(f"  [AUDIO PREPROCESSING] Starting automatic audio analysis and enhancement...")
        result = normalize_audio_gain(
            input_file,
            processed_folder,
            base_name=base_name,  # Pass base name for consistent naming
            target_dBFS=target_dBFS if target_dBFS != -20.0 else None,  # Use None for auto if default
            max_gain=max_gain,
            auto_recommend=True
        )
        if result and result[0]:
            enhanced_file, audio_analysis = result
            processed_file = enhanced_file
            print(f"  [OK] Audio preprocessing complete - enhanced audio saved to 'processed' folder")
        elif result and result[1]:
            # Analysis was done but no processing needed
            audio_analysis = result[1]
            print(f"  [OK] Audio analysis complete - no processing needed (audio already optimal)")
    
    print(f"  [TRANSCRIBING] Starting transcription...")
    print(f"  [INFO] This may take several minutes depending on file length...")
    print(f"  [INFO] Whisper will show detailed progress below:\n")
    
    # Transcribe with detailed options
    # Note: Setting language explicitly and using English-specific prompt helps prevent hallucinations
    result = model.transcribe(
        str(processed_file),
        language=language,
        verbose=verbose,
        task="transcribe",
        fp16=(device == "cuda"),  # fp16 on GPU for speed, fp32 on CPU for stability
        condition_on_previous_text=False,  # Disable to prevent hallucination propagation
        no_speech_threshold=0.6,  # Higher threshold to better detect silence (default 0.6)
        logprob_threshold=-1.0,  # Filter low confidence segments
        compression_ratio_threshold=2.4,  # Filter repetitive/hallucinated segments
        initial_prompt="This is an English language lecture. Transcribe only English speech with proper punctuation."
    )
    
    print(f"\n  [FORMATTING] Processing transcript for optimal AI readability...")
    formatted_text = format_transcript_for_ai(
        result,
        include_timestamps=include_timestamps,
        include_speaker_segments=include_speaker_segments
    )
    
    # Write transcript to file
    print(f"  [SAVING] Writing transcript files...")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(formatted_text)
    print(f"    - Main transcript: {output_file.name}")
    
    # Also save raw JSON for reference - use same base name as input file
    json_output = output_file.parent / f"{base_name}_transcript_raw.json"
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"    - Raw data: {json_output.name}")
    
    duration_min = result.get('duration', 0) / 60
    detected_lang = result.get('language', 'Unknown')
    
    print(f"\n  [STATISTICS]")
    print(f"    Detected language: {detected_lang}")
    print(f"    Audio duration: {duration_min:.1f} minutes")
    print(f"    Transcript length: {len(formatted_text)} characters")
    
    return result, formatted_text


def prompt_user_choice(prompt: str, choices: List[str], default: int = 0) -> str:
    """Display choices and prompt user to select one"""
    print(f"\n{prompt}")
    for i, choice in enumerate(choices, 1):
        marker = " [default]" if i == default + 1 else ""
        print(f"  {i}. {choice}{marker}")
    
    while True:
        try:
            response = input(f"\nEnter your choice (1-{len(choices)}) [default: {default + 1}]: ").strip()
            if not response:
                return choices[default]
            
            choice_idx = int(response) - 1
            if 0 <= choice_idx < len(choices):
                return choices[choice_idx]
            else:
                print(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print("Please enter a valid number")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled by user.")
            return None


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt user for yes/no answer"""
    default_str = "Y/n" if default else "y/N"
    
    while True:
        try:
            response = input(f"{prompt} [{default_str}]: ").strip().lower()
            if not response:
                return default
            
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' or 'n'")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled by user.")
            return None


def prompt_text(prompt: str, default: str = None, required: bool = False) -> str:
    """Prompt user for text input"""
    default_str = f" [default: {default}]" if default else ""
    
    while True:
        try:
            response = input(f"{prompt}{default_str}: ").strip()
            
            if not response:
                if default:
                    return default
                elif required:
                    print("This field is required. Please enter a value.")
                    continue
                else:
                    return None
            return response
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled by user.")
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe lectures using OpenAI Whisper with AI-optimized formatting. "
                    "Processes all files from 'queue' folder automatically.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Drop lecture files into "queue" folder (named like "C188 Lecture 1.m4a")
  2. Run this script
  3. Files are transcribed and archived to "archived recordings.zip"
  4. Archives are organized by class code within the zip file
  5. Original files and transcripts are packed together in the archive
        """
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="Whisper model size (optional override, otherwise prompted)"
    )
    parser.add_argument(
        "-l", "--language",
        type=str,
        default="en",
        help="Language code (default: 'en' for English, override if needed)"
    )
    parser.add_argument(
        "--no-timestamps",
        action="store_true",
        help="Omit timestamps from output (optional override)"
    )
    parser.add_argument(
        "--no-segments",
        action="store_true",
        help="Use simple paragraph formatting (optional override)"
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        choices=["cpu", "cuda"],
        help="Device to use (optional override)"
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=None,
        help="Base path for workflow folders (default: script's directory)"
    )
    parser.add_argument(
        "--normalize-audio",
        action="store_true",
        help="Normalize audio gain (optional override)"
    )
    parser.add_argument(
        "--target-dBFS",
        type=float,
        default=None,
        help="Target audio loudness in dBFS (optional override)"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults without prompts (for automation)"
    )
    
    args = parser.parse_args()
    
    # Interactive setup if not in non-interactive mode
    if not args.non_interactive:
        print("="*80)
        print("LECTURE TRANSCRIPTION SYSTEM")
        print("="*80)
        print("Welcome! This program will help you transcribe your lectures.")
        print("Let's configure the settings for optimal transcription quality.\n")
    
    try:
        # Get or create workflow folders
        # Default to script's directory, or use provided base_path
        if args.base_path:
            base_path = Path(args.base_path)
        else:
            # Use the directory where this script is located
            base_path = Path(__file__).parent.resolve()
        
        print(f"\n[STEP 1/6] Setting up workspace folders...")
        print(f"  Working directory: {base_path}")
        
        queue_folder, processed_folder = get_workflow_folders(
            base_path, 
            prompt_user=not args.non_interactive
        )
        
        # Check if user cancelled folder creation
        if queue_folder is None:
            print("\n[ABORTED] Folder creation was cancelled.")
            return 1
        
        archived_zip_path = base_path / "archived recordings.zip"
        
        print(f"  [OK] Folders ready:")
        print(f"    - Queue: {queue_folder.name}")
        print(f"    - Processed: {processed_folder.name} (each lecture gets its own subfolder)")
        print(f"    - Archived Recordings: {archived_zip_path.name} (zip file, organized by class code)")
        
        # Get all files to process
        print(f"\n[STEP 2/6] Scanning for lecture files...")
        files_to_process = get_audio_video_files(queue_folder)
        
        if not files_to_process:
            print(f"\n[INFO] No audio/video files found in '{queue_folder.name}' folder.")
            print(f"  Please drop your lecture files there and run the script again!")
            return 0
        
        print(f"  [OK] Found {len(files_to_process)} file(s) ready for transcription:")
        total_size = 0
        for i, file in enumerate(files_to_process, 1):
            file_size = file.stat().st_size / (1024 * 1024)  # MB
            total_size += file_size
            print(f"    {i}. {file.name} ({file_size:.1f} MB)")
        print(f"  Total size: {total_size:.1f} MB")
        
        # Interactive configuration (unless overridden or non-interactive)
        if not args.non_interactive:
            print(f"\n[STEP 3/6] Configuration Settings")
            print("  Let's configure the transcription options:")
            
            # Model selection
            if args.model is None:
                model_choices = [
                    "large-v3 (Best quality, slower) - Recommended",
                    "large-v2 (Excellent quality)",
                    "medium (Good quality, faster)",
                    "small (Fair quality, much faster)",
                    "base (Basic quality, very fast)",
                    "tiny (Lowest quality, fastest)"
                ]
                model_map = ["large-v3", "large-v2", "medium", "small", "base", "tiny"]
                model_choice = prompt_user_choice(
                    "Which transcription quality would you like?",
                    model_choices,
                    default=0
                )
                if model_choice is None:
                    return 1
                model_size = model_map[model_choices.index(model_choice)]
            else:
                model_size = args.model
            
            # Language - always English, no prompt needed
            language = args.language if args.language else "en"
            
            # Audio normalization
            if args.normalize_audio is False:
                normalize = prompt_yes_no(
                    "Enable automatic audio enhancement? (Automatically detects and optimizes audio levels with limiter)",
                    default=True
                )
                if normalize is None:
                    return 1
            else:
                normalize = args.normalize_audio
            
            # Target dBFS if normalization enabled - now auto-recommended, but allow override
            target_dBFS = None  # None means auto-detect and recommend
            if normalize and args.target_dBFS is not None:
                # User provided explicit target via command line
                target_dBFS = args.target_dBFS
            elif normalize:
                # Auto-mode - will detect and recommend
                print("\n  [INFO] Audio enhancement will automatically:")
                print("    - Analyze current audio levels (RMS, peak, dynamic range)")
                print("    - Recommend optimal gain adjustment")
                print("    - Apply limiter to prevent distortion")
                print("    - Optimize for best transcription quality")
            
            # Timestamps - default to False (no timestamps), user can enable if needed
            include_timestamps = False  # Default to no timestamps
            if args.non_interactive == False:
                include_timestamps = prompt_yes_no(
                    "Include timestamps in transcript?",
                    default=False
                )
                if include_timestamps is None:
                    return 1
            elif args.no_timestamps:
                # If --no-timestamps flag is explicitly set, keep it False
                include_timestamps = False
            
            # Segments
            include_segments = not args.no_segments
            if not args.no_segments and args.non_interactive == False:
                include_segments = prompt_yes_no(
                    "Use smart paragraph formatting? (Better for AI reading)",
                    default=True
                )
                if include_segments is None:
                    return 1
            
            print(f"\n  [CONFIGURATION SUMMARY]")
            print(f"    Model: {model_size}")
            print(f"    Language: English")
            print(f"    Audio enhancement: {'Yes (auto-detect & optimize)' if normalize else 'No'}")
            if normalize and target_dBFS:
                print(f"    Target loudness: {target_dBFS} dBFS (manual)")
            elif normalize:
                print(f"    Target loudness: Auto-recommended based on analysis")
            print(f"    Timestamps: {'Yes' if include_timestamps else 'No'}")
            print(f"    Smart formatting: {'Yes' if include_segments else 'No'}")
            
            confirm = prompt_yes_no("\n  Proceed with these settings?", default=True)
            if not confirm:
                print("\n[CANCELLED] Transcription cancelled by user.")
                return 1
        else:
            # Non-interactive mode - use defaults or args
            model_size = args.model or "large-v3"
            language = args.language if args.language else "en"  # Default to English
            normalize = args.normalize_audio if args.normalize_audio else True  # Default to True
            target_dBFS = args.target_dBFS  # None means auto-detect
            include_timestamps = False  # Default to no timestamps
            include_segments = not args.no_segments
        
        # Load model
        print(f"\n[STEP 4/6] Loading transcription model...")
        print(f"  Model: {model_size}")
        print(f"  [INFO] This may take a moment on first run (downloading model)...")
        print(f"  [INFO] Subsequent runs will be faster (model cached)")
        
        # Determine device - check CUDA availability if not explicitly set
        device = args.device
        if device is None:
            # Auto-detect: use CUDA if available, otherwise CPU
            if check_cuda_available():
                device = "cuda"
                print(f"  [INFO] NVIDIA GPU (CUDA) detected - using GPU for faster processing")
            else:
                device = "cpu"
                print(f"  [INFO] No GPU detected - using CPU")
        
        model = whisper.load_model(model_size, device=device)
        device_used = "GPU (CUDA)" if device == "cuda" else "CPU"
        print(f"  [OK] Model loaded successfully on {device_used}!")
        
        # Estimate processing time (rough estimate: 1x real-time for large-v3 on CPU)
        print(f"\n[STEP 5/6] Starting transcription...")
        print(f"  Processing {len(files_to_process)} file(s)...")
        print(f"  [INFO] Transcription typically takes 1-2x the audio duration.")
        print(f"  [INFO] You can monitor progress below.\n")
        
        # Process each file
        successful = 0
        failed = 0
        start_time = datetime.now()
        
        for i, input_file in enumerate(files_to_process, 1):
            try:
                file_start = datetime.now()
                print(f"\n{'='*80}")
                print(f"[FILE {i}/{len(files_to_process)}] {input_file.name}")
                print(f"{'='*80}")
                
                # Create a subfolder for this lecture in processed/
                base_name = input_file.stem
                lecture_folder = processed_folder / base_name
                
                # Handle duplicate folder names
                counter = 1
                while lecture_folder.exists():
                    lecture_folder = processed_folder / f"{base_name}_{counter}"
                    counter += 1
                
                # Create the lecture subfolder
                lecture_folder.mkdir(exist_ok=True)
                
                # Create output filename - use consistent base name
                output_filename = f"{base_name}_transcript.txt"
                output_file = lecture_folder / output_filename
                
                # Transcribe (will save transcript and enhanced audio to lecture_folder)
                transcribe_lecture(
                    input_file=input_file,
                    output_file=output_file,
                    model=model,
                    processed_folder=lecture_folder,
                    language=language,
                    include_timestamps=include_timestamps,
                    include_speaker_segments=include_segments,
                    normalize_audio=normalize,
                    target_dBFS=target_dBFS if target_dBFS else -20.0,  # Pass default if None
                    max_gain=30.0,
                    device=device
                )
                
                # Extract class code from filename and archive ONLY the original file to zip
                class_code = extract_class_code(input_file.name)
                print(f"\n  [ARCHIVING] Archiving original file to zip (Class: {class_code})...")
                if archive_lecture_to_zip(input_file, archived_zip_path, class_code):
                    print(f"  [OK] Original file archived to {archived_zip_path.name}")
                    # Delete the original file from queue (it's now in the archive)
                    input_file.unlink()
                    print(f"  [OK] Removed original file from queue (archived)")
                else:
                    print(f"  [WARNING] Archive failed, original file remains in queue")
                
                # Processed files (enhanced audio, transcript, JSON) remain in processed/lecture_folder
                print(f"  [OK] Processed files remain in: {lecture_folder}")
                
                file_duration = (datetime.now() - file_start).total_seconds()
                print(f"  [OK] File processed in {file_duration/60:.1f} minutes")
                print(f"  [OK] Archived to: {archived_zip_path.name} (Class: {class_code})")
                
                successful += 1
                
            except Exception as e:
                print(f"\n  [ERROR] Error processing {input_file.name}")
                print(f"  [ERROR] Details: {e}")
                import traceback
                traceback.print_exc()
                failed += 1
                continue
        
        # Final summary
        total_duration = (datetime.now() - start_time).total_seconds()
        print(f"\n{'='*80}")
        print(f"[STEP 6/6] PROCESSING COMPLETE")
        print(f"{'='*80}")
        print(f"  [SUMMARY]")
        print(f"    Total files: {len(files_to_process)}")
        print(f"    Successful: {successful}")
        if failed > 0:
            print(f"    Failed: {failed}")
        print(f"    Total time: {total_duration/60:.1f} minutes")
        print(f"\n  [OUTPUT LOCATIONS]")
        print(f"    Archived recordings: {archived_zip_path}")
        print(f"    (All lectures archived to zip file, organized by class code)")
        if successful > 0:
            print(f"    Processed files: {processed_folder}")
            print(f"    (Temporary subfolders removed after archiving)")
        print(f"{'='*80}")
        print(f"\n[SUCCESS] Transcription complete! All lectures archived to '{archived_zip_path.name}' (organized by class code).")
        print(f"="*80)
        
        return 0 if failed == 0 else 1
        
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
